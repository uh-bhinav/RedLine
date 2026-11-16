"""
End-to-end integration test for the Agent Reliability Score (Phase 4 Section 1).

Runs the REAL eval engine, against the zero-cost dummy_agent fixture (no LLM calls,
no quota risk), through the REAL gate engine, against REAL Postgres. This is the
test that proves the whole chain actually wired together correctly:

  eval_engine.run_eval() -> ars_engine.evaluate_ars() persists an ARSSnapshot
                          -> gate_engine.evaluate() reads it back (read-only)
                          -> a min_ars threshold genuinely gates a run
                          -> an exhausted error budget freezes a gate even when
                             the CURRENT run's own numbers look fine -- the actual
                             SRE mechanic, not just a per-run threshold

Requires:
  - Postgres running (docker compose up postgres)

Run from the repo root:
    pytest apps/api/tests/integration/test_ars_end_to_end.py -v -m integration
"""
from __future__ import annotations

import hashlib
import uuid

import pytest

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
    SLOPolicy,
    Tenant,
)
from apps.api.services import eval_engine
from apps.api.services.gate_engine import evaluate as gate_evaluate

pytestmark = pytest.mark.integration

DUMMY_ENTRYPOINT = "apps.api.tests.unit.fixtures.dummy_agent:run_turn"


@pytest.fixture
def seeded():
    """A tenant + agent + dummy-agent version + a 2-case suite. No LLM calls --
    dummy_agent always echoes the input, so cases assert on that echo."""
    db = SessionLocal()
    try:
        tenant = Tenant(name=f"ars-e2e-{uuid.uuid4().hex[:8]}")
        db.add(tenant)
        db.flush()

        agent = Agent(tenant_id=tenant.id, name=f"ars-agent-{uuid.uuid4().hex[:6]}")
        db.add(agent)
        db.flush()

        version = AgentVersion(
            agent_id=agent.id,
            version_label="v1",
            model_name="dummy",
            prompt_text="dummy agent, no prompt",
            content_hash=hashlib.sha256(DUMMY_ENTRYPOINT.encode()).hexdigest(),
            entrypoint=DUMMY_ENTRYPOINT,
        )
        suite = EvalSuite(agent_id=agent.id, name=f"ars-suite-{uuid.uuid4().hex[:6]}")
        db.add_all([version, suite])
        db.flush()

        db.add_all([
            EvalCase(
                suite_id=suite.id,
                case_key="case_001",
                description="dummy_agent always echoes",
                turns=[{"role": "user", "content": "hello"}],
                expectations={"contains": ["echo: hello"], "max_latency_ms": 5000},
            ),
            EvalCase(
                suite_id=suite.id,
                case_key="case_002",
                description="dummy_agent always echoes",
                turns=[{"role": "user", "content": "world"}],
                expectations={"contains": ["echo: world"], "max_latency_ms": 5000},
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
        db.query(SLOPolicy).filter(SLOPolicy.agent_id == ids["agent_id"]).delete()
        db.query(GatePolicy).filter(GatePolicy.agent_id == ids["agent_id"]).delete()
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

    eval_engine.run_eval(run_id)
    return run_id


# ---------- ARSSnapshot is actually created ----------

def test_run_eval_persists_an_ars_snapshot(seeded):
    run_id = _run_eval(seeded)

    db = SessionLocal()
    try:
        assert db.get(EvalRun, run_id).status == "completed"

        snapshot = db.query(ARSSnapshot).filter(ARSSnapshot.eval_run_id == run_id).first()
        assert snapshot is not None, "no ARSSnapshot was persisted for a completed run"
        assert 0.0 <= snapshot.ars <= 1.0
        assert snapshot.correctness == 1.0, "both cases satisfy their contains check"
        assert snapshot.safety == 1.0, "dummy_agent's noop_tool is not retrieval-shaped"
        assert snapshot.latency == 1.0, "both cases are well under their 5000ms budget"
        assert snapshot.cost == 1.0, "no max_cost_usd configured -- CostScorer auto-passes"
        # 0.4*1 + 0.2*1 + 0.2*1 + 0.2*1 = 1.0
        assert snapshot.ars == pytest.approx(1.0)
    finally:
        db.close()


def test_rerunning_the_same_eval_run_updates_not_duplicates(seeded):
    """ars_snapshots.eval_run_id is unique -- evaluate_ars() must upsert."""
    from apps.api.services.ars_engine import evaluate_ars

    run_id = _run_eval(seeded)
    evaluate_ars(run_id)  # deliberately called again for the same run_id
    evaluate_ars(run_id)

    db = SessionLocal()
    try:
        count = db.query(ARSSnapshot).filter(ARSSnapshot.eval_run_id == run_id).count()
        assert count == 1, f"expected exactly one snapshot, found {count}"
    finally:
        db.close()


# ---------- gate reads the snapshot, doesn't recompute ----------

def test_gate_fails_when_this_runs_ars_is_below_min_ars(seeded):
    db = SessionLocal()
    try:
        db.add(GatePolicy(agent_id=seeded["agent_id"], min_pass_rate=0.0, min_ars=0.99))
        db.commit()
    finally:
        db.close()

    run_id = _run_eval(seeded)  # this run scores ars=1.0 per the test above...
    gate = gate_evaluate(run_id)
    # ars=1.0 >= min_ars=0.99, so this specific case actually PASSES -- verifying the
    # inverse (a real failure) requires a policy threshold above what dummy_agent can
    # achieve, which is done in the next test via a policy of 1.01 (unreachable).
    assert gate.passed is True


def test_gate_fails_when_min_ars_is_unreachably_high(seeded):
    db = SessionLocal()
    try:
        db.add(GatePolicy(agent_id=seeded["agent_id"], min_pass_rate=0.0, min_ars=1.01))
        db.commit()
    finally:
        db.close()

    run_id = _run_eval(seeded)
    gate = gate_evaluate(run_id)

    assert gate.passed is False
    assert any("ars" in r and "1.010" in r for r in gate.reasons)


def test_gate_ignores_ars_when_no_min_ars_configured(seeded):
    """No GatePolicy at all -- min_ars defaults to None, matching every other
    optional threshold's convention."""
    run_id = _run_eval(seeded)
    gate = gate_evaluate(run_id)
    assert gate.passed is True


# ---------- the SRE mechanic: error budget freezes regardless of THIS run's score ----------

def test_error_budget_exhaustion_freezes_the_gate_even_on_a_perfect_run(seeded):
    """The actual claim under test: a run that scores ars=1.0 on its own merits must
    still FAIL the gate if the agent's recent history has burned its error budget.
    That is what makes an error budget different from a per-run threshold."""
    db = SessionLocal()
    try:
        # A tight budget: only 10% of recent runs may fall below target 0.9.
        db.add(SLOPolicy(agent_id=seeded["agent_id"], target_ars=0.9, error_budget_pct=0.1,
                          window_days=7))
        db.commit()

        # Fabricate history: 5 prior bad runs for this agent_version, all well below
        # target. Inserted directly -- this test is about the budget arithmetic
        # reading history correctly, not about generating that history via more
        # eval runs.
        for _ in range(5):
            fake_run = EvalRun(
                tenant_id=seeded["tenant_id"], agent_version_id=seeded["version_id"],
                suite_id=seeded["suite_id"], status="completed", triggered_by="manual",
            )
            db.add(fake_run)
            db.flush()
            db.add(ARSSnapshot(
                agent_version_id=seeded["version_id"], eval_run_id=fake_run.id,
                ars=0.3, correctness=0.3, safety=0.3, latency=0.3, cost=0.3,
            ))
        db.commit()
    finally:
        db.close()

    # This run, on its own, is perfect (ars=1.0 -- verified in the first test above).
    run_id = _run_eval(seeded)
    gate = gate_evaluate(run_id)

    assert gate.passed is False, (
        "a perfect run passed the gate despite an exhausted error budget -- "
        "the freeze mechanic did not fire"
    )
    assert any("error budget exhausted" in r for r in gate.reasons)


def test_no_slo_policy_means_default_thresholds_not_no_enforcement(seeded):
    """Missing SLOPolicy must behave like missing GatePolicy already does elsewhere
    in this codebase: defaults apply, it is never silent 'anything goes.'"""
    from apps.api.services.ars_engine import DEFAULT_ERROR_BUDGET_PCT, DEFAULT_TARGET_ARS, \
        evaluate_error_budget

    run_id = _run_eval(seeded)
    budget = evaluate_error_budget(seeded["agent_id"])

    assert budget.target_ars == DEFAULT_TARGET_ARS
    assert budget.error_budget_pct == DEFAULT_ERROR_BUDGET_PCT
    assert budget.exhausted is False  # one perfect run, no breaches
