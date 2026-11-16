"""
Behavioural diff engine.

Compares what two agent versions *said* on the same suite (not what the code looks like):
per-case text similarity, then a four-way classification combining "did the code change?"
with "did behaviour change?":

    code same   + behaviour same    -> no_op
    code same   + behaviour changed -> silent_drift   (provider updated the model, say)
    code change + behaviour same    -> safe_refactor
    code change + behaviour changed -> expected_change
"""
from __future__ import annotations

import difflib
import re
import uuid
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from apps.api.core.db import SessionLocal
from apps.api.models import (
    AgentVersion,
    DiffCaseResult,
    DiffRun,
    DriftAlert,
    EvalCaseResult,
    EvalRun,
)
from apps.api.services import eval_engine

_TOKEN = re.compile(r"[a-z0-9]+")


def similarity(a: str, b: str) -> float:
    """Blend of token-set Jaccard and sequence ratio -- cheap, deterministic, no LLM call."""
    ta, tb = set(_TOKEN.findall(a.lower())), set(_TOKEN.findall(b.lower()))
    if not ta and not tb:
        return 1.0
    jaccard = len(ta & tb) / len(ta | tb)
    seq = difflib.SequenceMatcher(None, a.lower(), b.lower()).ratio()
    return round(0.5 * jaccard + 0.5 * seq, 4)


def classify(code_changed: bool, behaviour_changed: bool) -> str:
    if code_changed:
        return "expected_change" if behaviour_changed else "safe_refactor"
    return "silent_drift" if behaviour_changed else "no_op"


def _assistant_text(transcript: list[dict]) -> str:
    return " ".join(t["content"] for t in transcript if t.get("role") == "assistant")


def latest_completed_run(db: Session, version_id: uuid.UUID, suite_id: uuid.UUID) -> EvalRun | None:
    return (
        db.query(EvalRun)
        .filter(
            EvalRun.agent_version_id == version_id,
            EvalRun.suite_id == suite_id,
            EvalRun.status == "completed",
        )
        .order_by(EvalRun.created_at.desc())
        .first()
    )


def _fresh_run(db: Session, template: EvalRun, version_id: uuid.UUID) -> EvalRun:
    run = EvalRun(
        tenant_id=template.tenant_id,
        agent_version_id=version_id,
        suite_id=template.suite_id,
        status="pending",
        triggered_by="manual",
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    eval_engine.run_eval(run.id)
    db.expire_all()
    return db.get(EvalRun, run.id)


def run_diff(diff_run_id: uuid.UUID) -> None:
    """Worker entrypoint. run_a/run_b were chosen at creation time; any that are still
    pending (no prior completed run) are executed inline before comparing."""
    db: Session = SessionLocal()
    try:
        diff = db.get(DiffRun, diff_run_id)
        if diff is None:
            raise ValueError(f"diff_run {diff_run_id} not found")
        diff.status = "running"
        db.commit()

        run_a, run_b = db.get(EvalRun, diff.run_a_id), db.get(EvalRun, diff.run_b_id)
        for run in (run_a, run_b):
            if run.status == "pending":
                eval_engine.run_eval(run.id)
        db.expire_all()
        run_a, run_b = db.get(EvalRun, diff.run_a_id), db.get(EvalRun, diff.run_b_id)

        res_a = {r.case_id: r for r in db.query(EvalCaseResult).filter_by(eval_run_id=run_a.id)}
        res_b = {r.case_id: r for r in db.query(EvalCaseResult).filter_by(eval_run_id=run_b.id)}
        sims: list[float] = []
        for case_id in res_a.keys() & res_b.keys():
            out_a, out_b = _assistant_text(res_a[case_id].transcript), _assistant_text(res_b[case_id].transcript)
            sim = similarity(out_a, out_b)
            sims.append(sim)
            db.add(
                DiffCaseResult(
                    diff_run_id=diff.id,
                    case_id=case_id,
                    similarity=sim,
                    output_a=out_a,
                    output_b=out_b,
                    passed_a=res_a[case_id].passed,
                    passed_b=res_b[case_id].passed,
                )
            )

        ver_a, ver_b = db.get(AgentVersion, run_a.agent_version_id), db.get(AgentVersion, run_b.agent_version_id)
        mean_sim = round(sum(sims) / len(sims), 4) if sims else 1.0
        diff.code_changed = ver_a.content_hash != ver_b.content_hash
        diff.mean_similarity = mean_sim
        diff.classification = classify(diff.code_changed, mean_sim < diff.threshold)
        diff.status = "completed"
        diff.completed_at = datetime.now(timezone.utc)

        if diff.classification == "silent_drift":
            db.add(
                DriftAlert(
                    agent_id=diff.agent_id,
                    drift_type="model",
                    metric="similarity",
                    baseline_value=diff.threshold,
                    current_value=mean_sim,
                    message="Identical code hash but outputs diverged -- likely a silent model update.",
                    eval_run_id=run_b.id,
                    diff_run_id=diff.id,
                )
            )
        db.commit()
    except Exception:
        db.rollback()
        failed = db.get(DiffRun, diff_run_id)
        if failed is not None:
            failed.status = "failed"
            db.commit()
        raise
    finally:
        db.close()
