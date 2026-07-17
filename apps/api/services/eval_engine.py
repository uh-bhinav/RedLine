"""
Eval Engine (Phase1 roadmap Section 10, Phase 2 Section 4 trace instrumentation).

Phase 2 adds non-fatal ClickHouse trace emission at three points in the run
lifecycle: run_started, turn_completed (per case), and run_completed. These are
fire-and-forget -- a ClickHouse write failure never affects the eval result or
the Postgres state. The eval logic itself is unchanged.
Eval Engine (Phase 2 Section 8 -- adds telemetry instrumentation).

Changes from Phase 2 Section 4:
  - Emits Prometheus metrics at run completion (EVAL_RUNS_TOTAL, EVAL_RUN_DURATION_SECONDS,
    EVAL_CASE_RESULTS_TOTAL, EVAL_CASE_COST_USD)
  - Wraps the full run in an OTel span for distributed tracing
  - ClickHouse trace emission unchanged
"""

from __future__ import annotations

import time
import uuid
from datetime import datetime

from sqlalchemy.orm import Session

from apps.api.core.clickhouse_client import emit_trace
from apps.api.core.db import SessionLocal
from apps.api.core.telemetry import (
    EVAL_CASE_COST_USD,
    EVAL_CASE_RESULTS_TOTAL,
    EVAL_RUN_DURATION_SECONDS,
    EVAL_RUNS_TOTAL,
    tracer,
)
from apps.api.models import AgentVersion, EvalCase, EvalCaseResult, EvalRun
from apps.api.services.adapters.local_python import LocalPythonAdapter
from apps.api.services.scorers.base import Turn
from apps.api.services.scorers.contains_match import ContainsMatchScorer
from apps.api.services.scorers.cost import CostScorer
from apps.api.services.scorers.latency import LatencyScorer
from apps.api.services.scorers.llm_judge import LLMJudgeScorer

_SCORERS = [ContainsMatchScorer(), CostScorer(), LatencyScorer(), LLMJudgeScorer()]


def _run_case(adapter: LocalPythonAdapter, case: EvalCase) -> tuple[list[Turn], bool, dict]:
    session_state: dict = {}
    transcript: list[Turn] = []

    for scripted_turn in case.turns:
        transcript.append(Turn(role=scripted_turn["role"], content=scripted_turn["content"]))
        result = adapter.run_turn(session_state, scripted_turn["content"])
        transcript.append(
            Turn(
                role="assistant",
                content=result.assistant_message,
                tool_calls=[tc.model_dump() for tc in result.tool_calls],
                latency_ms=result.latency_ms,
                cost_usd=result.cost_usd,
            )
        )

    scorer_results: dict = {}
    overall_passed = True
    for scorer in _SCORERS:
        scorer_result = scorer.score(case, transcript)
        scorer_results[type(scorer).__name__] = scorer_result.model_dump()
        if not scorer_result.passed:
            overall_passed = False

    return transcript, overall_passed, scorer_results


def _compute_metrics(transcript: list[Turn]) -> dict:
    return {
        "cost_usd": sum(t.cost_usd or 0.0 for t in transcript if t.role == "assistant"),
        "latency_ms": sum(t.latency_ms or 0 for t in transcript if t.role == "assistant"),
    }


def run_eval(eval_run_id: uuid.UUID) -> None:
    with tracer.start_as_current_span(
        "eval_run",
        attributes={"eval_run_id": str(eval_run_id)},
    ) as span:
        run_start = time.perf_counter()
        db: Session = SessionLocal()
        try:
            eval_run = db.get(EvalRun, eval_run_id)
            if eval_run is None:
                raise ValueError(f"eval_run {eval_run_id} not found")

            agent_version = db.get(AgentVersion, eval_run.agent_version_id)
            if agent_version is None:
                raise ValueError(f"agent_version {eval_run.agent_version_id} not found")

            cases = db.query(EvalCase).filter(EvalCase.suite_id == eval_run.suite_id).all()
            if not cases:
                raise ValueError(f"suite {eval_run.suite_id} has no cases")

            span.set_attribute("case_count", len(cases))
            span.set_attribute("agent_version", agent_version.version_label)

            eval_run.status = "running"
            eval_run.started_at = datetime.utcnow()
            db.commit()

            emit_trace(
                eval_run_id=eval_run.id,
                tenant_id=eval_run.tenant_id,
                event_type="run_started",
                detail=f"suite_id={eval_run.suite_id}",
            )

            adapter = LocalPythonAdapter(agent_version.entrypoint)

            for i, case in enumerate(cases):
                with tracer.start_as_current_span(
                    "eval_case",
                    attributes={"case_key": case.case_key, "case_index": i},
                ):
                    transcript, overall_passed, scorer_results = _run_case(adapter, case)
                    metrics = _compute_metrics(transcript)

                    case_result = EvalCaseResult(
                        eval_run_id=eval_run.id,
                        case_id=case.id,
                        passed=overall_passed,
                        metrics=metrics,
                        transcript=[t.model_dump() for t in transcript],
                        scorer_results=scorer_results,
                    )
                    db.add(case_result)
                    db.commit()

                    # Prometheus metrics
                    EVAL_CASE_RESULTS_TOTAL.labels(passed=str(overall_passed).lower()).inc()
                    EVAL_CASE_COST_USD.observe(metrics["cost_usd"])

                    emit_trace(
                        eval_run_id=eval_run.id,
                        tenant_id=eval_run.tenant_id,
                        event_type="turn_completed",
                        case_key=case.case_key,
                        turn_index=i,
                        latency_ms=metrics["latency_ms"],
                        cost_usd=metrics["cost_usd"],
                        passed=overall_passed,
                        detail=str({k: v["passed"] for k, v in scorer_results.items()}),
                    )

            eval_run.status = "completed"
            eval_run.completed_at = datetime.utcnow()
            db.commit()

            duration = time.perf_counter() - run_start
            EVAL_RUNS_TOTAL.labels(status="completed").inc()
            EVAL_RUN_DURATION_SECONDS.observe(duration)

            emit_trace(
                eval_run_id=eval_run.id,
                tenant_id=eval_run.tenant_id,
                event_type="run_completed",
                detail="status=completed",
            )

        except Exception:
            db.rollback()
            failed_run = db.get(EvalRun, eval_run_id)
            if failed_run is not None:
                failed_run.status = "failed"
                db.commit()
            EVAL_RUNS_TOTAL.labels(status="failed").inc()
            span.record_exception(Exception())
            emit_trace(
                eval_run_id=eval_run_id,
                tenant_id=uuid.uuid4(),
                event_type="run_completed",
                detail="status=failed",
            )
            raise
        finally:
            db.close()