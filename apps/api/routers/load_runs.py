"""
Load-test endpoints (Phase 4 Section 5).

Owned by eval_service, same reasoning as /diff-runs -- this is eval-adjacent
execution, not registry or gate-policy territory.

Unlike /diff-runs (computed synchronously -- an embedding call per case takes
seconds), a load test can run for minutes, so this follows /eval-runs's async
pattern exactly: create a LoadRun row (status=pending), publish to Redpanda,
return the id immediately. The CLI polls, same as `agentbench run`.
"""
import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from apps.api.core.db import get_db
from apps.api.core.redpanda_queue import RedpandaJobQueue
from apps.api.core.security import TenantContext, get_tenant_context, require_tenant_role
from apps.api.models import Agent, AgentVersion, LoadRun
from apps.api.schemas.load_run import LoadRunCreate, LoadRunResponse

router = APIRouter(prefix="/load-runs", tags=["load"])


@router.post("", response_model=LoadRunResponse, status_code=201)
def create_load_run(
    payload: LoadRunCreate,
    ctx: TenantContext = Depends(require_tenant_role("admin", "developer")),
    db: Session = Depends(get_db),
) -> LoadRun:
    version = db.get(AgentVersion, payload.agent_version_id)
    if version is None:
        raise HTTPException(status_code=404, detail="agent version not found")
    agent = db.get(Agent, version.agent_id)
    if agent is None or agent.tenant_id != ctx.tenant_id:
        raise HTTPException(status_code=404, detail="agent version not found")

    load_run = LoadRun(
        tenant_id=ctx.tenant_id,
        agent_version_id=payload.agent_version_id,
        message=payload.message,
        concurrency=payload.concurrency,
        duration_seconds=payload.duration_seconds,
        status="pending",
        triggered_by=payload.triggered_by,
    )
    db.add(load_run)
    db.commit()
    db.refresh(load_run)

    queue = RedpandaJobQueue(db)
    queue.publish(
        ctx.tenant_id,
        "load.requested",
        {"load_run_id": str(load_run.id)},
    )

    return load_run


@router.get("/{load_run_id}", response_model=LoadRunResponse)
def get_load_run(
    load_run_id: uuid.UUID,
    ctx: TenantContext = Depends(get_tenant_context),
    db: Session = Depends(get_db),
) -> LoadRun:
    load_run = db.get(LoadRun, load_run_id)
    if load_run is None or load_run.tenant_id != ctx.tenant_id:
        raise HTTPException(status_code=404, detail="load run not found")
    return load_run
