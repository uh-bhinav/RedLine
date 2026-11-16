"""
Eval run endpoints.

POST /eval-runs creates the EvalRun row, publishes an "eval.requested" job, and returns
immediately with status: pending -- it never blocks waiting for the worker.
GET /eval-runs/{id} just reads current state, which the worker updates asynchronously.

Callers authenticate with either a dashboard JWT or a CLI API key; every lookup is scoped
to the caller's tenant (an agent version / suite from another tenant is a 404).
"""
import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from apps.api.core.db import get_db
from apps.api.core.jobqueue import PostgresJobQueue
from apps.api.core.security import TenantContext, require_tenant_role
from apps.api.models import Agent, AgentVersion, EvalRun, EvalSuite
from apps.api.schemas.eval_run import EvalRunCreate, EvalRunResponse
from apps.api.services import gate_engine

router = APIRouter(prefix="/eval-runs", tags=["eval-runs"])


def _check_ownership(db: Session, ctx: TenantContext, version_id: uuid.UUID, suite_id: uuid.UUID) -> None:
    version = db.get(AgentVersion, version_id)
    agent = db.get(Agent, version.agent_id) if version else None
    suite = db.get(EvalSuite, suite_id)
    if agent is None or agent.tenant_id != ctx.tenant_id:
        raise HTTPException(status_code=404, detail="agent version not found")
    if suite is None or suite.agent_id != agent.id:
        raise HTTPException(status_code=404, detail="suite not found for this agent")


@router.post("", response_model=EvalRunResponse, status_code=201)
def create_eval_run(
    payload: EvalRunCreate,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_tenant_role("developer")),
) -> EvalRun:
    _check_ownership(db, ctx, payload.agent_version_id, payload.suite_id)

    eval_run = EvalRun(
        tenant_id=ctx.tenant_id,
        agent_version_id=payload.agent_version_id,
        suite_id=payload.suite_id,
        status="pending",
        triggered_by=payload.triggered_by,
    )
    db.add(eval_run)
    db.commit()
    db.refresh(eval_run)

    PostgresJobQueue(db).publish(ctx.tenant_id, "eval.requested", {"eval_run_id": str(eval_run.id)})
    return eval_run


@router.get("/{eval_run_id}", response_model=EvalRunResponse)
def get_eval_run(
    eval_run_id: uuid.UUID,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_tenant_role("viewer")),
) -> EvalRunResponse:
    eval_run = db.get(EvalRun, eval_run_id)
    if eval_run is None or eval_run.tenant_id != ctx.tenant_id:
        raise HTTPException(status_code=404, detail="eval_run not found")

    # Computed fresh on every read, not persisted -- gate_engine.evaluate() is cheap
    # and pure (reads case results + policy), so there's nothing to keep in sync.
    gate_result = gate_engine.evaluate(eval_run.id) if eval_run.status == "completed" else None

    return EvalRunResponse(
        id=eval_run.id,
        status=eval_run.status,
        triggered_by=eval_run.triggered_by,
        started_at=eval_run.started_at,
        completed_at=eval_run.completed_at,
        gate_result=gate_result,
    )
