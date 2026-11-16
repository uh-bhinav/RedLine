"""
Integration test for EvalRun.error (follow-up from Phase 3.3): a failed run used
to be visible only as status='failed' with no reason -- the actual exception was
recorded in the OTel span and the ClickHouse trace, neither of which the
dashboard or CLI ever reads back.

Reuses the same dead-HTTP-endpoint pattern already proven in
test_http_adapter_end_to_end.py to produce a REAL failure (not a mocked one),
and additionally asserts on the new `error` column and its exposure through the
real FastAPI app (TestClient, not just the DB row) via both /eval-runs/{id} and
/dashboard/runs/{id}.

Run from the repo root:
    pytest apps/api/tests/integration/test_eval_run_error_field.py -v -m integration
"""
from __future__ import annotations

import hashlib
import socket
import uuid

import pytest
from fastapi.testclient import TestClient

from apps.api.core.db import SessionLocal
from apps.api.main import app
from apps.api.models import (
    ARSSnapshot,
    Agent,
    AgentVersion,
    ApiKey,
    EvalCase,
    EvalCaseResult,
    EvalRun,
    EvalSuite,
    Tenant,
)
from apps.api.services import eval_engine

pytestmark = pytest.mark.integration


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def seeded():
    db = SessionLocal()
    try:
        tenant = Tenant(name=f"error-field-e2e-{uuid.uuid4().hex[:8]}")
        db.add(tenant)
        db.flush()

        agent = Agent(tenant_id=tenant.id, name=f"error-field-agent-{uuid.uuid4().hex[:6]}")
        db.add(agent)
        db.flush()

        # Points at a closed port -- guarantees a real AgentHTTPError from
        # HTTPAdapter, the same pattern test_http_adapter_end_to_end.py uses.
        version = AgentVersion(
            agent_id=agent.id, version_label="v1", model_name="dead",
            prompt_text="points at a closed port",
            content_hash=hashlib.sha256(b"error-field-e2e").hexdigest(),
            entrypoint=f"http://127.0.0.1:{_free_port()}/turn",
        )
        suite = EvalSuite(agent_id=agent.id, name=f"error-field-suite-{uuid.uuid4().hex[:6]}")
        db.add_all([version, suite])
        db.flush()

        case = EvalCase(
            suite_id=suite.id, case_key="case_001",
            turns=[{"role": "user", "content": "hello"}], expectations={},
        )
        db.add(case)

        raw_key = f"rl_live_{uuid.uuid4().hex}"
        db.add(ApiKey(
            tenant_id=tenant.id, name="error-field-e2e-key",
            key_hash=hashlib.sha256(raw_key.encode()).hexdigest(), role="admin",
        ))
        db.commit()

        ids = {
            "tenant_id": tenant.id, "agent_id": agent.id, "version_id": version.id,
            "suite_id": suite.id, "raw_key": raw_key,
        }
    except Exception:
        db.rollback()
        db.close()
        raise

    yield ids

    try:
        run_ids = [r.id for r in db.query(EvalRun).filter(EvalRun.tenant_id == ids["tenant_id"])]
        if run_ids:
            # run_eval() persists an ARS snapshot + case results on completion --
            # both FK to eval_runs and must go first (same ordering fix already
            # applied in test_http_adapter_end_to_end.py).
            db.query(ARSSnapshot).filter(
                ARSSnapshot.eval_run_id.in_(run_ids)
            ).delete(synchronize_session=False)
            db.query(EvalCaseResult).filter(
                EvalCaseResult.eval_run_id.in_(run_ids)
            ).delete(synchronize_session=False)
        db.query(EvalRun).filter(EvalRun.tenant_id == ids["tenant_id"]).delete()
        db.query(EvalCase).filter(EvalCase.suite_id == ids["suite_id"]).delete()
        db.query(EvalSuite).filter(EvalSuite.id == ids["suite_id"]).delete()
        db.query(AgentVersion).filter(AgentVersion.id == ids["version_id"]).delete()
        db.query(Agent).filter(Agent.id == ids["agent_id"]).delete()
        db.query(ApiKey).filter(ApiKey.tenant_id == ids["tenant_id"]).delete()
        db.query(Tenant).filter(Tenant.id == ids["tenant_id"]).delete()
        db.commit()
    finally:
        db.close()


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def _run_eval(seeded) -> uuid.UUID:
    db = SessionLocal()
    try:
        run = EvalRun(
            tenant_id=seeded["tenant_id"], agent_version_id=seeded["version_id"],
            suite_id=seeded["suite_id"], status="pending", triggered_by="manual",
        )
        db.add(run)
        db.commit()
        db.refresh(run)
        run_id = run.id
    finally:
        db.close()

    with pytest.raises(Exception):
        eval_engine.run_eval(run_id)
    return run_id


def test_failed_run_persists_a_meaningful_error(seeded):
    run_id = _run_eval(seeded)

    db = SessionLocal()
    try:
        run = db.get(EvalRun, run_id)
        assert run.status == "failed"
        assert run.error is not None
        assert run.error != "", "error was populated but empty -- not meaningful"
        assert "AgentHTTPError" in run.error or "unreachable" in run.error, (
            f"expected the real HTTPAdapter failure reason, got: {run.error!r}"
        )
    finally:
        db.close()


def test_error_is_exposed_through_get_eval_runs(seeded, client):
    run_id = _run_eval(seeded)
    headers = {"Authorization": f"Bearer {seeded['raw_key']}"}

    resp = client.get(f"/eval-runs/{run_id}", headers=headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "failed"
    assert body["error"] is not None
    assert len(body["error"]) > 0


def test_error_is_exposed_through_dashboard_run_detail(seeded, client):
    run_id = _run_eval(seeded)
    headers = {"Authorization": f"Bearer {seeded['raw_key']}"}

    resp = client.get(f"/dashboard/runs/{run_id}", headers=headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["error"] is not None


def test_completed_run_has_no_error(seeded):
    """A successful run must not carry a stale error from an unrelated prior
    failure -- error is None unless THIS run actually failed."""
    db = SessionLocal()
    try:
        # Reuse the zero-cost dummy_agent for a run that genuinely succeeds.
        version = AgentVersion(
            agent_id=seeded["agent_id"], version_label="v-ok", model_name="dummy",
            prompt_text="succeeds", content_hash=hashlib.sha256(b"ok-e2e").hexdigest(),
            entrypoint="apps.api.tests.unit.fixtures.dummy_agent:run_turn",
        )
        db.add(version)
        db.flush()
        run = EvalRun(
            tenant_id=seeded["tenant_id"], agent_version_id=version.id,
            suite_id=seeded["suite_id"], status="pending", triggered_by="manual",
        )
        db.add(run)
        db.commit()
        db.refresh(run)
        run_id, version_id = run.id, version.id
    finally:
        db.close()

    eval_engine.run_eval(run_id)

    db = SessionLocal()
    try:
        run = db.get(EvalRun, run_id)
        assert run.status == "completed"
        assert run.error is None
    finally:
        db.query(ARSSnapshot).filter(ARSSnapshot.eval_run_id == run_id).delete()
        db.query(EvalCaseResult).filter(EvalCaseResult.eval_run_id == run_id).delete()
        db.query(EvalRun).filter(EvalRun.id == run_id).delete()
        db.query(AgentVersion).filter(AgentVersion.id == version_id).delete()
        db.commit()
        db.close()
