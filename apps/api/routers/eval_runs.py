"""
Eval run endpoints (Phase1 roadmap Section 10, Phase 3 Section 1).

POST /eval-runs creates the EvalRun row, publishes an "eval.requested" job, and
returns immediately with status: pending -- it never blocks waiting for the worker.
GET /eval-runs/{id} just reads current state, which the worker updates asynchronously.

Phase 3 Section 1 changes:
  - POST requires admin/developer; triggering an eval spends the tenant's LLM budget,
    so it is not a Viewer action
  - the tenant comes from the auth context, replacing `db.query(Tenant).first()`
  - GET is tenant-scoped -- a run belonging to another tenant 404s rather than
    returning its gate result and status
"""
import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from apps.api.core.db import get_db
from apps.api.core.redpanda_queue import RedpandaJobQueue
from apps.api.core.security import TenantContext, get_tenant_context, require_tenant_role
from apps.api.models import EvalRun
from apps.api.schemas.eval_run import EvalRunCreate, EvalRunResponse
from apps.api.services import gate_engine

router = APIRouter(prefix="/eval-runs", tags=["eval-runs"])


@router.post("", response_model=EvalRunResponse, status_code=201)
def create_eval_run(
    payload: EvalRunCreate,
    ctx: TenantContext = Depends(require_tenant_role("admin", "developer")),
    db: Session = Depends(get_db),
) -> EvalRun:
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

    queue = RedpandaJobQueue(db)
    queue.publish(
        ctx.tenant_id,
        "eval.requested",
        {"eval_run_id": str(eval_run.id)},
    )

    return eval_run


@router.get("/{eval_run_id}", response_model=EvalRunResponse)
def get_eval_run(
    eval_run_id: uuid.UUID,
    ctx: TenantContext = Depends(get_tenant_context),
    db: Session = Depends(get_db),
) -> EvalRunResponse:
    from apps.api.core.redis_client import JobStatusCache
    cache = JobStatusCache()

    eval_run = db.get(EvalRun, eval_run_id)
    if eval_run is None or eval_run.tenant_id != ctx.tenant_id:
        raise HTTPException(status_code=404, detail="eval_run not found")

    gate_result = gate_engine.evaluate(eval_run.id) if eval_run.status == "completed" else None

    # Cache completed runs -- gate_result is immutable once the run is done
    if eval_run.status == "completed":
        cache.set(eval_run_id, {
            "status": eval_run.status,
            "result": None,
            "error": None
        })

    return EvalRunResponse(
        id=eval_run.id,
        status=eval_run.status,
        triggered_by=eval_run.triggered_by,
        started_at=eval_run.started_at,
        completed_at=eval_run.completed_at,
        error=eval_run.error,
        gate_result=gate_result,
    )
