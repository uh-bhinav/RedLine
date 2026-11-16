"""
Behavioral Diff Engine (Phase 4 Section 2 -- foundational doc §5.2).

`git diff` shows you code changed. It tells you nothing about whether the agent's
behavior changed. A prompt edit that looks like one word can flip "refund: approved"
to "refund: denied" -- and, the more interesting direction, a model provider can
silently upgrade the model underneath an agent that has ZERO code changes, and
nothing in a code review would ever catch that.

How it works: take the two most recent COMPLETED eval runs of two agent versions
against the SAME suite (no new eval is triggered here -- if a version hasn't been
run against the suite, run it first via `agentbench run`, then diff). For every
case_key present in both runs, embed the final assistant message from each and
compute cosine similarity. The mean similarity across cases, plus whether the two
versions' `content_hash` differ, places the comparison into one of four quadrants:

                          code same              code changed
    behavior same      NO_OP (nothing to see)   SAFE_REFACTOR (code moved, output didn't)
    behavior changed    SILENT_DRIFT (the alarm) EXPECTED_CHANGE (you meant to do this)

SILENT_DRIFT is the case the foundational document calls out specifically: "catching
cases where code changed but behavior is identical (safe) vs. code didn't change but
behavior drifted (e.g., underlying model was silently upgraded)."

Split into a pure classifier (`_classify_diff`, no DB, no I/O, unit-testable with
plain dicts) and a DB-backed orchestrator (`compute_diff`), the same discipline as
gate_engine and ars_engine.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from enum import Enum

import numpy as np

from apps.api.core.db import SessionLocal
from apps.api.models import AgentVersion, BehaviorDiff, EvalCase, EvalCaseResult, EvalRun
from apps.api.services.embeddings import embed_texts

# Similarity below this counts as "behavior changed." This is a STARTING default, not
# an empirically calibrated constant (unlike DEFAULT_DRIFT_THRESHOLD in
# drift/detector.py, which had real pass-rate history to calibrate against at the
# time it was written). There is no corpus of "known-safe paraphrase" vs
# "known-different answer" version pairs yet to tune this against. Revisit once
# agentbench diff has real version-pair history to learn from.
DEFAULT_SIMILARITY_THRESHOLD = 0.90


class DiffClassification(str, Enum):
    NO_OP = "no_op"
    SAFE_REFACTOR = "safe_refactor"
    EXPECTED_CHANGE = "expected_change"
    SILENT_DRIFT = "silent_drift"
    INSUFFICIENT_DATA = "insufficient_data"


@dataclass
class BehaviorDiffResult:
    classification: DiffClassification
    code_changed: bool
    behavior_changed: bool
    mean_similarity: float
    threshold: float
    per_case_similarity: dict[str, float]
    detail: str
    # Optional, defaulted -- _classify_diff() (the pure classifier, no DB
    # access) never sets these, matching its existing 7-arg construction
    # unchanged. Only compute_diff() (the DB-backed orchestrator) populates
    # them after persisting, so a caller with the DB-backed result can link
    # back to the created row and the two runs compared -- Phase 5.3's
    # dashboard diff viewer needs this to fetch both runs' transcripts.
    id: uuid.UUID | None = None
    eval_run_a_id: uuid.UUID | None = None
    eval_run_b_id: uuid.UUID | None = None


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """Deliberately re-implemented here rather than imported from agents/rag_agent --
    agents/ are fixtures under test, not library code the platform depends on. The
    platform and the agents it evaluates must not share code that a test suite
    change could accidentally couple."""
    a_arr, b_arr = np.array(a), np.array(b)
    denom = np.linalg.norm(a_arr) * np.linalg.norm(b_arr)
    if denom == 0:
        return 0.0
    return float(np.dot(a_arr, b_arr) / denom)


def _classify_diff(
    code_changed: bool,
    per_case_similarity: dict[str, float],
    similarity_threshold: float = DEFAULT_SIMILARITY_THRESHOLD,
) -> BehaviorDiffResult:
    """Pure function -- no DB, no I/O, no embedding calls. Takes similarities already
    computed and classifies. Unit-testable with a plain dict."""
    if not per_case_similarity:
        return BehaviorDiffResult(
            classification=DiffClassification.INSUFFICIENT_DATA,
            code_changed=code_changed, behavior_changed=False,
            mean_similarity=0.0, threshold=similarity_threshold,
            per_case_similarity={},
            detail="no case_key is present in both runs -- nothing to compare "
                    "(did the suite change between versions?)",
        )

    mean_similarity = sum(per_case_similarity.values()) / len(per_case_similarity)
    behavior_changed = mean_similarity < similarity_threshold

    if code_changed and not behavior_changed:
        classification = DiffClassification.SAFE_REFACTOR
        headline = "code changed, behavior did not -- safe"
    elif code_changed and behavior_changed:
        classification = DiffClassification.EXPECTED_CHANGE
        headline = "code changed and behavior changed -- expected, review the diff"
    elif not code_changed and behavior_changed:
        classification = DiffClassification.SILENT_DRIFT
        headline = "code UNCHANGED but behavior changed -- likely a silent model/provider update"
    else:
        classification = DiffClassification.NO_OP
        headline = "code unchanged, behavior unchanged"

    detail = (
        f"{headline}. mean_similarity={mean_similarity:.3f} "
        f"(threshold={similarity_threshold:.2f}) across {len(per_case_similarity)} case(s)"
    )
    return BehaviorDiffResult(
        classification=classification, code_changed=code_changed,
        behavior_changed=behavior_changed, mean_similarity=mean_similarity,
        threshold=similarity_threshold, per_case_similarity=per_case_similarity,
        detail=detail,
    )


def _latest_completed_run(db, agent_version_id: uuid.UUID, suite_id: uuid.UUID) -> EvalRun | None:
    return (
        db.query(EvalRun)
        .filter(
            EvalRun.agent_version_id == agent_version_id,
            EvalRun.suite_id == suite_id,
            EvalRun.status == "completed",
        )
        .order_by(EvalRun.created_at.desc())
        .first()
    )


def _final_assistant_messages(db, eval_run_id: uuid.UUID) -> dict[str, str]:
    """{case_key: final assistant turn's content} for every case result in a run."""
    results = db.query(EvalCaseResult).filter(EvalCaseResult.eval_run_id == eval_run_id).all()
    out: dict[str, str] = {}
    for r in results:
        case = db.get(EvalCase, r.case_id)
        if case is None:
            continue
        assistant_turns = [t for t in r.transcript if t.get("role") == "assistant"]
        if not assistant_turns:
            continue
        out[case.case_key] = assistant_turns[-1].get("content", "")
    return out


class DiffEngineError(RuntimeError):
    """Raised when a diff cannot be computed -- e.g. one of the versions has no
    completed eval run against the requested suite yet."""


def compute_diff(
    eval_run_a_id: uuid.UUID,
    eval_run_b_id: uuid.UUID,
    similarity_threshold: float = DEFAULT_SIMILARITY_THRESHOLD,
) -> BehaviorDiffResult:
    """DB-backed orchestrator, and the one real primitive underneath both
    convenience wrappers below.

    Takes two EVAL RUN ids directly, not version ids. This matters:
    `agent_versions` has a UNIQUE(agent_id, content_hash) constraint, so two
    DIFFERENT AgentVersion rows for the same agent are guaranteed to have
    DIFFERENT content_hash. If this function took two version ids and always
    resolved "the latest run," `code_changed` would be True on every single call
    that compares distinct versions -- making SILENT_DRIFT and NO_OP structurally
    unreachable, not just rare. Taking run ids directly is what lets the SAME
    version be compared against itself across two different points in time (two
    different completed runs, same content_hash) -- which is the only way
    "code did not change" can be represented at all in this schema, and is
    exactly what a real silent-drift event looks like: nobody touched the code,
    the provider changed the model underneath it.

    Embeds the shared cases' final assistant messages, classifies via the pure
    function, and persists a BehaviorDiff row (always inserted, never upserted --
    see the model's docstring for why). Both runs must target the same suite;
    diffing across different suites would compare answers to different questions.
    """
    db = SessionLocal()
    try:
        run_a = db.get(EvalRun, eval_run_a_id)
        run_b = db.get(EvalRun, eval_run_b_id)
        if run_a is None or run_b is None:
            raise DiffEngineError("one or both eval runs were not found")
        if run_a.suite_id != run_b.suite_id:
            raise DiffEngineError(
                "cannot diff eval runs against different suites -- they would be "
                "answers to different questions, not a behavior comparison"
            )
        if run_a.status != "completed" or run_b.status != "completed":
            raise DiffEngineError("both eval runs must be completed before diffing")

        version_a = db.get(AgentVersion, run_a.agent_version_id)
        version_b = db.get(AgentVersion, run_b.agent_version_id)
        if version_a is None or version_b is None:
            raise DiffEngineError("one or both agent versions were not found")
        if version_a.agent_id != version_b.agent_id:
            raise DiffEngineError("cannot diff versions belonging to different agents")

        responses_a = _final_assistant_messages(db, run_a.id)
        responses_b = _final_assistant_messages(db, run_b.id)
        shared_keys = sorted(set(responses_a) & set(responses_b))

        code_changed = version_a.content_hash != version_b.content_hash

        if not shared_keys:
            result = _classify_diff(code_changed, {}, similarity_threshold)
        else:
            texts_a = [responses_a[k] for k in shared_keys]
            texts_b = [responses_b[k] for k in shared_keys]
            embeddings_a = embed_texts(texts_a)
            embeddings_b = embed_texts(texts_b)
            per_case_similarity = {
                k: _cosine_similarity(ea, eb)
                for k, ea, eb in zip(shared_keys, embeddings_a, embeddings_b)
            }
            result = _classify_diff(code_changed, per_case_similarity, similarity_threshold)

        behavior_diff = BehaviorDiff(
            agent_id=version_a.agent_id,
            version_a_id=version_a.id,
            version_b_id=version_b.id,
            suite_id=run_a.suite_id,
            eval_run_a_id=run_a.id,
            eval_run_b_id=run_b.id,
            code_changed=result.code_changed,
            behavior_changed=result.behavior_changed,
            mean_similarity=result.mean_similarity,
            similarity_threshold=result.threshold,
            classification=result.classification.value,
            per_case_similarity=result.per_case_similarity,
            detail=result.detail,
        )
        db.add(behavior_diff)
        db.commit()
        db.refresh(behavior_diff)

        result.id = behavior_diff.id
        result.eval_run_a_id = run_a.id
        result.eval_run_b_id = run_b.id

        return result
    finally:
        db.close()


def compute_diff_for_versions(
    version_a_id: uuid.UUID,
    version_b_id: uuid.UUID,
    suite_id: uuid.UUID,
    similarity_threshold: float = DEFAULT_SIMILARITY_THRESHOLD,
) -> BehaviorDiffResult:
    """Convenience wrapper for the `agentbench diff <version-a> <version-b>` /
    `POST /diff-runs` interface: resolves each version's most recent completed run
    against `suite_id` and delegates to compute_diff().

    Because these are two DIFFERENT registered versions, code_changed is always
    True here (the unique constraint guarantees it) -- the only reachable
    classifications through this path are SAFE_REFACTOR and EXPECTED_CHANGE. That
    is correct, not a bug: comparing two distinct versions answers "was this
    version bump safe," which is a different question from "did this version's
    behavior drift over time" (compute_diff_over_time, below).
    """
    db = SessionLocal()
    try:
        version_a = db.get(AgentVersion, version_a_id)
        version_b = db.get(AgentVersion, version_b_id)
        if version_a is None or version_b is None:
            raise DiffEngineError("one or both agent versions were not found")

        run_a = _latest_completed_run(db, version_a_id, suite_id)
        run_b = _latest_completed_run(db, version_b_id, suite_id)
        if run_a is None or run_b is None:
            missing = version_a.version_label if run_a is None else version_b.version_label
            raise DiffEngineError(
                f"version '{missing}' has no completed eval run against this suite yet -- "
                f"run `agentbench run` for it first, then diff"
            )
    finally:
        db.close()

    return compute_diff(run_a.id, run_b.id, similarity_threshold)


def compute_diff_over_time(
    agent_version_id: uuid.UUID,
    suite_id: uuid.UUID,
    similarity_threshold: float = DEFAULT_SIMILARITY_THRESHOLD,
) -> BehaviorDiffResult:
    """The genuine silent-drift check: compares the SAME agent version's two most
    recent completed runs against the same suite. Same version -> same
    content_hash -> code_changed is always False here, so the only reachable
    classifications are NO_OP (nothing changed, the common case) and SILENT_DRIFT
    (the alarm -- called by drift/runner.py on a schedule).
    """
    db = SessionLocal()
    try:
        recent_runs = (
            db.query(EvalRun)
            .filter(
                EvalRun.agent_version_id == agent_version_id,
                EvalRun.suite_id == suite_id,
                EvalRun.status == "completed",
            )
            .order_by(EvalRun.created_at.desc())
            .limit(2)
            .all()
        )
        if len(recent_runs) < 2:
            raise DiffEngineError(
                "need at least 2 completed eval runs of this version against this "
                "suite to detect drift over time -- only found "
                f"{len(recent_runs)}"
            )
        newer_run, older_run = recent_runs[0], recent_runs[1]
    finally:
        db.close()

    return compute_diff(older_run.id, newer_run.id, similarity_threshold)
