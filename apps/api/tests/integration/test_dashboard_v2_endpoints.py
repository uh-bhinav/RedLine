"""
Integration tests for the Phase 5.3 (dashboard v2) backend additions:
transcript + is_chaos_case on run detail, ARS history, error budget, drift
alerts (merged model+behavior), agent-scoped load runs, ClickHouse traces,
GET /eval-suites, and GET /auth/me.

Follows test_tenant_isolation.py's fixture pattern: real Postgres, real
TestClient(app), two independent tenants, cross-tenant probing asserted on
every new endpoint rather than inventing a parallel convention.

Requires:
  - Postgres running (docker compose up postgres)
  - `alembic upgrade head` already run

Run from the repo root:
    pytest apps/api/tests/integration/test_dashboard_v2_endpoints.py -v -m integration
"""
from __future__ import annotations

import hashlib
import secrets
import uuid

import pytest
from fastapi.testclient import TestClient

from apps.api.core.auth import create_access_token, hash_password
from apps.api.core.db import SessionLocal
from apps.api.main import app
from apps.api.models import (
    Agent,
    AgentVersion,
    ApiKey,
    ARSSnapshot,
    BehaviorDiff,
    DriftAlert,
    EvalCase,
    EvalCaseResult,
    EvalRun,
    EvalSuite,
    LoadRun,
    Tenant,
    User,
)
from apps.api.services.adapters.chaos_adapter import CHAOS_MARKER_TOOL_NAME

pytestmark = pytest.mark.integration


class _Fixture:
    def __init__(self, tenant, agent, version, suite, run, case_result, raw_key, user, access_token):
        self.tenant = tenant
        self.agent = agent
        self.version = version
        self.suite = suite
        self.run = run
        self.case_result = case_result
        self.raw_key = raw_key
        self.user = user
        self.access_token = access_token

    @property
    def headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.raw_key}"}

    @property
    def jwt_headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.access_token}"}


def _make_fixture(db, label: str) -> _Fixture:
    tenant = Tenant(name=f"dashv2-test-{label}-{uuid.uuid4().hex[:8]}")
    db.add(tenant)
    db.flush()

    agent = Agent(tenant_id=tenant.id, name=f"agent-{label}", description=f"tenant {label} agent")
    db.add(agent)
    db.flush()

    version = AgentVersion(
        agent_id=agent.id,
        version_label="v1",
        model_name="gemini-2.0-flash",
        prompt_text=f"dashv2 test prompt {label}",
        content_hash=hashlib.sha256(f"{label}-v1".encode()).hexdigest(),
        entrypoint="apps.api.tests.unit.fixtures.dummy_agent:run_turn",
    )
    suite = EvalSuite(agent_id=agent.id, name=f"suite-{label}")
    db.add_all([version, suite])
    db.flush()

    case = EvalCase(
        suite_id=suite.id,
        case_key=f"case-{label}",
        turns=[{"role": "user", "content": "hi"}],
        expectations={},
    )
    db.add(case)
    db.flush()

    run = EvalRun(
        tenant_id=tenant.id,
        agent_version_id=version.id,
        suite_id=suite.id,
        status="completed",
        triggered_by="manual",
    )
    db.add(run)
    db.flush()

    # A chaos-faulted transcript -- exercises is_chaos_case=True on run detail.
    transcript = [
        {"role": "user", "content": "hello", "tool_calls": None},
        {
            "role": "assistant",
            "content": "[[CHAOS:timeout]] no response obtained",
            "tool_calls": [{"name": CHAOS_MARKER_TOOL_NAME, "arguments": {"mode": "timeout"}}],
        },
    ]
    case_result = EvalCaseResult(
        eval_run_id=run.id,
        case_id=case.id,
        passed=True,
        metrics={"cost_usd": 0.001, "latency_ms": 500},
        transcript=transcript,
        scorer_results={"ContainsMatchScorer": {"passed": True, "detail": "ok"}},
    )
    db.add(case_result)

    # ARS snapshot for the ars-history endpoint.
    db.add(ARSSnapshot(
        agent_version_id=version.id,
        eval_run_id=run.id,
        ars=0.75,
        correctness=0.8,
        safety=0.9,
        latency=0.7,
        cost=0.6,
    ))

    # Model-drift alert.
    db.add(DriftAlert(
        agent_version_id=version.id,
        suite_id=suite.id,
        drift_type="model",
        baseline_pass_rate=0.9,
        current_pass_rate=0.6,
        delta=-0.3,
        threshold=0.1,
        detail="pass rate regressed",
    ))

    # Behavior-drift (silent_drift) row -- needs a second run to diff against.
    run_b = EvalRun(
        tenant_id=tenant.id,
        agent_version_id=version.id,
        suite_id=suite.id,
        status="completed",
        triggered_by="manual",
    )
    db.add(run_b)
    db.flush()
    db.add(BehaviorDiff(
        agent_id=agent.id,
        version_a_id=version.id,
        version_b_id=version.id,
        suite_id=suite.id,
        eval_run_a_id=run.id,
        eval_run_b_id=run_b.id,
        code_changed=False,
        behavior_changed=True,
        mean_similarity=0.5,
        similarity_threshold=0.9,
        classification="silent_drift",
        per_case_similarity={f"case-{label}": 0.5},
        detail="behavior drifted",
    ))

    # A load run for the agent-scoped load-runs endpoint.
    db.add(LoadRun(
        tenant_id=tenant.id,
        agent_version_id=version.id,
        message="hi",
        concurrency=5,
        duration_seconds=10,
        status="completed",
        triggered_by="manual",
        p95_latency_ms=120.0,
        error_rate=0.0,
        cost_per_hour_usd=1.5,
    ))

    raw_key = f"rl_live_{secrets.token_urlsafe(32)}"
    db.add(ApiKey(
        tenant_id=tenant.id,
        name=f"dashv2-test-{label}",
        key_hash=hashlib.sha256(raw_key.encode()).hexdigest(),
        role="admin",
    ))

    user = User(
        tenant_id=tenant.id,
        email=f"dashv2-{label}-{uuid.uuid4().hex[:8]}@example.com",
        hashed_password=hash_password("not-a-real-password"),
        role="admin",
    )
    db.add(user)
    db.flush()

    access_token = create_access_token(user.id, tenant.id, user.role)

    db.commit()
    db.refresh(case_result)

    return _Fixture(tenant, agent, version, suite, run, case_result, raw_key, user, access_token)


@pytest.fixture(scope="module")
def fixtures():
    db = SessionLocal()
    try:
        a = _make_fixture(db, "a")
        b = _make_fixture(db, "b")
    except Exception:
        db.rollback()
        db.close()
        raise

    yield a, b

    try:
        for fx in (a, b):
            db.query(EvalCaseResult).filter(
                EvalCaseResult.eval_run_id.in_(
                    db.query(EvalRun.id).filter(EvalRun.tenant_id == fx.tenant.id)
                )
            ).delete(synchronize_session=False)
            db.query(ARSSnapshot).filter(
                ARSSnapshot.agent_version_id == fx.version.id
            ).delete(synchronize_session=False)
            db.query(BehaviorDiff).filter(BehaviorDiff.agent_id == fx.agent.id).delete(
                synchronize_session=False
            )
            db.query(DriftAlert).filter(
                DriftAlert.agent_version_id == fx.version.id
            ).delete(synchronize_session=False)
            db.query(LoadRun).filter(LoadRun.agent_version_id == fx.version.id).delete(
                synchronize_session=False
            )
            db.query(EvalRun).filter(EvalRun.tenant_id == fx.tenant.id).delete()
            db.query(EvalCase).filter(EvalCase.suite_id == fx.suite.id).delete()
            db.query(AgentVersion).filter(AgentVersion.agent_id == fx.agent.id).delete()
            db.query(EvalSuite).filter(EvalSuite.agent_id == fx.agent.id).delete()
            db.query(Agent).filter(Agent.id == fx.agent.id).delete()
            db.query(ApiKey).filter(ApiKey.tenant_id == fx.tenant.id).delete()
            db.query(User).filter(User.tenant_id == fx.tenant.id).delete()
            db.query(Tenant).filter(Tenant.id == fx.tenant.id).delete()
        db.commit()
    finally:
        db.close()


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


# ---------- transcript + is_chaos_case ----------

def test_run_detail_includes_transcript_and_chaos_flag(client, fixtures):
    a, _ = fixtures
    resp = client.get(f"/dashboard/runs/{a.run.id}", headers=a.headers)
    assert resp.status_code == 200
    case = resp.json()["case_results"][0]
    assert case["transcript"] == [
        {"role": "user", "content": "hello", "tool_calls": None},
        {
            "role": "assistant",
            "content": "[[CHAOS:timeout]] no response obtained",
            "tool_calls": [{"name": CHAOS_MARKER_TOOL_NAME, "arguments": {"mode": "timeout"}}],
        },
    ]
    assert case["is_chaos_case"] is True


# ---------- ARS history ----------

def test_ars_history_ordered_and_labeled(client, fixtures):
    a, b = fixtures
    resp = client.get(f"/dashboard/agents/{a.agent.id}/ars-history", headers=a.headers)
    assert resp.status_code == 200
    points = resp.json()
    assert len(points) == 1
    assert points[0]["version_label"] == "v1"
    assert points[0]["ars"] == 0.75

    # cross-tenant: B's key cannot read A's ars-history
    assert client.get(f"/dashboard/agents/{a.agent.id}/ars-history", headers=b.headers).status_code == 404


# ---------- error budget ----------

def test_error_budget_default_fallback_when_no_slo_policy(client, fixtures):
    a, _ = fixtures
    resp = client.get(f"/dashboard/agents/{a.agent.id}/error-budget", headers=a.headers)
    assert resp.status_code == 200
    body = resp.json()
    assert "target_ars" in body
    assert "exhausted" in body


# ---------- drift alerts ----------

def test_drift_alerts_merges_model_and_behavior(client, fixtures):
    a, b = fixtures
    resp = client.get(f"/dashboard/agents/{a.agent.id}/drift-alerts", headers=a.headers)
    assert resp.status_code == 200
    items = resp.json()
    types = {i["drift_type"] for i in items}
    assert types == {"model", "behavior"}

    assert client.get(f"/dashboard/agents/{a.agent.id}/drift-alerts", headers=b.headers).status_code == 404


# ---------- load runs ----------

def test_agent_load_runs_scoped(client, fixtures):
    a, b = fixtures
    resp = client.get(f"/dashboard/agents/{a.agent.id}/load-runs", headers=a.headers)
    assert resp.status_code == 200
    runs = resp.json()
    assert len(runs) == 1
    assert runs[0]["cost_per_hour_usd"] == 1.5

    assert client.get(f"/dashboard/agents/{a.agent.id}/load-runs", headers=b.headers).status_code == 404


# ---------- eval-suites list ----------

def test_eval_suites_list_tenant_isolated(client, fixtures):
    a, b = fixtures
    resp = client.get(f"/eval-suites?agent_id={a.agent.id}", headers=a.headers)
    assert resp.status_code == 200
    suites = resp.json()
    assert len(suites) == 1
    assert suites[0]["case_count"] == 1

    resp_b = client.get(f"/eval-suites?agent_id={a.agent.id}", headers=b.headers)
    assert resp_b.status_code == 404


# ---------- auth/me ----------

def test_auth_me_jwt_has_email(client, fixtures):
    a, _ = fixtures
    resp = client.get("/auth/me", headers=a.jwt_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["email"] == a.user.email
    assert body["user_id"] == str(a.user.id)


def test_auth_me_api_key_has_no_email(client, fixtures):
    a, _ = fixtures
    resp = client.get("/auth/me", headers=a.headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["email"] is None
    assert body["user_id"] is None


# ---------- cross-tenant probing on traces ----------

def test_run_traces_cross_tenant_404s(client, fixtures):
    a, b = fixtures
    # Not asserting ClickHouse content here (no trace rows seeded in this
    # fixture) -- only that ownership is checked in Postgres before any
    # ClickHouse query happens.
    resp = client.get(f"/dashboard/runs/{a.run.id}/traces", headers=b.headers)
    assert resp.status_code == 404
