"""
Gate Engine (Phase1 roadmap Section 11).

evaluate(eval_run_id) -> GateResult. Computes pass_rate, avg_cost_usd, avg_latency_ms
across all EvalCaseResult rows for the run, compares each against the agent's
GatePolicy, and collects a human-readable reason string for every violated threshold.

A run with zero configured GatePolicy rows for its agent defaults to min_pass_rate =
0.9 (the table's own column default) rather than auto-passing -- a missing policy
must never silently mean "anything goes."
"""
from __future__ import annotations

import uuid

from pydantic import BaseModel

from apps.api.core.db import SessionLocal
from apps.api.models import AgentVersion, EvalCaseResult, EvalRun, GatePolicy

DEFAULT_MIN_PASS_RATE = 0.9


class GateResult(BaseModel):
    passed: bool
    reasons: list[str]


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
        pass_rate = passed_count / total
        avg_cost_usd = sum(r.metrics.get("cost_usd", 0.0) for r in case_results) / total
        avg_latency_ms = sum(r.metrics.get("latency_ms", 0) for r in case_results) / total

        agent_version = db.get(AgentVersion, eval_run.agent_version_id)
        policy = (
            db.query(GatePolicy).filter(GatePolicy.agent_id == agent_version.agent_id).first()
        )

        min_pass_rate = policy.min_pass_rate if policy is not None else DEFAULT_MIN_PASS_RATE
        max_avg_cost_usd = policy.max_avg_cost_usd if policy is not None else None
        max_avg_latency_ms = policy.max_avg_latency_ms if policy is not None else None

        reasons: list[str] = []
        if pass_rate < min_pass_rate:
            reasons.append(f"pass_rate {pass_rate:.2f} is below required minimum {min_pass_rate:.2f}")
        if max_avg_cost_usd is not None and avg_cost_usd > max_avg_cost_usd:
            reasons.append(f"avg_cost_usd ${avg_cost_usd:.6f} exceeds max ${max_avg_cost_usd}")
        if max_avg_latency_ms is not None and avg_latency_ms > max_avg_latency_ms:
            reasons.append(f"avg_latency_ms {avg_latency_ms:.0f}ms exceeds max {max_avg_latency_ms}ms")

        return GateResult(passed=len(reasons) == 0, reasons=reasons)
    finally:
        db.close()