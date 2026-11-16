"""
Failure mining. Collects the first user prompt of every case an agent has ever been
scored on, TF-IDF vectorises them, and clusters with DBSCAN (cosine distance) so recurring
failure patterns surface as clusters. Each cluster stores its share of "bad outcomes"
and proposes its most representative prompt as a CandidateCase for human review.
"""
from __future__ import annotations

import re
import uuid
from collections import defaultdict

import numpy as np
from sklearn.cluster import DBSCAN
from sklearn.feature_extraction.text import ENGLISH_STOP_WORDS, TfidfVectorizer
from sqlalchemy.orm import Session

from apps.api.models import (
    AgentVersion,
    CandidateCase,
    EvalCaseResult,
    EvalRun,
    FailureCluster,
)


def _first_user_prompt(transcript: list[dict]) -> str:
    for turn in transcript:
        if turn.get("role") == "user":
            return turn["content"]
    return ""


def mine(db: Session, agent_id: uuid.UUID) -> list[FailureCluster]:
    rows = (
        db.query(EvalCaseResult)
        .join(EvalRun, EvalRun.id == EvalCaseResult.eval_run_id)
        .join(AgentVersion, AgentVersion.id == EvalRun.agent_version_id)
        .filter(AgentVersion.agent_id == agent_id)
        .all()
    )
    outcomes: dict[str, list[bool]] = defaultdict(list)
    for r in rows:
        prompt = _first_user_prompt(r.transcript)
        if prompt:
            outcomes[prompt].append(r.passed)

    failing = [p for p, o in outcomes.items() if not all(o)]

    # Re-mining replaces previous results (but keeps candidates already reviewed).
    db.query(CandidateCase).filter(
        CandidateCase.agent_id == agent_id, CandidateCase.status == "pending"
    ).delete()
    # Reviewed (approved/rejected) candidates are kept, but must not block deleting their
    # cluster through the foreign key -- detach them first.
    db.query(CandidateCase).filter(
        CandidateCase.agent_id == agent_id, CandidateCase.status != "pending"
    ).update({CandidateCase.cluster_id: None}, synchronize_session=False)
    db.query(FailureCluster).filter(FailureCluster.agent_id == agent_id).delete()
    db.commit()
    if not failing:
        return []

    if len(failing) == 1:
        groups = {0: [0]}
        vec = None
        matrix = None
    else:
        vec = TfidfVectorizer(stop_words="english", ngram_range=(1, 2))
        matrix = vec.fit_transform(failing)
        labels = DBSCAN(eps=0.85, min_samples=2, metric="cosine").fit_predict(matrix)
        groups: dict[int, list[int]] = defaultdict(list)
        for idx, label in enumerate(labels):
            groups[int(label)].append(idx)
        noise = groups.pop(-1, [])
        if noise:  # unclustered failures still matter -- keep them as one catch-all group
            groups[max(groups, default=-1) + 1] = noise

    clusters: list[FailureCluster] = []
    for cluster_index, member_idx in sorted(groups.items()):
        prompts = [failing[i] for i in member_idx]
        if matrix is not None and len(member_idx) > 1:
            sub = matrix[member_idx]
            centroid = np.asarray(sub.mean(axis=0))
            sims = np.asarray(sub @ centroid.T).ravel()
            representative = prompts[int(sims.argmax())]
            weights = np.asarray(sub.sum(axis=0)).ravel()
            terms = [
                vec.get_feature_names_out()[i]
                for i in weights.argsort()[::-1]
                if " " not in vec.get_feature_names_out()[i]
            ][:3]
        else:
            representative = prompts[0]
            terms = [w for w in re.findall(r"[a-z]+", prompts[0].lower()) if w not in ENGLISH_STOP_WORDS][:3]

        results = [o for p in prompts for o in outcomes[p]]
        bad_rate = round(results.count(False) / len(results), 3)
        cluster = FailureCluster(
            agent_id=agent_id,
            cluster_index=cluster_index,
            label=f"Questions about {', '.join(terms) if terms else 'recurring failures'}",
            representative=representative,
            case_count=len(prompts),
            bad_outcome_rate=bad_rate,
        )
        db.add(cluster)
        db.flush()
        clusters.append(cluster)
        db.add(
            CandidateCase(
                agent_id=agent_id,
                cluster_id=cluster.id,
                case_key=f"mined_{cluster_index:02d}_{re.sub(r'[^a-z0-9]+', '_', representative.lower())[:32].strip('_')}",
                prompt=representative,
            )
        )
    db.commit()
    return clusters
