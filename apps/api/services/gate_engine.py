"""
Gate Engine (Phase1 roadmap Section 11).

evaluate(eval_run_id) -> GateResult. Computes pass_rate, avg_cost_usd, avg_latency_ms
across all EvalCaseResult rows for the run, compares each against the agent's
GatePolicy, and collects a human-readable reason string for every violated threshold.

A run with zero configured GatePolicy rows for its agent defaults to min_pass_rate =
0.9 (the table's own column default) rather than auto-passing -- a missing policy
must never silently mean "anything goes."

Section 15 refactor: the threshold comparison logic is now in the pure function
`_compute_gate_result()`, which unit tests call directly without needing a DB
connection. `evaluate()` is the DB-backed wrapper that resolves the run's policy
and delegates to it.

Phase 4 Section 1 adds two ARS-driven checks to `evaluate()`:
  - a min_ars threshold on THIS run's own ARS (same shape as the existing
    cost/latency thresholds, folded into the still-pure `_compute_gate_result()`)
  - an error-budget check across RECENT runs (ars_engine.evaluate_error_budget()) --
    this is deliberately NOT part of the pure function, because it is a statement
    about history, not about this run's own numbers. An exhausted budget forces a
    gate failure regardless of how well this particular run scored: that is the
    actual SRE mechanic (freeze deployments until reliability recovers), not a
    per-run vanity metric.
"""
from __future__ import annotations

import uuid

from pydantic import BaseModel

from apps.api.core.db import SessionLocal
from apps.api.models import ARSSnapshot, AgentVersion, EvalCaseResult, EvalRun, GatePolicy

DEFAULT_MIN_PASS_RATE = 0.9


class GateResult(BaseModel):
    passed: bool
    reasons: list[str]


def _compute_gate_result(
    passed_count: int,
    total: int,
    avg_cost_usd: float,
    avg_latency_ms: float,
    min_pass_rate: float,
    max_avg_cost_usd: float | None,
    max_avg_latency_ms: int | None,
    ars: float | None = None,
    min_ars: float | None = None,
) -> GateResult:
    """Pure threshold logic -- no DB, no I/O. Unit-testable in isolation.

    ars/min_ars default to None so every pre-Phase-4 call site (and every existing
    test) keeps working unchanged -- None on either side means "no ARS gate
    configured," identical in spirit to max_avg_cost_usd/max_avg_latency_ms already
    being optional.
    """
    if total == 0:
        return GateResult(passed=False, reasons=["no case results found for this run"])

    pass_rate = passed_count / total
    reasons: list[str] = []

    if pass_rate < min_pass_rate:
        reasons.append(
            f"pass_rate {pass_rate:.2f} is below required minimum {min_pass_rate:.2f}"
        )
    if max_avg_cost_usd is not None and avg_cost_usd > max_avg_cost_usd:
        reasons.append(
            f"avg_cost_usd ${avg_cost_usd:.6f} exceeds max ${max_avg_cost_usd}"
        )
    if max_avg_latency_ms is not None and avg_latency_ms > max_avg_latency_ms:
        reasons.append(
            f"avg_latency_ms {avg_latency_ms:.0f}ms exceeds max {max_avg_latency_ms}ms"
        )
    if min_ars is not None and ars is not None and ars < min_ars:
        reasons.append(
            f"ars {ars:.3f} is below required minimum {min_ars:.3f}"
        )

    return GateResult(passed=len(reasons) == 0, reasons=reasons)


def evaluate(eval_run_id: uuid.UUID) -> GateResult:
    db = SessionLocal()
    try:
        eval_run = db.get(EvalRun, eval_run_id)
        if eval_run is None:
            raise ValueError(f"eval_run {eval_run_id} not found")

        case_results = (
            db.query(EvalCaseResult).filter(EvalCaseResult.eval_run_id == eval_run.id).all()
        )
        if not case_results:
            return GateResult(passed=False, reasons=["no case results found for this run"])

        total = len(case_results)
        passed_count = sum(1 for r in case_results if r.passed)
        avg_cost_usd = sum(r.metrics.get("cost_usd", 0.0) for r in case_results) / total
        avg_latency_ms = sum(r.metrics.get("latency_ms", 0) for r in case_results) / total

        agent_version = db.get(AgentVersion, eval_run.agent_version_id)
        policy = (
            db.query(GatePolicy).filter(GatePolicy.agent_id == agent_version.agent_id).first()
        )

        min_pass_rate = policy.min_pass_rate if policy is not None else DEFAULT_MIN_PASS_RATE
        max_avg_cost_usd = policy.max_avg_cost_usd if policy is not None else None
        max_avg_latency_ms = policy.max_avg_latency_ms if policy is not None else None
        min_ars = policy.min_ars if policy is not None else None

        # Read-only lookup of the ARS already persisted at run completion
        # (eval_engine.run_eval() -> ars_engine.evaluate_ars()). Deliberately NOT
        # recomputed here: evaluate() can be called on every dashboard page load,
        # and a read path must not also be a write path. A run with no snapshot yet
        # (predates Phase 4, or ARS computation failed non-fatally) reports ars=None,
        # which _compute_gate_result treats as "no ARS gate for this run" -- the
        # same convention as every other optional threshold.
        ars_snapshot = (
            db.query(ARSSnapshot).filter(ARSSnapshot.eval_run_id == eval_run.id).first()
        )
        ars = ars_snapshot.ars if ars_snapshot is not None else None

        result = _compute_gate_result(
            passed_count=passed_count,
            total=total,
            avg_cost_usd=avg_cost_usd,
            avg_latency_ms=avg_latency_ms,
            min_pass_rate=min_pass_rate,
            max_avg_cost_usd=max_avg_cost_usd,
            max_avg_latency_ms=max_avg_latency_ms,
            ars=ars,
            min_ars=min_ars,
        )

        # Error-budget freeze: a statement about the recent past, not this run's own
        # numbers, so it cannot be folded into the pure function above. If the
        # agent's error budget is exhausted, this run fails the gate regardless of
        # its own score -- that is what distinguishes an error budget from a
        # per-run threshold (foundational doc §5.1's SRE borrowing).
        from apps.api.services.ars_engine import evaluate_error_budget
        budget = evaluate_error_budget(agent_version.agent_id)
        if budget.exhausted:
            result = GateResult(
                passed=False,
                reasons=[*result.reasons, f"error budget exhausted: {budget.detail}"],
            )

        return result
    finally:
        db.close()