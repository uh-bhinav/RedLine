"""
End-to-end integration test for the Behavioral Diff Engine (Phase 4 Section 2).

Runs the REAL eval engine (zero-cost dummy_agent fixtures, no generate_content
calls) to produce REAL completed EvalRuns, then calls the REAL diff_engine functions,
which make REAL Gemini embedding calls (a separate quota metric from
generate_content, and the one this suite actually needs) and REAL cosine-similarity
math on REAL vectors. Only the classification thresholds are exercised with
synthetic data in test_diff_engine.py; this file exists to prove the embedding call
and the DB orchestration around it actually work end to end.

Two distinct code paths, matching the two real questions this feature answers:

  compute_diff_for_versions() -- "was switching from version A to version B safe?"
    Two DIFFERENT registered AgentVersion rows always have different content_hash
    (agent_versions.UNIQUE(agent_id, content_hash) guarantees it), so code_changed
    is always True here. Only SAFE_REFACTOR/EXPECTED_CHANGE are reachable.

  compute_diff_over_time() -- "did THIS version's behavior drift on its own?"
    Compares one version against itself across two of its own completed runs, so
    code_changed is always False. Only NO_OP/SILENT_DRIFT are reachable -- this is
    the actual alarm case the drift scheduler checks on a schedule.

Requires:
  - Postgres running (docker compose up postgres)
  - GEMINI_API_KEY set in .env (embedding calls only -- no generate_content)

Run from the repo root:
    pytest apps/api/tests/integration/test_diff_engine_end_to_end.py -v -m integration
"""
from __future__ import annotations

import hashlib
import uuid

import pytest

from sqlalchemy import or_

from apps.api.core.db import SessionLocal
from apps.api.models import (
    ARSSnapshot,
    Agent,
    AgentVersion,
    BehaviorDiff,
    EvalCase,
    EvalCaseResult,
    EvalRun,
    EvalSuite,
    Tenant,
)
from apps.api.services import eval_engine
from apps.api.services.diff_engine import (
    DiffClassification,
    DiffEngineError,
    compute_diff_for_versions,
    compute_diff_over_time,
)
from apps.api.tests.unit.fixtures import dummy_agent_drifting

pytestmark = pytest.mark.integration

DUMMY_ENTRYPOINT = "apps.api.tests.unit.fixtures.dummy_agent:run_turn"
DRIFTING_ENTRYPOINT = "apps.api.tests.unit.fixtures.dummy_agent_drifting:run_turn"


@pytest.fixture
def seeded():
    """A tenant + agent + a 1-case suite, with two independent registered versions:
    one on the plain dummy_agent (used for the cross-version comparison), one on
    dummy_agent_drifting (used for the over-time comparison)."""
    db = SessionLocal()
    try:
        tenant = Tenant(name=f"diff-e2e-{uuid.uuid4().hex[:8]}")
        db.add(tenant)
        db.flush()

        agent = Agent(tenant_id=tenant.id, name=f"diff-agent-{uuid.uuid4().hex[:6]}")
        db.add(agent)
        db.flush()

        version_a = AgentVersion(
            agent_id=agent.id, version_label="v1", model_name="dummy",
            prompt_text="dummy v1",
            content_hash=hashlib.sha256(b"dummy-v1").hexdigest(),
            entrypoint=DUMMY_ENTRYPOINT,
        )
        version_b = AgentVersion(
            agent_id=agent.id, version_label="v2", model_name="dummy",
            prompt_text="dummy v2 -- refactored, same behavior",
            content_hash=hashlib.sha256(b"dummy-v2").hexdigest(),
            entrypoint=DUMMY_ENTRYPOINT,
        )
        version_drifting = AgentVersion(
            agent_id=agent.id, version_label="v-drift", model_name="dummy-drifting",
            prompt_text="unchanged between both runs -- this is the whole point",
            content_hash=hashlib.sha256(b"dummy-drifting").hexdigest(),
            entrypoint=DRIFTING_ENTRYPOINT,
        )
        suite = EvalSuite(agent_id=agent.id, name=f"diff-suite-{uuid.uuid4().hex[:6]}")
        db.add_all([version_a, version_b, version_drifting, suite])
        db.flush()

        db.add(EvalCase(
            suite_id=suite.id,
            case_key="case_001",
            description="fixed input; response text depends on the fixture agent",
            turns=[{"role": "user", "content": "what is your refund policy"}],
            expectations={},
        ))
        db.commit()

        ids = {
            "tenant_id": tenant.id, "agent_id": agent.id, "suite_id": suite.id,
            "version_a_id": version_a.id, "version_b_id": version_b.id,
            "version_drifting_id": version_drifting.id,
        }
    except Exception:
        db.rollback()
        db.close()
        raise

    yield ids

    dummy_agent_drifting.MODE = "v1"  # reset the global the test mutates

    try:
        run_ids = [r.id for r in db.query(EvalRun).filter(EvalRun.tenant_id == ids["tenant_id"])]
        if run_ids:
            # Order matters: behavior_diffs and ars_snapshots both FK to eval_runs.
            # BehaviorDiff.eval_run_b_id must be checked too, not just eval_run_a_id
            # -- compute_diff_over_time's "older_run" can end up as either side.
            db.query(BehaviorDiff).filter(
                or_(
                    BehaviorDiff.eval_run_a_id.in_(run_ids),
                    BehaviorDiff.eval_run_b_id.in_(run_ids),
                )
            ).delete(synchronize_session=False)
            db.query(ARSSnapshot).filter(ARSSnapshot.eval_run_id.in_(run_ids)).delete(
                synchronize_session=False
            )
            db.query(EvalCaseResult).filter(EvalCaseResult.eval_run_id.in_(run_ids)).delete(
                synchronize_session=False
            )
        db.query(EvalRun).filter(EvalRun.tenant_id == ids["tenant_id"]).delete()
        db.query(EvalCase).filter(EvalCase.suite_id == ids["suite_id"]).delete()
        for vid in (ids["version_a_id"], ids["version_b_id"], ids["version_drifting_id"]):
            db.query(AgentVersion).filter(AgentVersion.id == vid).delete()
        db.query(EvalSuite).filter(EvalSuite.id == ids["suite_id"]).delete()
        db.query(Agent).filter(Agent.id == ids["agent_id"]).delete()
        db.query(Tenant).filter(Tenant.id == ids["tenant_id"]).delete()
        db.commit()
    finally:
        db.close()


def _run_eval(tenant_id, version_id, suite_id) -> uuid.UUID:
    db = SessionLocal()
    try:
        run = EvalRun(
            tenant_id=tenant_id, agent_version_id=version_id, suite_id=suite_id,
            status="pending", triggered_by="manual",
        )
        db.add(run)
        db.commit()
        db.refresh(run)
        run_id = run.id
    finally:
        db.close()

    eval_engine.run_eval(run_id)
    return run_id


# ---------- compute_diff_for_versions: cross-version comparison ----------

def test_diff_for_versions_requires_a_completed_run_first(seeded):
    with pytest.raises(DiffEngineError, match="no completed eval run"):
        compute_diff_for_versions(seeded["version_a_id"], seeded["version_b_id"], seeded["suite_id"])


def test_safe_refactor_detected_with_real_embeddings(seeded):
    """Two DIFFERENT versions, IDENTICAL dummy_agent behavior (same fixed input ->
    same deterministic echo text). Real embedding calls on identical text should
    be highly similar -- this is the live proof the embedding + cosine-similarity
    path actually works, not just the classifier."""
    _run_eval(seeded["tenant_id"], seeded["version_a_id"], seeded["suite_id"])
    _run_eval(seeded["tenant_id"], seeded["version_b_id"], seeded["suite_id"])

    result = compute_diff_for_versions(
        seeded["version_a_id"], seeded["version_b_id"], seeded["suite_id"]
    )

    assert result.code_changed is True, "two distinct registered versions always differ in hash"
    assert result.mean_similarity > 0.95, (
        f"identical text embedded twice scored only {result.mean_similarity} -- "
        f"either the embedding call or the cosine math is wrong"
    )
    assert result.classification == DiffClassification.SAFE_REFACTOR


def test_diff_for_versions_is_persisted(seeded):
    _run_eval(seeded["tenant_id"], seeded["version_a_id"], seeded["suite_id"])
    _run_eval(seeded["tenant_id"], seeded["version_b_id"], seeded["suite_id"])
    compute_diff_for_versions(seeded["version_a_id"], seeded["version_b_id"], seeded["suite_id"])

    db = SessionLocal()
    try:
        row = (
            db.query(BehaviorDiff)
            .filter(BehaviorDiff.agent_id == seeded["agent_id"])
            .order_by(BehaviorDiff.created_at.desc())
            .first()
        )
        assert row is not None
        assert row.classification == "safe_refactor"
        assert "case_001" in row.per_case_similarity
    finally:
        db.close()


def test_rediffing_appends_a_new_row_not_an_upsert(seeded):
    """Unlike ars_snapshots, behavior_diffs is append-only -- each computation is
    its own historical record."""
    _run_eval(seeded["tenant_id"], seeded["version_a_id"], seeded["suite_id"])
    _run_eval(seeded["tenant_id"], seeded["version_b_id"], seeded["suite_id"])

    compute_diff_for_versions(seeded["version_a_id"], seeded["version_b_id"], seeded["suite_id"])
    compute_diff_for_versions(seeded["version_a_id"], seeded["version_b_id"], seeded["suite_id"])

    db = SessionLocal()
    try:
        count = db.query(BehaviorDiff).filter(BehaviorDiff.agent_id == seeded["agent_id"]).count()
        assert count == 2
    finally:
        db.close()


# ---------- compute_diff_over_time: the genuine silent-drift alarm ----------

def test_over_time_requires_two_completed_runs(seeded):
    _run_eval(seeded["tenant_id"], seeded["version_drifting_id"], seeded["suite_id"])

    with pytest.raises(DiffEngineError, match="need at least 2"):
        compute_diff_over_time(seeded["version_drifting_id"], seeded["suite_id"])


def test_no_op_when_the_same_version_answers_consistently(seeded):
    """Same version, same MODE both times -- code did not change AND behavior did
    not change. This is the common case a scheduled check should mostly see."""
    dummy_agent_drifting.MODE = "v1"
    _run_eval(seeded["tenant_id"], seeded["version_drifting_id"], seeded["suite_id"])
    _run_eval(seeded["tenant_id"], seeded["version_drifting_id"], seeded["suite_id"])

    result = compute_diff_over_time(seeded["version_drifting_id"], seeded["suite_id"])

    assert result.code_changed is False, "it is literally the same AgentVersion row both times"
    assert result.classification == DiffClassification.NO_OP


def test_silent_drift_detected_when_the_same_version_answers_differently(seeded):
    """The alarm case, constructed for real: the SAME registered version (same
    content_hash, same row) produces genuinely different real-embedded text across
    two of its own completed runs. Nobody touched the code -- this is exactly what
    'the provider silently changed the model underneath the agent' looks like."""
    dummy_agent_drifting.MODE = "v1"
    _run_eval(seeded["tenant_id"], seeded["version_drifting_id"], seeded["suite_id"])

    dummy_agent_drifting.MODE = "v2"
    _run_eval(seeded["tenant_id"], seeded["version_drifting_id"], seeded["suite_id"])

    result = compute_diff_over_time(seeded["version_drifting_id"], seeded["suite_id"])

    assert result.code_changed is False, "same AgentVersion row -- content_hash never changed"
    assert result.behavior_changed is True, (
        f"'30 day refund window' vs 'no refunds ever' scored {result.mean_similarity} -- "
        f"expected clearly below threshold"
    )
    assert result.classification == DiffClassification.SILENT_DRIFT
