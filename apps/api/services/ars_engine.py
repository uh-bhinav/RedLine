"""
Agent Reliability Score engine (Phase 4 Section 1 -- foundational doc §5.1).

    ARS = 0.4*correctness + 0.2*safety + 0.2*latency + 0.2*cost

The point of the formula isn't precision in the weights -- it's that reliability
becomes one number a deployment gate can read, the same way "99.9% uptime" gates an
infra decision. Two pure functions do all the real work, following the same
discipline as gate_engine._compute_gate_result(): numbers in, a result out, no DB,
no I/O, fully unit-testable.

  _compute_ars()       -- one run's four sub-scores and the composite, from counts.
  compute_error_budget() -- the SRE mechanic: given a history of ARS scores, is the
                            agent's error budget exhausted? If so, gate_engine
                            freezes deployments for that agent regardless of how the
                            current run itself scored -- an error budget is a
                            statement about the recent past, not just today.

evaluate_ars() is the DB-backed wrapper, exactly parallel to gate_engine.evaluate():
it resolves an eval run's case results, derives the four sub-scores from each case's
already-stored scorer_results (no re-scoring), persists an ARSSnapshot, and returns
the pure ARSResult for the gate to read.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass

from pydantic import BaseModel

from apps.api.core.db import SessionLocal
from apps.api.models import ARSSnapshot, AgentVersion, EvalCaseResult, EvalRun, SLOPolicy

# Weights from foundational doc §5.1. Not configurable per-agent (yet) -- a
# per-agent weighting scheme is a bigger product decision than this phase covers,
# and a single fixed formula is what makes ARS comparable across agents at all.
WEIGHT_CORRECTNESS = 0.4
WEIGHT_SAFETY = 0.2
WEIGHT_LATENCY = 0.2
WEIGHT_COST = 0.2

DEFAULT_TARGET_ARS = 0.9
DEFAULT_ERROR_BUDGET_PCT = 0.1
DEFAULT_WINDOW_DAYS = 7


class ARSResult(BaseModel):
    ars: float
    correctness: float
    safety: float
    latency: float
    cost: float
    detail: str


def _compute_ars(
    correctness_passed: int,
    safety_passed: int,
    latency_passed: int,
    cost_passed: int,
    total: int,
) -> ARSResult:
    """Pure function -- no DB, no I/O. Each sub-score is `passed / total` for the
    scorer(s) that measure that dimension:

        correctness -- ContainsMatchScorer AND LLMJudgeScorer both passed
        safety      -- SafetyScorer passed
        latency     -- LatencyScorer passed
        cost        -- CostScorer passed

    This mirrors how each existing scorer already expresses a threshold as
    pass/fail rather than inventing a new continuous curve per dimension (e.g.
    "how good is 3400ms against a 5000ms budget") that the platform doesn't
    otherwise use anywhere.
    """
    if total == 0:
        return ARSResult(
            ars=0.0, correctness=0.0, safety=0.0, latency=0.0, cost=0.0,
            detail="no case results found for this run",
        )

    correctness = correctness_passed / total
    safety = safety_passed / total
    latency = latency_passed / total
    cost = cost_passed / total

    ars = (
        WEIGHT_CORRECTNESS * correctness
        + WEIGHT_SAFETY * safety
        + WEIGHT_LATENCY * latency
        + WEIGHT_COST * cost
    )

    detail = (
        f"ARS={ars:.3f} = 0.4*{correctness:.2f}(correctness) + 0.2*{safety:.2f}(safety) "
        f"+ 0.2*{latency:.2f}(latency) + 0.2*{cost:.2f}(cost)"
    )
    return ARSResult(
        ars=ars, correctness=correctness, safety=safety, latency=latency, cost=cost,
        detail=detail,
    )


@dataclass
class ErrorBudgetResult:
    exhausted: bool
    target_ars: float
    error_budget_pct: float
    window_size: int
    breaches: int
    breach_rate: float
    budget_remaining_pct: float
    detail: str


def compute_error_budget(
    recent_ars_scores: list[float],
    target_ars: float = DEFAULT_TARGET_ARS,
    error_budget_pct: float = DEFAULT_ERROR_BUDGET_PCT,
) -> ErrorBudgetResult:
    """Pure function -- no DB, no I/O.

    A run "breaches" the SLO if its ARS fell below target_ars. The error budget is
    the fraction of recent runs allowed to breach before deployments freeze
    (error_budget_pct). This is the direct SRE analogue of an uptime error budget,
    applied to ARS instead of availability.

    Deliberately takes a plain list of floats, not ARSSnapshot rows -- the DB-backed
    caller (evaluate_ars) resolves the window and hands over just the numbers, which
    is what keeps this testable with a bare list in a unit test.
    """
    if not recent_ars_scores:
        return ErrorBudgetResult(
            exhausted=False, target_ars=target_ars, error_budget_pct=error_budget_pct,
            window_size=0, breaches=0, breach_rate=0.0,
            budget_remaining_pct=error_budget_pct,
            detail="no ARS snapshots yet -- nothing to evaluate",
        )

    window_size = len(recent_ars_scores)
    breaches = sum(1 for s in recent_ars_scores if s < target_ars)
    breach_rate = breaches / window_size
    exhausted = breach_rate > error_budget_pct
    budget_remaining_pct = max(0.0, error_budget_pct - breach_rate)

    detail = (
        f"{breaches}/{window_size} recent run(s) scored below target ARS "
        f"{target_ars:.2f} ({breach_rate:.1%} breach rate vs {error_budget_pct:.1%} "
        f"allowed budget)"
    )
    return ErrorBudgetResult(
        exhausted=exhausted, target_ars=target_ars, error_budget_pct=error_budget_pct,
        window_size=window_size, breaches=breaches, breach_rate=breach_rate,
        budget_remaining_pct=budget_remaining_pct, detail=detail,
    )


def _sub_score_passed(scorer_results: dict, *scorer_names: str) -> bool:
    """True only if every named scorer is present and passed. A scorer missing from
    scorer_results (e.g. a run predating SafetyScorer's introduction) counts as not
    passed, not as "not applicable" -- silently treating missing data as success
    would let old runs report an inflated ARS."""
    return all(scorer_results.get(name, {}).get("passed") is True for name in scorer_names)


def evaluate_ars(eval_run_id: uuid.UUID) -> ARSResult:
    """DB-backed wrapper, parallel to gate_engine.evaluate(). Resolves the run's case
    results, derives the four sub-score pass counts from each case's already-stored
    scorer_results, computes ARS via the pure function, and persists an
    ARSSnapshot. Re-running this for the same eval_run_id updates the existing
    snapshot rather than creating a duplicate (ars_snapshots.eval_run_id is unique).
    """
    db = SessionLocal()
    try:
        eval_run = db.get(EvalRun, eval_run_id)
        if eval_run is None:
            raise ValueError(f"eval_run {eval_run_id} not found")

        case_results = (
            db.query(EvalCaseResult).filter(EvalCaseResult.eval_run_id == eval_run.id).all()
        )

        correctness_passed = sum(
            1 for r in case_results
            if _sub_score_passed(r.scorer_results, "ContainsMatchScorer", "LLMJudgeScorer")
        )
        safety_passed = sum(
            1 for r in case_results if _sub_score_passed(r.scorer_results, "SafetyScorer")
        )
        latency_passed = sum(
            1 for r in case_results if _sub_score_passed(r.scorer_results, "LatencyScorer")
        )
        cost_passed = sum(
            1 for r in case_results if _sub_score_passed(r.scorer_results, "CostScorer")
        )

        result = _compute_ars(
            correctness_passed=correctness_passed,
            safety_passed=safety_passed,
            latency_passed=latency_passed,
            cost_passed=cost_passed,
            total=len(case_results),
        )

        existing = (
            db.query(ARSSnapshot).filter(ARSSnapshot.eval_run_id == eval_run.id).first()
        )
        if existing is not None:
            existing.ars = result.ars
            existing.correctness = result.correctness
            existing.safety = result.safety
            existing.latency = result.latency
            existing.cost = result.cost
        else:
            db.add(ARSSnapshot(
                agent_version_id=eval_run.agent_version_id,
                eval_run_id=eval_run.id,
                ars=result.ars,
                correctness=result.correctness,
                safety=result.safety,
                latency=result.latency,
                cost=result.cost,
            ))
        db.commit()

        return result
    finally:
        db.close()


def evaluate_error_budget(agent_id: uuid.UUID) -> ErrorBudgetResult:
    """DB-backed wrapper around compute_error_budget(). Resolves the agent's
    SLOPolicy (or the defaults, if none is configured -- a missing policy must not
    silently mean "no budget enforcement," matching gate_engine's convention for a
    missing GatePolicy) and the ARS history across all of the agent's versions
    within the policy's window, oldest first.
    """
    db = SessionLocal()
    try:
        policy = db.query(SLOPolicy).filter(SLOPolicy.agent_id == agent_id).first()
        target_ars = policy.target_ars if policy else DEFAULT_TARGET_ARS
        error_budget_pct = policy.error_budget_pct if policy else DEFAULT_ERROR_BUDGET_PCT
        window_days = policy.window_days if policy else DEFAULT_WINDOW_DAYS

        from datetime import datetime, timedelta, timezone
        cutoff = datetime.now(timezone.utc) - timedelta(days=window_days)

        version_ids = [v.id for v in db.query(AgentVersion.id).filter(
            AgentVersion.agent_id == agent_id
        )]
        if not version_ids:
            return compute_error_budget([], target_ars, error_budget_pct)

        snapshots = (
            db.query(ARSSnapshot)
            .filter(
                ARSSnapshot.agent_version_id.in_(version_ids),
                ARSSnapshot.created_at >= cutoff,
            )
            .order_by(ARSSnapshot.created_at.asc())
            .all()
        )
        recent_scores = [s.ars for s in snapshots]

        return compute_error_budget(recent_scores, target_ars, error_budget_pct)
    finally:
        db.close()
