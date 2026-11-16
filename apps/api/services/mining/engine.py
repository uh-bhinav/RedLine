"""
Production Failure Mining (Phase 4 Section 6 -- foundational doc §5.3).

"Continuously embed production traces, cluster them (unsupervised clustering on
embeddings), and flag clusters that correlate with bad outcomes... Each significant
cluster becomes a candidate regression test automatically. This is the actual
machine-learning component of the platform, not just LLM-as-judge scoring."

The honest scope: "production traces"
---------------------------------------
RedLine has no separate production-traffic ingestion pipeline yet -- every agent
interaction this platform has ever recorded is an EvalCaseResult from an eval run.
That IS the corpus. Mining looks across every eval run for an agent (every suite,
every version, not just one suite's cases), which is the closest honest proxy for
"production traffic" available today: real recorded interactions, not a synthetic
sample. A genuine production-traffic ingestion endpoint is future work (the
foundational doc's own scope is "continuously embed production traces," which
implies a live feed this phase does not build) -- this mines what already exists.

Why scikit-learn's DBSCAN, not a hand-rolled clustering routine
------------------------------------------------------------------
This is explicitly "the actual machine-learning component of the platform." Hand-
rolling a clustering algorithm for a feature whose entire point is being real
unsupervised ML would undercut the claim -- DBSCAN is a well-audited, standard
choice that naturally handles noise (points that don't belong to any cluster get
label -1, unlike k-means which forces every point into some cluster) and doesn't
require choosing a cluster count up front, which matters when you don't know in
advance how many distinct failure modes exist in the corpus.

"Bad outcome" definition
---------------------------
A case result's own `passed` field (every configured scorer's AND) -- the same
signal the gate engine already uses for pass_rate. Not a separate, narrower
definition (e.g. only SafetyScorer failures) -- any scorer failing is a legitimate
bad outcome worth mining for a pattern.

Split into pure clustering-significance logic (`_identify_significant_clusters`,
takes labels and outcomes already computed, no DB, no embeddings, unit-testable
with synthetic data) and a DB-backed orchestrator (`mine_failures`), the same
discipline as every other Phase 4 engine.
"""
from __future__ import annotations

import uuid
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime

import numpy as np
from sklearn.cluster import DBSCAN

from apps.api.core.db import SessionLocal
from apps.api.models import (
    Agent,
    AgentVersion,
    CandidateCase,
    EvalCase,
    EvalCaseResult,
    EvalRun,
    FailureCluster,
)
from apps.api.services.embeddings import embed_texts

# Cosine DISTANCE (1 - cosine similarity), not similarity -- DBSCAN's `eps` is a
# distance radius. 0.15 means "cluster together responses at cosine similarity
# >= 0.85." A STARTING default, not empirically calibrated (same honesty as
# diff_engine.DEFAULT_SIMILARITY_THRESHOLD) -- there is no labeled corpus of
# "genuinely the same failure mode" vs "coincidentally similar wording" yet to
# tune this against.
DEFAULT_DBSCAN_EPS = 0.15

# Also DBSCAN's min_samples: fewer than this many neighbors within eps and a
# point is noise (label -1), not a cluster. 3 is deliberately small -- a
# repeated failure mode showing up even 3 times across an agent's eval history
# is worth surfacing; requiring more would miss real but infrequent patterns.
DEFAULT_MIN_CLUSTER_SIZE = 3

# Of a cluster's members, what fraction must be bad outcomes before the cluster
# is flagged as a FAILURE cluster rather than just "a common, mostly-fine topic."
# 0.5 = a majority. Below this, clustering the SAME topic that mostly passes
# would falsely look like a failure pattern.
DEFAULT_MIN_BAD_OUTCOME_RATE = 0.5

NOISE_LABEL = -1


@dataclass
class ClusterSummary:
    cluster_label: int
    size: int
    bad_outcome_rate: float
    representative_index: int  # index into the original samples list
    detail: str


@dataclass
class MinedCluster:
    """Plain result type for mine_failures() -- deliberately NOT the FailureCluster
    ORM model. Every other Phase 4 engine (ars_engine, diff_engine, load_engine)
    returns a plain dataclass/Pydantic result, never a raw ORM instance, precisely
    to avoid handing the caller an object bound to a session that
    mine_failures()'s own `finally: db.close()` is about to invalidate. Returning
    FailureCluster directly here was a real bug caught by the integration test
    accessing a returned object's attributes after the function returned --
    DetachedInstanceError, not a passing assertion."""

    id: uuid.UUID
    cluster_label: int
    size: int
    bad_outcome_rate: float
    representative_text: str
    candidate_case_id: uuid.UUID
    created_at: datetime


class MiningError(RuntimeError):
    """Raised when mining cannot run -- e.g. not enough eval history yet."""


def _cluster_embeddings(
    embeddings: list[list[float]],
    eps: float = DEFAULT_DBSCAN_EPS,
    min_samples: int = DEFAULT_MIN_CLUSTER_SIZE,
) -> list[int]:
    """Thin DBSCAN wrapper over a precomputed cosine-distance matrix. Returns one
    label per input embedding, in the same order -- NOISE_LABEL (-1) for points
    DBSCAN could not assign to any cluster.

    Not a pure function in the strictest sense (it calls into sklearn/numpy), but
    it takes plain lists and returns plain labels -- no DB, no I/O, no embedding
    API call -- so it's fully unit-testable with small synthetic vectors.
    """
    if not embeddings:
        return []

    matrix = np.array(embeddings)
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    norms[norms == 0] = 1.0  # avoid division by zero for a degenerate zero vector
    normalized = matrix / norms
    similarity = normalized @ normalized.T
    distance = np.clip(1.0 - similarity, 0.0, 2.0)

    labels = DBSCAN(eps=eps, min_samples=min_samples, metric="precomputed").fit_predict(distance)
    return [int(label) for label in labels]


def _identify_significant_clusters(
    labels: list[int],
    bad_outcomes: list[bool],
    min_cluster_size: int = DEFAULT_MIN_CLUSTER_SIZE,
    min_bad_outcome_rate: float = DEFAULT_MIN_BAD_OUTCOME_RATE,
) -> list[ClusterSummary]:
    """Pure function -- no DB, no I/O, no embeddings. Takes cluster labels and a
    parallel list of "was this a bad outcome" booleans (both already computed),
    returns the clusters worth surfacing as candidate regression tests.

    A cluster qualifies if it meets BOTH thresholds: large enough to be a real
    recurring pattern (not two coincidentally similar responses), AND with enough
    bad outcomes that it looks like a failure mode, not just a common topic that
    mostly goes fine.
    """
    if len(labels) != len(bad_outcomes):
        raise ValueError(
            f"labels and bad_outcomes must be the same length, got "
            f"{len(labels)} and {len(bad_outcomes)}"
        )

    members_by_cluster: dict[int, list[int]] = defaultdict(list)
    for index, label in enumerate(labels):
        if label == NOISE_LABEL:
            continue
        members_by_cluster[label].append(index)

    summaries: list[ClusterSummary] = []
    for label, indices in sorted(members_by_cluster.items()):
        size = len(indices)
        if size < min_cluster_size:
            continue

        bad_count = sum(1 for i in indices if bad_outcomes[i])
        bad_rate = bad_count / size
        if bad_rate < min_bad_outcome_rate:
            continue

        # Prefer a bad-outcome member as the representative -- the candidate
        # case's whole purpose is testing the failure, not a passing example
        # that happened to land in the same cluster.
        bad_indices = [i for i in indices if bad_outcomes[i]]
        representative_index = bad_indices[0] if bad_indices else indices[0]

        summaries.append(ClusterSummary(
            cluster_label=label,
            size=size,
            bad_outcome_rate=bad_rate,
            representative_index=representative_index,
            detail=(
                f"cluster {label}: {size} members, {bad_count}/{size} "
                f"({bad_rate:.0%}) bad outcomes"
            ),
        ))

    return summaries


def _final_assistant_message(case_result: EvalCaseResult) -> str | None:
    assistant_turns = [t for t in case_result.transcript if t.get("role") == "assistant"]
    if not assistant_turns:
        return None
    return assistant_turns[-1].get("content", "")


def mine_failures(
    agent_id: uuid.UUID,
    eps: float = DEFAULT_DBSCAN_EPS,
    min_cluster_size: int = DEFAULT_MIN_CLUSTER_SIZE,
    min_bad_outcome_rate: float = DEFAULT_MIN_BAD_OUTCOME_RATE,
) -> list[MinedCluster]:
    """DB-backed orchestrator. Pulls every EvalCaseResult across every suite and
    version this agent has ever run, embeds each result's final assistant message,
    clusters via DBSCAN, identifies significant (large + failure-correlated)
    clusters via the pure function, and persists one FailureCluster + one
    CandidateCase per significant cluster.

    Always inserts new rows -- append-only, like drift_snapshots and
    behavior_diffs. Re-mining after more eval history accumulates is expected to
    happen repeatedly and each run is its own historical record.
    """
    db = SessionLocal()
    try:
        agent = db.get(Agent, agent_id)
        if agent is None:
            raise MiningError(f"agent {agent_id} not found")

        version_ids = [v.id for v in db.query(AgentVersion.id).filter(
            AgentVersion.agent_id == agent_id
        )]
        if not version_ids:
            raise MiningError(f"agent {agent_id} has no registered versions")

        run_ids = [r.id for r in db.query(EvalRun.id).filter(
            EvalRun.agent_version_id.in_(version_ids), EvalRun.status == "completed"
        )]
        if not run_ids:
            raise MiningError(
                f"agent {agent_id} has no completed eval runs yet -- nothing to mine"
            )

        case_results = (
            db.query(EvalCaseResult).filter(EvalCaseResult.eval_run_id.in_(run_ids)).all()
        )

        samples: list[EvalCaseResult] = []
        texts: list[str] = []
        for result in case_results:
            text = _final_assistant_message(result)
            if text:
                samples.append(result)
                texts.append(text)

        if len(samples) < min_cluster_size:
            raise MiningError(
                f"only {len(samples)} case result(s) with a real assistant response "
                f"across {len(run_ids)} completed run(s) -- need at least "
                f"{min_cluster_size} to find any cluster"
            )

        embeddings = embed_texts(texts)
        labels = _cluster_embeddings(embeddings, eps=eps, min_samples=min_cluster_size)
        bad_outcomes = [not r.passed for r in samples]

        clusters = _identify_significant_clusters(
            labels, bad_outcomes, min_cluster_size=min_cluster_size,
            min_bad_outcome_rate=min_bad_outcome_rate,
        )

        persisted: list[MinedCluster] = []
        for summary in clusters:
            representative = samples[summary.representative_index]
            representative_text = texts[summary.representative_index]

            failure_cluster = FailureCluster(
                agent_id=agent_id,
                cluster_label=summary.cluster_label,
                size=summary.size,
                bad_outcome_rate=summary.bad_outcome_rate,
                representative_case_result_id=representative.id,
                representative_text=representative_text,
            )
            db.add(failure_cluster)
            db.flush()

            representative_case = db.get(EvalCase, representative.case_id)
            candidate = CandidateCase(
                failure_cluster_id=failure_cluster.id,
                source_case_result_id=representative.id,
                case_key=f"mined_{failure_cluster.id.hex[:8]}",
                turns=representative_case.turns if representative_case else [],
                expectations={
                    "judge_rubric": (
                        f"This is a mined regression case representing a recurring "
                        f"failure pattern ({summary.size} similar cases, "
                        f"{summary.bad_outcome_rate:.0%} of them failed). The agent "
                        f"should NOT reproduce this response: {representative_text[:300]!r}"
                    ),
                },
                status="pending",
            )
            db.add(candidate)
            db.flush()

            # Captured as plain values, not the ORM instances, before the session
            # closes below -- see MinedCluster's docstring for why this matters.
            persisted.append(MinedCluster(
                id=failure_cluster.id,
                cluster_label=failure_cluster.cluster_label,
                size=failure_cluster.size,
                bad_outcome_rate=failure_cluster.bad_outcome_rate,
                representative_text=failure_cluster.representative_text,
                candidate_case_id=candidate.id,
                created_at=failure_cluster.created_at,
            ))

        db.commit()
        return persisted
    finally:
        db.close()
