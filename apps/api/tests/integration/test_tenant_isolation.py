"""
Tenant isolation integration test (Phase 3 Section 1).

This is the test that had to exist before Phase 4. Until now the platform carried
`tenant_id` on every row but resolved the *current* tenant with
`db.query(Tenant).first()` in two routers, and served `/dashboard` with no auth at
all. Both are correct on a laptop with one seeded tenant and are cross-tenant data
leaks the moment a second tenant exists.

The test creates two real tenants with their own agents, versions and eval runs, then
asserts that a credential scoped to tenant A cannot observe tenant B through any
read path -- including by guessing tenant B's UUIDs directly.

Requires:
  - Postgres running (docker compose up postgres)
  - `alembic upgrade head` already run

Run from the repo root:
    pytest apps/api/tests/integration/test_tenant_isolation.py -v -m integration
"""
from __future__ import annotations

import hashlib
import secrets
import uuid

import pytest
from fastapi.testclient import TestClient

from apps.api.core.db import SessionLocal
from apps.api.main import app
from apps.api.models import Agent, AgentVersion, ApiKey, EvalRun, EvalSuite, Tenant

pytestmark = pytest.mark.integration


class _TenantFixture:
    """One fully-populated tenant: tenant + agent + version + suite + run + api key."""

    def __init__(self, tenant: Tenant, agent: Agent, run: EvalRun, raw_key: str):
        self.tenant = tenant
        self.agent = agent
        self.run = run
        self.raw_key = raw_key

    @property
    def headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.raw_key}"}


def _make_tenant(db, label: str, role: str = "admin") -> _TenantFixture:
    tenant = Tenant(name=f"isolation-test-{label}-{uuid.uuid4().hex[:8]}")
    db.add(tenant)
    db.flush()

    agent = Agent(tenant_id=tenant.id, name=f"agent-{label}", description=f"tenant {label} agent")
    db.add(agent)
    db.flush()

    version = AgentVersion(
        agent_id=agent.id,
        version_label="v1",
        model_name="gemini-2.0-flash",
        prompt_text=f"isolation test prompt for tenant {label}",
        content_hash=hashlib.sha256(label.encode()).hexdigest(),
        entrypoint="apps.api.tests.unit.fixtures.dummy_agent:run_turn",
    )
    suite = EvalSuite(agent_id=agent.id, name=f"suite-{label}")
    db.add_all([version, suite])
    db.flush()

    run = EvalRun(
        tenant_id=tenant.id,
        agent_version_id=version.id,
        suite_id=suite.id,
        status="pending",
        triggered_by="manual",  # ck_eval_runs_triggered_by allows only 'manual' | 'ci'
    )
    db.add(run)
    db.flush()

    raw_key = f"rl_live_{secrets.token_urlsafe(32)}"
    db.add(ApiKey(
        tenant_id=tenant.id,
        name=f"isolation-test-{label}",
        key_hash=hashlib.sha256(raw_key.encode()).hexdigest(),
        role=role,
    ))
    db.commit()

    return _TenantFixture(tenant=tenant, agent=agent, run=run, raw_key=raw_key)


@pytest.fixture(scope="module")
def tenants():
    """Two independent tenants, torn down afterwards so the test is re-runnable."""
    db = SessionLocal()
    try:
        a = _make_tenant(db, "a")
        b = _make_tenant(db, "b")
    except Exception:
        db.rollback()
        db.close()
        raise

    yield a, b

    # Teardown, children first (no cascade configured on these FKs).
    try:
        for fx in (a, b):
            db.query(EvalRun).filter(EvalRun.tenant_id == fx.tenant.id).delete()
            version_ids = [
                v.id for v in db.query(AgentVersion).filter(AgentVersion.agent_id == fx.agent.id)
            ]
            db.query(AgentVersion).filter(AgentVersion.id.in_(version_ids)).delete(
                synchronize_session=False
            )
            db.query(EvalSuite).filter(EvalSuite.agent_id == fx.agent.id).delete()
            db.query(Agent).filter(Agent.id == fx.agent.id).delete()
            db.query(ApiKey).filter(ApiKey.tenant_id == fx.tenant.id).delete()
            db.query(Tenant).filter(Tenant.id == fx.tenant.id).delete()
        db.commit()
    finally:
        db.close()


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


# ---------- Auth is actually required ----------

def test_dashboard_rejects_unauthenticated_requests(client, tenants):
    """The Phase 1 behaviour -- /dashboard served with no auth -- must be gone."""
    a, _ = tenants

    assert client.get("/dashboard/agents").status_code == 401
    assert client.get(f"/dashboard/agents/{a.agent.id}").status_code == 401
    assert client.get(f"/dashboard/runs/{a.run.id}").status_code == 401


def test_dashboard_rejects_invalid_api_key(client):
    bad = {"Authorization": "Bearer rl_live_definitely-not-a-real-key"}
    assert client.get("/dashboard/agents", headers=bad).status_code == 401


# ---------- Listing is scoped ----------

def test_agent_list_shows_only_own_tenants_agents(client, tenants):
    a, b = tenants

    resp = client.get("/dashboard/agents", headers=a.headers)
    assert resp.status_code == 200
    ids = {item["id"] for item in resp.json()}

    assert str(a.agent.id) in ids
    assert str(b.agent.id) not in ids, "tenant A can see tenant B's agent in the list"


def test_each_tenant_sees_a_different_agent_list(client, tenants):
    """Guards against the `Tenant.first()` bug specifically: under that bug both
    credentials would resolve to whichever tenant was inserted first, and these two
    lists would be identical."""
    a, b = tenants

    list_a = {i["id"] for i in client.get("/dashboard/agents", headers=a.headers).json()}
    list_b = {i["id"] for i in client.get("/dashboard/agents", headers=b.headers).json()}

    assert list_a != list_b
    assert list_a.isdisjoint(list_b)


# ---------- Direct-UUID access is scoped ----------

def test_cannot_read_another_tenants_agent_by_id(client, tenants):
    a, b = tenants

    resp = client.get(f"/dashboard/agents/{b.agent.id}", headers=a.headers)
    assert resp.status_code == 404, (
        f"tenant A read tenant B's agent detail (status {resp.status_code})"
    )


def test_cannot_read_another_tenants_run_by_id(client, tenants):
    a, b = tenants

    resp = client.get(f"/dashboard/runs/{b.run.id}", headers=a.headers)
    assert resp.status_code == 404, (
        f"tenant A read tenant B's run detail (status {resp.status_code})"
    )


def test_cannot_read_another_tenants_run_via_eval_runs(client, tenants):
    a, b = tenants

    resp = client.get(f"/eval-runs/{b.run.id}", headers=a.headers)
    assert resp.status_code == 404


def test_foreign_resource_returns_404_not_403(client, tenants):
    """404, not 403 -- a 403 confirms the resource exists and leaks the existence of
    another tenant's data to anyone probing UUIDs."""
    a, b = tenants

    resp = client.get(f"/dashboard/agents/{b.agent.id}", headers=a.headers)
    assert resp.status_code == 404
    assert resp.status_code != 403


def test_own_resources_are_still_readable(client, tenants):
    """The isolation must not have been achieved by breaking the happy path."""
    a, _ = tenants

    agent_resp = client.get(f"/dashboard/agents/{a.agent.id}", headers=a.headers)
    assert agent_resp.status_code == 200
    assert agent_resp.json()["id"] == str(a.agent.id)

    run_resp = client.get(f"/dashboard/runs/{a.run.id}", headers=a.headers)
    assert run_resp.status_code == 200
    assert run_resp.json()["id"] == str(a.run.id)


# ---------- RBAC on the mutating path ----------

def test_viewer_cannot_trigger_an_eval_run(client, tenants):
    """Triggering an eval spends the tenant's LLM budget -- not a Viewer action."""
    a, _ = tenants
    db = SessionLocal()
    raw_key = f"rl_live_{secrets.token_urlsafe(32)}"
    try:
        db.add(ApiKey(
            tenant_id=a.tenant.id,
            name="isolation-test-viewer",
            key_hash=hashlib.sha256(raw_key.encode()).hexdigest(),
            role="viewer",
        ))
        db.commit()

        resp = client.post(
            "/eval-runs",
            headers={"Authorization": f"Bearer {raw_key}"},
            json={
                "agent_version_id": str(uuid.uuid4()),
                "suite_id": str(uuid.uuid4()),
                "triggered_by": "manual",
            },
        )
        assert resp.status_code == 403
    finally:
        db.query(ApiKey).filter(ApiKey.name == "isolation-test-viewer").delete()
        db.commit()
        db.close()


def test_viewer_can_still_read_the_dashboard(client, tenants):
    a, _ = tenants
    db = SessionLocal()
    raw_key = f"rl_live_{secrets.token_urlsafe(32)}"
    try:
        db.add(ApiKey(
            tenant_id=a.tenant.id,
            name="isolation-test-viewer-read",
            key_hash=hashlib.sha256(raw_key.encode()).hexdigest(),
            role="viewer",
        ))
        db.commit()

        resp = client.get(
            "/dashboard/agents", headers={"Authorization": f"Bearer {raw_key}"}
        )
        assert resp.status_code == 200
    finally:
        db.query(ApiKey).filter(ApiKey.name == "isolation-test-viewer-read").delete()
        db.commit()
        db.close()
