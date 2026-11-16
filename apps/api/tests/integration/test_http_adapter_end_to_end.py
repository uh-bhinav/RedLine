"""
End-to-end integration test for HTTPAdapter (Phase 3 Section 2).

Runs the REAL eval engine against the REAL reference HTTP agent
(examples/http-agent/server.py), started in a background thread on a free port.
This is the test that proves the framework-agnostic claim: an agent RedLine never
imports, reached only over HTTP, produces genuine EvalCaseResult rows and a gate
verdict.

No LLM cost: the eval cases here deliberately configure no `judge_rubric`, so the
LLM judge short-circuits and only the deterministic scorers run.

Requires:
  - Postgres running (docker compose up postgres)
  - `alembic upgrade head` already run

Run from the repo root:
    pytest apps/api/tests/integration/test_http_adapter_end_to_end.py -v -m integration
"""
from __future__ import annotations

import hashlib
import socket
import threading
import time
import uuid

import httpx
import pytest
import uvicorn

from apps.api.core.db import SessionLocal
from apps.api.models import (
    ARSSnapshot,
    Agent,
    AgentVersion,
    EvalCase,
    EvalCaseResult,
    EvalRun,
    EvalSuite,
    GatePolicy,
    Tenant,
)
from apps.api.services import eval_engine
from apps.api.services.adapters import HTTPAdapter, build_adapter
from apps.api.services.gate_engine import evaluate as gate_evaluate

pytestmark = pytest.mark.integration


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def agent_url():
    """Starts the reference HTTP agent on a free port for the duration of the module."""
    import sys
    from pathlib import Path

    example_dir = Path(__file__).resolve().parents[4] / "examples" / "http-agent"
    if not (example_dir / "server.py").exists():
        pytest.skip(f"reference agent not found at {example_dir}")
    sys.path.insert(0, str(example_dir))

    from server import app  # noqa: E402

    port = _free_port()
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    url = f"http://127.0.0.1:{port}"
    deadline = time.time() + 15
    while time.time() < deadline:
        try:
            if httpx.get(f"{url}/health", timeout=1).status_code == 200:
                break
        except httpx.HTTPError:
            time.sleep(0.2)
    else:
        server.should_exit = True
        pytest.fail("reference HTTP agent did not become healthy within 15s")

    yield f"{url}/turn"

    server.should_exit = True
    thread.join(timeout=5)
    sys.path.remove(str(example_dir))


@pytest.fixture(scope="module")
def seeded(agent_url):
    """A tenant + agent + HTTP-entrypoint version + suite with two cases."""
    db = SessionLocal()
    try:
        tenant = Tenant(name=f"http-adapter-e2e-{uuid.uuid4().hex[:8]}")
        db.add(tenant)
        db.flush()

        agent = Agent(tenant_id=tenant.id, name=f"http-agent-{uuid.uuid4().hex[:6]}")
        db.add(agent)
        db.flush()

        version = AgentVersion(
            agent_id=agent.id,
            version_label="v1",
            model_name="reference-http-agent",
            prompt_text="reference agent, no prompt",
            content_hash=hashlib.sha256(agent_url.encode()).hexdigest(),
            entrypoint=agent_url,  # <-- a URL, not module:function
        )
        suite = EvalSuite(agent_id=agent.id, name="http-baseline")
        db.add_all([version, suite])
        db.flush()

        db.add_all([
            EvalCase(
                suite_id=suite.id,
                case_key="case_001_direct_answer",
                description="Answers a question the agent's knowledge base covers",
                turns=[{"role": "user", "content": "How long do I have to return an item?"}],
                expectations={"contains": ["30 days"], "max_latency_ms": 10000},
            ),
            EvalCase(
                suite_id=suite.id,
                case_key="case_002_multiturn_context",
                description="Second turn must use state returned by the first turn",
                turns=[
                    {"role": "user", "content": "What is your shipping policy?"},
                    {"role": "user", "content": "and that?"},
                ],
                expectations={"contains": ["earlier I said"], "max_latency_ms": 10000},
            ),
        ])
        db.add(GatePolicy(agent_id=agent.id, min_pass_rate=0.9))
        db.commit()

        ids = {
            "tenant_id": tenant.id,
            "agent_id": agent.id,
            "version_id": version.id,
            "suite_id": suite.id,
        }
    except Exception:
        db.rollback()
        db.close()
        raise

    yield ids

    try:
        run_ids = [r.id for r in db.query(EvalRun).filter(EvalRun.tenant_id == ids["tenant_id"])]
        if run_ids:
            # Phase 4 Section 1: ars_snapshots FKs to eval_runs, and run_eval() now
            # persists one automatically at completion -- delete it first or the
            # EvalRun delete below hits ars_snapshots_eval_run_id_fkey.
            db.query(ARSSnapshot).filter(
                ARSSnapshot.eval_run_id.in_(run_ids)
            ).delete(synchronize_session=False)
            db.query(EvalCaseResult).filter(
                EvalCaseResult.eval_run_id.in_(run_ids)
            ).delete(synchronize_session=False)
        db.query(EvalRun).filter(EvalRun.tenant_id == ids["tenant_id"]).delete()
        db.query(EvalCase).filter(EvalCase.suite_id == ids["suite_id"]).delete()
        db.query(GatePolicy).filter(GatePolicy.agent_id == ids["agent_id"]).delete()
        db.query(EvalSuite).filter(EvalSuite.id == ids["suite_id"]).delete()
        db.query(AgentVersion).filter(AgentVersion.id == ids["version_id"]).delete()
        db.query(Agent).filter(Agent.id == ids["agent_id"]).delete()
        db.query(Tenant).filter(Tenant.id == ids["tenant_id"]).delete()
        db.commit()
    finally:
        db.close()


# ---------- adapter against the live server ----------

def test_adapter_reaches_the_live_reference_agent(agent_url):
    adapter = build_adapter(agent_url)
    assert isinstance(adapter, HTTPAdapter)

    state: dict = {}
    result = adapter.run_turn(state, "How long do I have to return an item?")

    assert "30 days" in result.assistant_message
    assert result.cost_usd > 0
    assert result.latency_ms >= 0
    assert result.tool_calls[0].name == "knowledge_base_lookup"
    assert state["turns"] == 1, "session_state was not written back from the live agent"


def test_multi_turn_state_survives_across_real_http_calls(agent_url):
    adapter = build_adapter(agent_url)
    state: dict = {}

    adapter.run_turn(state, "What is your shipping policy?")
    second = adapter.run_turn(state, "and that?")

    assert state["turns"] == 2
    assert "earlier I said" in second.assistant_message, (
        "the agent did not receive the state from turn 1"
    )


# ---------- the real eval engine, end to end ----------

def test_eval_engine_runs_a_suite_against_an_http_agent(seeded):
    db = SessionLocal()
    try:
        run = EvalRun(
            tenant_id=seeded["tenant_id"],
            agent_version_id=seeded["version_id"],
            suite_id=seeded["suite_id"],
            status="pending",
            triggered_by="manual",
        )
        db.add(run)
        db.commit()
        db.refresh(run)
        run_id = run.id
    finally:
        db.close()

    # The real engine. It never learns this agent is remote.
    eval_engine.run_eval(run_id)

    db = SessionLocal()
    try:
        completed = db.get(EvalRun, run_id)
        assert completed.status == "completed", f"run ended as {completed.status}"
        assert completed.started_at is not None
        assert completed.completed_at is not None

        results = db.query(EvalCaseResult).filter(
            EvalCaseResult.eval_run_id == run_id
        ).all()
        assert len(results) == 2, f"expected 2 case results, got {len(results)}"

        for r in results:
            assert r.passed is True, f"case failed: {r.scorer_results}"
            assert r.metrics["cost_usd"] > 0, "cost was not carried through HTTP"
            assert r.transcript, "transcript was not recorded"

        # The multi-turn case must show 4 turns (2 user + 2 assistant), proving
        # session_state round-tripped over HTTP inside the engine's own loop.
        multi = next(
            r for r in results
            if len(r.transcript) == 4
        )
        assert "earlier I said" in multi.transcript[3]["content"]

        gate = gate_evaluate(run_id)
        assert gate.passed is True, f"gate failed: {gate.reasons}"
    finally:
        db.close()


def test_engine_marks_the_run_failed_when_the_agent_is_unreachable(seeded):
    """A dead agent endpoint must fail the run, not hang or silently pass."""
    db = SessionLocal()
    try:
        dead_version = AgentVersion(
            agent_id=seeded["agent_id"],
            version_label="v-dead",
            model_name="reference-http-agent",
            prompt_text="points at a closed port",
            content_hash=hashlib.sha256(b"dead").hexdigest(),
            entrypoint=f"http://127.0.0.1:{_free_port()}/turn",
        )
        db.add(dead_version)
        db.flush()

        run = EvalRun(
            tenant_id=seeded["tenant_id"],
            agent_version_id=dead_version.id,
            suite_id=seeded["suite_id"],
            status="pending",
            triggered_by="manual",
        )
        db.add(run)
        db.commit()
        db.refresh(run)
        run_id, dead_version_id = run.id, dead_version.id
    finally:
        db.close()

    with pytest.raises(Exception):
        eval_engine.run_eval(run_id)

    db = SessionLocal()
    try:
        assert db.get(EvalRun, run_id).status == "failed"
    finally:
        db.query(EvalRun).filter(EvalRun.id == run_id).delete()
        db.query(AgentVersion).filter(AgentVersion.id == dead_version_id).delete()
        db.commit()
        db.close()
