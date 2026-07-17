"""
Drift detection runner (Phase 2 Section 9).

run_drift_check() is the DB-backed orchestrator:
  1. Finds all registered agent versions across all tenants
  2. For each: triggers a synchronous eval run against its reference suite
  3. Records a DriftSnapshot
  4. Calls detect_model_drift() on the recent snapshot history
  5. If drifted: writes a DriftAlert and emits a Prometheus metric

This runs in the drift_scheduler process, NOT in the API server and NOT in the
eval worker -- it is its own long-lived process with its own DB session lifecycle.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime

from prometheus_client import Counter, Gauge

from apps.api.core.db import SessionLocal
from apps.api.models import AgentVersion, EvalCaseResult, EvalRun, EvalSuite
from apps.api.models.drift import DriftAlert, DriftSnapshot
from apps.api.services.drift.detector import (
    BASELINE_WINDOW,
    DEFAULT_DRIFT_THRESHOLD,
    detect_model_drift,
)
from apps.api.services.eval_engine import run_eval

logger = logging.getLogger("redline.drift")

# Prometheus metrics for drift -- Grafana alerts on these
DRIFT_CHECK_RUNS_TOTAL = Counter(
    "redline_drift_check_runs_total",
    "Total scheduled drift check runs",
    ["status"],  # "ok" | "error"
)

DRIFT_SCORE_DELTA = Gauge(
    "redline_drift_score_delta",
    "Latest pass_rate delta from baseline (negative = regression)",
    ["agent_version_id", "suite_id"],
)

DRIFT_ALERTS_TOTAL = Counter(
    "redline_drift_alerts_total",
    "Total drift alerts raised",
    ["drift_type"],
)


def run_drift_check(threshold: float = DEFAULT_DRIFT_THRESHOLD) -> None:
    """
    Entry point called by the scheduler on every tick.
    Runs a drift check for every registered agent version.
    """
    db = SessionLocal()
    try:
        agent_versions = db.query(AgentVersion).all()
        if not agent_versions:
            logger.info("drift check: no agent versions registered, skipping")
            return

        logger.info(f"drift check: checking {len(agent_versions)} agent version(s)")

        for av in agent_versions:
            try:
                _check_one_version(db, av, threshold)
                DRIFT_CHECK_RUNS_TOTAL.labels(status="ok").inc()
            except Exception as exc:
                logger.error(f"drift check failed for agent_version={av.id}: {exc}")
                DRIFT_CHECK_RUNS_TOTAL.labels(status="error").inc()
    finally:
        db.close()


def _check_one_version(db, agent_version: AgentVersion, threshold: float) -> None:
    # Find the reference suite (baseline suite named "baseline" for this agent)
    suite = (
        db.query(EvalSuite)
        .filter(EvalSuite.agent_id == agent_version.agent_id, EvalSuite.name == "baseline")
        .first()
    )
    if suite is None:
        logger.info(f"  no 'baseline' suite for agent_version={agent_version.id}, skipping")
        return

    # Find the tenant from the agent
    from apps.api.models import Agent
    agent = db.get(Agent, agent_version.agent_id)
    if agent is None:
        return

    logger.info(
        f"  running drift check: agent={agent.name} "
        f"version={agent_version.version_label} suite={suite.name}"
    )

    # Trigger a fresh eval run synchronously
    eval_run = EvalRun(
        tenant_id=agent.tenant_id,
        agent_version_id=agent_version.id,
        suite_id=suite.id,
        status="pending",
        triggered_by="ci",  # drift checks are automated
    )
    db.add(eval_run)
    db.commit()
    db.refresh(eval_run)

    run_eval(eval_run.id)

    # Reload after run_eval updated it
    db.expire(eval_run)
    db.refresh(eval_run)

    if eval_run.status != "completed":
        logger.warning(f"  eval run {eval_run.id} did not complete (status={eval_run.status})")
        return

    # Compute pass rate from case results
    case_results = (
        db.query(EvalCaseResult)
        .filter(EvalCaseResult.eval_run_id == eval_run.id)
        .all()
    )
    if not case_results:
        return

    total = len(case_results)
    passed = sum(1 for r in case_results if r.passed)
    pass_rate = passed / total
    avg_cost = sum(r.metrics.get("cost_usd", 0.0) for r in case_results) / total
    avg_latency = sum(r.metrics.get("latency_ms", 0) for r in case_results) / total

    # Save snapshot
    snapshot = DriftSnapshot(
        agent_version_id=agent_version.id,
        suite_id=suite.id,
        eval_run_id=eval_run.id,
        pass_rate=pass_rate,
        total_cases=total,
        passed_cases=passed,
        avg_cost_usd=avg_cost,
        avg_latency_ms=avg_latency,
    )
    db.add(snapshot)
    db.commit()
    logger.info(f"  snapshot saved: pass_rate={pass_rate:.3f} ({passed}/{total})")

    # Pull recent snapshots for this version + suite (oldest first)
    recent_snapshots = (
        db.query(DriftSnapshot)
        .filter(
            DriftSnapshot.agent_version_id == agent_version.id,
            DriftSnapshot.suite_id == suite.id,
        )
        .order_by(DriftSnapshot.created_at.asc())
        .limit(BASELINE_WINDOW + 1)
        .all()
    )
    recent_rates = [s.pass_rate for s in recent_snapshots]

    result = detect_model_drift(recent_rates, threshold=threshold)

    # Update Prometheus gauge so Grafana can alert
    DRIFT_SCORE_DELTA.labels(
        agent_version_id=str(agent_version.id),
        suite_id=str(suite.id),
    ).set(result.delta)

    if result.drifted:
        alert = DriftAlert(
            agent_version_id=agent_version.id,
            suite_id=suite.id,
            drift_type="model",
            baseline_pass_rate=result.baseline_pass_rate,
            current_pass_rate=result.current_pass_rate,
            delta=result.delta,
            threshold=threshold,
            detail=result.detail,
        )
        db.add(alert)
        db.commit()
        DRIFT_ALERTS_TOTAL.labels(drift_type="model").inc()
        logger.warning(f"  DRIFT ALERT: {result.detail}")
    else:
        logger.info(f"  no drift: {result.detail}")