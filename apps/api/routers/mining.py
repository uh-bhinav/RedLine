"""
Production Failure Mining endpoints (Phase 4 Section 6).

Owned by eval_service, same reasoning as /diff-runs and /load-runs: this reads
eval history and calls an embedding model, which is eval-logic territory.

POST /mining/{agent_id}/run computes synchronously -- embedding a batch of past
transcripts plus DBSCAN is fast (seconds, not minutes), same shape as /diff-runs.

Approving a candidate is a genuinely separate, deliberate action from mining
itself (the docstring in models/mining.py is explicit about this): a mined
candidate is a suggestion, never auto-trusted into the real suite.
"""
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from apps.api.core.db import get_db
from apps.api.core.security import TenantContext, get_tenant_context, require_tenant_role
from apps.api.models import (
    Agent,
    CandidateCase,
    EvalCase,
    EvalSuite,
    FailureCluster,
)
from apps.api.schemas.mining import CandidateCaseResponse, FailureClusterResponse
from apps.api.services.mining import MinedCluster, MiningError, mine_failures

router = APIRouter(prefix="/mining", tags=["mining"])

MINED_SUITE_NAME = "mined-failures"


def _owned_agent(agent_id: uuid.UUID, tenant_id: uuid.UUID, db: Session) -> Agent:
    agent = db.get(Agent, agent_id)
    if agent is None or agent.tenant_id != tenant_id:
        raise HTTPException(status_code=404, detail="agent not found")
    return agent


def _owned_candidate(candidate_id: uuid.UUID, tenant_id: uuid.UUID, db: Session) -> CandidateCase:
    candidate = db.get(CandidateCase, candidate_id)
    if candidate is None:
        raise HTTPException(status_code=404, detail="candidate case not found")
    cluster = db.get(FailureCluster, candidate.failure_cluster_id)
    agent = db.get(Agent, cluster.agent_id) if cluster else None
    if agent is None or agent.tenant_id != tenant_id:
        raise HTTPException(status_code=404, detail="candidate case not found")
    return candidate


@router.post("/{agent_id}/run", response_model=list[FailureClusterResponse])
def run_mining(
    agent_id: uuid.UUID,
    ctx: TenantContext = Depends(require_tenant_role("admin", "developer")),
    db: Session = Depends(get_db),
) -> list[MinedCluster]:
    _owned_agent(agent_id, ctx.tenant_id, db)

    try:
        clusters = mine_failures(agent_id)
    except MiningError as e:
        raise HTTPException(status_code=422, detail=str(e))

    return clusters


@router.get("/candidates", response_model=list[CandidateCaseResponse])
def list_candidates(
    agent_id: uuid.UUID = Query(...),
    status: str | None = Query(None),
    ctx: TenantContext = Depends(get_tenant_context),
    db: Session = Depends(get_db),
) -> list[CandidateCase]:
    _owned_agent(agent_id, ctx.tenant_id, db)

    query = (
        db.query(CandidateCase)
        .join(FailureCluster, CandidateCase.failure_cluster_id == FailureCluster.id)
        .filter(FailureCluster.agent_id == agent_id)
    )
    if status is not None:
        query = query.filter(CandidateCase.status == status)
    return query.order_by(CandidateCase.created_at.desc()).all()


@router.post("/candidates/{candidate_id}/approve", response_model=CandidateCaseResponse)
def approve_candidate(
    candidate_id: uuid.UUID,
    ctx: TenantContext = Depends(require_tenant_role("admin", "developer")),
    db: Session = Depends(get_db),
) -> CandidateCase:
    candidate = _owned_candidate(candidate_id, ctx.tenant_id, db)
    if candidate.status != "pending":
        raise HTTPException(
            status_code=409, detail=f"candidate is already '{candidate.status}', not pending"
        )

    cluster = db.get(FailureCluster, candidate.failure_cluster_id)
    suite = (
        db.query(EvalSuite)
        .filter(EvalSuite.agent_id == cluster.agent_id, EvalSuite.name == MINED_SUITE_NAME)
        .first()
    )
    if suite is None:
        suite = EvalSuite(agent_id=cluster.agent_id, name=MINED_SUITE_NAME)
        db.add(suite)
        db.flush()

    new_case = EvalCase(
        suite_id=suite.id,
        case_key=candidate.case_key,
        description=f"Mined from failure cluster {cluster.cluster_label} (approved)",
        turns=candidate.turns,
        expectations=candidate.expectations,
    )
    db.add(new_case)
    db.flush()

    candidate.status = "approved"
    candidate.promoted_case_id = new_case.id
    candidate.reviewed_at = datetime.utcnow()
    db.commit()
    return candidate


@router.post("/candidates/{candidate_id}/reject", response_model=CandidateCaseResponse)
def reject_candidate(
    candidate_id: uuid.UUID,
    ctx: TenantContext = Depends(require_tenant_role("admin", "developer")),
    db: Session = Depends(get_db),
) -> CandidateCase:
    candidate = _owned_candidate(candidate_id, ctx.tenant_id, db)
    if candidate.status != "pending":
        raise HTTPException(
            status_code=409, detail=f"candidate is already '{candidate.status}', not pending"
        )

    candidate.status = "rejected"
    candidate.reviewed_at = datetime.utcnow()
    db.commit()
    return candidate
