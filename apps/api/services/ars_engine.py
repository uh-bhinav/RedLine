"""
Agent Reliability Score (ARS) + error budget.

ARS = 0.4*correctness + 0.2*safety + 0.2*latency + 0.2*cost, each component in [0,1],
computed from one completed eval run's per-case results. The error budget borrows the
SRE idea: look at the last WINDOW runs of an agent; each run whose ARS is below the
target "burns" budget, and once more than ALLOWED_BREACHES runs breached, the agent is
frozen (deployments blocked).
"""
from __future__ import annotations

import uuid

from pydantic import BaseModel
from sqlalchemy.orm import Session

from apps.api.models import (
    Agent,
    AgentVersion,
    ARSSnapshot,
    EvalCase,
    EvalCaseResult,
    EvalRun,
)

ARS_TARGET = 0.9
WINDOW = 5
ALLOWED_BREACHES = 2
WEIGHTS = {"correctness": 0.4, "safety": 0.2, "latency": 0.2, "cost": 0.2}
DEFAULT_MAX_LATENCY_MS = 5000
DEFAULT_MAX_COST_USD = 0.01


class ErrorBudget(BaseModel):
    status: str  # healthy | at_risk | frozen
    window: int
    runs_considered: int
    above_target: int
    breached: int
    allowed_breaches: int
    exhausted: bool
    target: float


def _ratio(hits: int, total: int) -> float:
    return round(hits / total, 4) if total else 1.0


def compute_snapshot(db: Session, eval_run: EvalRun) -> ARSSnapshot:
    results = db.query(EvalCaseResult).filter(EvalCaseResult.eval_run_id == eval_run.id).all()
    cases = {c.id: c for c in db.query(EvalCase).filter(EvalCase.suite_id == eval_run.suite_id)}
    total = len(results)

    correct = safe = fast = cheap = 0
    for r in results:
        case = cases.get(r.case_id)
        scorers = r.scorer_results or {}
        contains = scorers.get("ContainsMatchScorer", {})
        judge = scorers.get("LLMJudgeScorer", {})
        has_guard = bool(case and case.expectations.get("must_not_contain"))

        if r.passed:
            correct += 1
        forbidden = "forbidden" in str(contains.get("detail", ""))
        judge_failed = not judge.get("passed", True)
        if not forbidden and not (has_guard and judge_failed):
            safe += 1

        lat_ok = scorers.get("LatencyScorer", {}).get("passed", True)
        if "no max_latency" in str(scorers.get("LatencyScorer", {}).get("detail", "")):
            lat_ok = (r.metrics or {}).get("latency_ms", 0) <= DEFAULT_MAX_LATENCY_MS
        fast += 1 if lat_ok else 0

        cost_ok = scorers.get("CostScorer", {}).get("passed", True)
        if "no max_cost" in str(scorers.get("CostScorer", {}).get("detail", "")):
            cost_ok = (r.metrics or {}).get("cost_usd", 0.0) <= DEFAULT_MAX_COST_USD
        cheap += 1 if cost_ok else 0

    parts = {
        "correctness": _ratio(correct, total),
        "safety": _ratio(safe, total),
        "latency": _ratio(fast, total),
        "cost": _ratio(cheap, total),
    }
    ars = round(sum(parts[k] * w for k, w in WEIGHTS.items()), 4)

    snap = ARSSnapshot(
        agent_version_id=eval_run.agent_version_id, eval_run_id=eval_run.id, ars=ars, **parts
    )
    db.add(snap)
    db.commit()
    db.refresh(snap)
    return snap


def agent_snapshots(
    db: Session, agent_id: uuid.UUID, limit: int | None = None, as_of=None
) -> list[ARSSnapshot]:
    q = (
        db.query(ARSSnapshot)
        .join(AgentVersion, AgentVersion.id == ARSSnapshot.agent_version_id)
        .filter(AgentVersion.agent_id == agent_id)
    )
    if as_of is not None:
        q = q.filter(ARSSnapshot.created_at <= as_of)
    q = q.order_by(ARSSnapshot.created_at.desc())
    return q.limit(limit).all() if limit else q.all()


def evaluate_error_budget(db: Session, agent_id: uuid.UUID, as_of=None) -> ErrorBudget:
    recent = agent_snapshots(db, agent_id, limit=WINDOW, as_of=as_of)
    breached = sum(1 for s in recent if s.ars < ARS_TARGET)
    exhausted = breached > ALLOWED_BREACHES
    status = "frozen" if exhausted else ("at_risk" if breached > 0 else "healthy")
    return ErrorBudget(
        status=status,
        window=WINDOW,
        runs_considered=len(recent),
        above_target=len(recent) - breached,
        breached=breached,
        allowed_breaches=ALLOWED_BREACHES,
        exhausted=exhausted,
        target=ARS_TARGET,
    )


def tenant_agents(db: Session, tenant_id: uuid.UUID) -> list[Agent]:
    return db.query(Agent).filter(Agent.tenant_id == tenant_id).order_by(Agent.created_at).all()
