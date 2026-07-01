"""
Eval run endpoints (Phase1 roadmap Section 10 acceptance criteria).

POST /eval-runs creates the EvalRun row, publishes an "eval.requested" job, and
returns immediately with status: pending -- it never blocks waiting for the worker.
GET /eval-runs/{id} just reads current state, which the worker updates asynchronously.
"""
import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from apps.api.services import gate_engine

from apps.api.core.db import get_db
from apps.api.core.jobqueue import PostgresJobQueue
from apps.api.models import EvalRun, Tenant
from apps.api.schemas.eval_run import EvalRunCreate, EvalRunResponse

router = APIRouter(prefix="/eval-runs", tags=["eval-runs"])


@router.post("", response_model=EvalRunResponse, status_code=201)
def create_eval_run(payload: EvalRunCreate, db: Session = Depends(get_db)) -> EvalRun:
    # Phase 1 runs with a single seeded tenant (roadmap Section 1) -- no tenant
    # resolution from auth yet, that's explicitly a Phase 2 concern.
    tenant = db.query(Tenant).first()
    if tenant is None:
        raise HTTPException(status_code=500, detail="no tenant seeded")

    eval_run = EvalRun(
        tenant_id=tenant.id,
        agent_version_id=payload.agent_version_id,
        suite_id=payload.suite_id,
        status="pending",
        triggered_by=payload.triggered_by,
    )
    db.add(eval_run)
    db.commit()
    db.refresh(eval_run)

    queue = PostgresJobQueue(db)
    queue.publish(tenant.id, "eval.requested", {"eval_run_id": str(eval_run.id)})

    return eval_run


@router.get("/{eval_run_id}", response_model=EvalRunResponse)
def get_eval_run(eval_run_id: uuid.UUID, db: Session = Depends(get_db)) -> EvalRunResponse:
    eval_run = db.get(EvalRun, eval_run_id)
    if eval_run is None:
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