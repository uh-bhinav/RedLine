"""
Eval Engine (Phase1 roadmap Section 10).

Exposes one entrypoint: run_eval(eval_run_id). Orchestrates a full session-based
eval run: loads the run + its agent version + suite cases, drives the agent through
each case's scripted turns via the AgentAdapter contract (this loop is *why* the
session-shaped data model matters -- a single-response model has no place to put
this loop), scores the result, writes an EvalCaseResult row per case, then hands
off to the Gate Engine once every case is done.
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy.orm import Session

from apps.api.core.db import SessionLocal
from apps.api.models import AgentVersion, EvalCase, EvalCaseResult, EvalRun
from apps.api.services.adapters.local_python import LocalPythonAdapter
from apps.api.services.scorers.base import Turn
from apps.api.services.scorers.contains_match import ContainsMatchScorer
from apps.api.services.scorers.cost import CostScorer
from apps.api.services.scorers.latency import LatencyScorer
from apps.api.services.scorers.llm_judge import LLMJudgeScorer

# Deterministic scorers run before the LLM judge -- every avoided judge call is
# real money and real latency saved (roadmap Section 9).
_SCORERS = [ContainsMatchScorer(), CostScorer(), LatencyScorer(), LLMJudgeScorer()]


def _run_case(adapter: LocalPythonAdapter, case: EvalCase) -> tuple[list[Turn], bool, dict]:
    """Drives one case through its scripted turns. Fresh session_state per case --
    each case is an independent conversation, never sharing state with another."""
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

        eval_run.status = "running"
        eval_run.started_at = datetime.utcnow()
        db.commit()

        adapter = LocalPythonAdapter(agent_version.entrypoint)

        for case in cases:
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

        eval_run.status = "completed"
        eval_run.completed_at = datetime.utcnow()
        db.commit()
        # Gate verdict is intentionally not computed here -- GET /eval-runs/{id}
        # computes it fresh on every read (gate_engine.evaluate() is cheap and
        # pure), and the CLI's ci-check command is what actually reports it back
        # to GitHub. Nothing in this function needs to know GitHub exists.

    except Exception:
        db.rollback()
        failed_run = db.get(EvalRun, eval_run_id)
        if failed_run is not None:
            failed_run.status = "failed"
            db.commit()
        raise
    finally:
        db.close()