"""
End-to-end integration test for Agent Chaos Engineering (Phase 4 Section 3).

Runs the REAL eval engine, real Postgres, and the zero-cost dummy_agent fixture (no
LLM calls at all -- this test needs none, since it verifies the fault-injection and
recovery-scoring pipeline itself, not LLM-judged nuance). Proves the whole chain:

  suite case's `chaos` block (in expectations JSONB)
    -> eval_engine._build_case_adapter() wraps the adapter for THIS case only
    -> ChaosAdapter intercepts the targeted turn, real adapter untouched otherwise
    -> the eval run COMPLETES rather than crashing on the injected fault
    -> the transcript carries the chaos marker on the faulted turn
    -> RecoveryScorer reads it and scores correctly
    -> a case with no `chaos` block is completely unaffected (baseline)

Requires:
  - Postgres running (docker compose up postgres)

Run from the repo root:
    pytest apps/api/tests/integration/test_chaos_end_to_end.py -v -m integration
"""
from __future__ import annotations

import hashlib
import uuid

import pytest

from apps.api.core.db import SessionLocal
from apps.api.models import (
    Agent,
    AgentVersion,
    ARSSnapshot,
    EvalCase,
    EvalCaseResult,
    EvalRun,
    EvalSuite,
    Tenant,
)
from apps.api.services import eval_engine
from apps.api.services.adapters.chaos_adapter import has_chaos_marker
from apps.api.services.gate_engine import evaluate as gate_evaluate

pytestmark = pytest.mark.integration

DUMMY_ENTRYPOINT = "apps.api.tests.unit.fixtures.dummy_agent:run_turn"


@pytest.fixture
def seeded():
    """A tenant + agent + dummy-agent version + a 2-case suite: one case configures
    chaos on its first turn, the other has no chaos block at all (the baseline
    control)."""
    db = SessionLocal()
    try:
        tenant = Tenant(name=f"chaos-e2e-{uuid.uuid4().hex[:8]}")
        db.add(tenant)
        db.flush()

        agent = Agent(tenant_id=tenant.id, name=f"chaos-agent-{uuid.uuid4().hex[:6]}")
        db.add(agent)
        db.flush()

        version = AgentVersion(
            agent_id=agent.id, version_label="v1", model_name="dummy",
            prompt_text="dummy agent, no prompt",
            content_hash=hashlib.sha256(b"chaos-e2e").hexdigest(),
            entrypoint=DUMMY_ENTRYPOINT,
        )
        suite = EvalSuite(agent_id=agent.id, name=f"chaos-suite-{uuid.uuid4().hex[:6]}")
        db.add_all([version, suite])
        db.flush()

        db.add_all([
            EvalCase(
                suite_id=suite.id,
                case_key="case_chaos_timeout_first_turn",
                description="turn 0 is chaos-faulted (timeout); turn 1 is real",
                turns=[
                    {"role": "user", "content": "first question"},
                    {"role": "user", "content": "second question"},
                ],
                expectations={
                    "chaos": {"mode": "timeout", "target_turn_indices": [0]},
                },
            ),
            EvalCase(
                suite_id=suite.id,
                case_key="case_baseline_no_chaos",
                description="no chaos block -- must be completely unaffected",
                turns=[{"role": "user", "content": "hello"}],
                expectations={},
            ),
        ])
        db.commit()

        ids = {"tenant_id": tenant.id, "agent_id": agent.id, "version_id": version.id,
               "suite_id": suite.id}
    except Exception:
        db.rollback()
        db.close()
        raise

    yield ids

    try:
        run_ids = [r.id for r in db.query(EvalRun).filter(EvalRun.tenant_id == ids["tenant_id"])]
        if run_ids:
            db.query(ARSSnapshot).filter(ARSSnapshot.eval_run_id.in_(run_ids)).delete(
                synchronize_session=False
            )
            db.query(EvalCaseResult).filter(EvalCaseResult.eval_run_id.in_(run_ids)).delete(
                synchronize_session=False
            )
        db.query(EvalRun).filter(EvalRun.tenant_id == ids["tenant_id"]).delete()
        db.query(EvalCase).filter(EvalCase.suite_id == ids["suite_id"]).delete()
        db.query(EvalSuite).filter(EvalSuite.id == ids["suite_id"]).delete()
        db.query(AgentVersion).filter(AgentVersion.id == ids["version_id"]).delete()
        db.query(Agent).filter(Agent.id == ids["agent_id"]).delete()
        db.query(Tenant).filter(Tenant.id == ids["tenant_id"]).delete()
        db.commit()
    finally:
        db.close()


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

    eval_engine.run_eval(run_id)
    return run_id


def test_run_completes_despite_an_injected_total_failure(seeded):
    """The core claim: a chaos-injected timeout on one turn must not crash the
    whole eval run -- that would make chaos engineering useless, since there'd be
    nothing left to score."""
    run_id = _run_eval(seeded)

    db = SessionLocal()
    try:
        run = db.get(EvalRun, run_id)
        assert run.status == "completed", (
            f"run ended as {run.status} -- an injected fault must not fail the whole run"
        )
    finally:
        db.close()


def test_chaos_case_transcript_carries_the_marker_only_on_the_faulted_turn(seeded):
    run_id = _run_eval(seeded)

    db = SessionLocal()
    try:
        case = (
            db.query(EvalCase)
            .filter(EvalCase.suite_id == seeded["suite_id"],
                    EvalCase.case_key == "case_chaos_timeout_first_turn")
            .one()
        )
        result = (
            db.query(EvalCaseResult)
            .filter(EvalCaseResult.eval_run_id == run_id, EvalCaseResult.case_id == case.id)
            .one()
        )
        assistant_turns = [t for t in result.transcript if t["role"] == "assistant"]
        assert len(assistant_turns) == 2

        assert has_chaos_marker(assistant_turns[0]["tool_calls"]), (
            "turn 0 was targeted for chaos and must carry the marker"
        )
        assert not has_chaos_marker(assistant_turns[1]["tool_calls"]), (
            "turn 1 was NOT targeted and must be the real, unaffected dummy_agent response"
        )
        assert "second question" in assistant_turns[1]["content"], (
            "the real dummy_agent turn must have actually run and echoed the input"
        )
    finally:
        db.close()


def test_session_state_is_genuinely_untouched_by_the_faulted_turn(seeded):
    """dummy_agent's response embeds session_state['turn_count'] after incrementing
    it. If the faulted turn 0 had touched session_state, the real turn 1 would see
    turn_count=2 ('turn 2'). Because a total-failure fault must never call the real
    adapter, turn 1 is the agent's FIRST real invocation for this case and must see
    turn_count=1 ('turn 1') -- proving the untouched-session-state claim concretely,
    not just by inspecting ChaosAdapter's own unit tests in isolation."""
    run_id = _run_eval(seeded)

    db = SessionLocal()
    try:
        case = (
            db.query(EvalCase)
            .filter(EvalCase.suite_id == seeded["suite_id"],
                    EvalCase.case_key == "case_chaos_timeout_first_turn")
            .one()
        )
        result = (
            db.query(EvalCaseResult)
            .filter(EvalCaseResult.eval_run_id == run_id, EvalCaseResult.case_id == case.id)
            .one()
        )
        assistant_turns = [t for t in result.transcript if t["role"] == "assistant"]
        assert "(turn 1)" in assistant_turns[1]["content"], (
            f"expected the real agent's first genuine call to see turn_count=1, "
            f"got: {assistant_turns[1]['content']!r}"
        )
    finally:
        db.close()


def test_recovery_scorer_passes_when_the_session_continues_after_the_fault(seeded):
    run_id = _run_eval(seeded)

    db = SessionLocal()
    try:
        case = (
            db.query(EvalCase)
            .filter(EvalCase.suite_id == seeded["suite_id"],
                    EvalCase.case_key == "case_chaos_timeout_first_turn")
            .one()
        )
        result = (
            db.query(EvalCaseResult)
            .filter(EvalCaseResult.eval_run_id == run_id, EvalCaseResult.case_id == case.id)
            .one()
        )
        recovery = result.scorer_results["RecoveryScorer"]
        assert recovery["passed"] is True
        assert "fault injected" in recovery["detail"]
    finally:
        db.close()


def test_baseline_case_without_chaos_is_completely_unaffected(seeded):
    run_id = _run_eval(seeded)

    db = SessionLocal()
    try:
        case = (
            db.query(EvalCase)
            .filter(EvalCase.suite_id == seeded["suite_id"],
                    EvalCase.case_key == "case_baseline_no_chaos")
            .one()
        )
        result = (
            db.query(EvalCaseResult)
            .filter(EvalCaseResult.eval_run_id == run_id, EvalCaseResult.case_id == case.id)
            .one()
        )
        assistant_turn = next(t for t in result.transcript if t["role"] == "assistant")
        assert not has_chaos_marker(assistant_turn["tool_calls"])
        assert "(turn 1)" in assistant_turn["content"]
        assert result.scorer_results["RecoveryScorer"]["passed"] is True
        assert "no chaos fault" in result.scorer_results["RecoveryScorer"]["detail"]
    finally:
        db.close()


def test_gate_and_ars_still_compute_normally_for_a_run_containing_chaos(seeded):
    """Chaos must not break anything downstream of the eval run itself."""
    run_id = _run_eval(seeded)

    gate = gate_evaluate(run_id)
    assert isinstance(gate.passed, bool)

    db = SessionLocal()
    try:
        snapshot = db.query(ARSSnapshot).filter(ARSSnapshot.eval_run_id == run_id).first()
        assert snapshot is not None
        assert 0.0 <= snapshot.ars <= 1.0
    finally:
        db.close()
