"""
Dashboard read endpoints (Phase1 roadmap Section 14).

Three GET routes, one per dashboard page. No auth required on these — the dashboard
is a read-only internal tool; all mutation still goes through the authed endpoints.
"""
import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from apps.api.core.db import get_db
from apps.api.models import Agent, AgentVersion, EvalCase, EvalCaseResult, EvalRun, Tenant
from apps.api.schemas.dashboard import (
    AgentDetailResponse,
    AgentLatestRun,
    AgentListItem,
    AgentVersionSummary,
    CaseResultItem,
    EvalRunSummary,
    RunDetailResponse,
)
from apps.api.services.gate_engine import evaluate

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("/agents", response_model=list[AgentListItem])
def list_agents(db: Session = Depends(get_db)) -> list[AgentListItem]:
    tenant = db.query(Tenant).first()
    if tenant is None:
        return []

    agents = db.query(Agent).filter(Agent.tenant_id == tenant.id).order_by(Agent.created_at).all()
    result = []

    for agent in agents:
        latest_version = (
            db.query(AgentVersion)
            .filter(AgentVersion.agent_id == agent.id)
            .order_by(AgentVersion.created_at.desc())
            .first()
        )

        latest_run = (
            db.query(EvalRun)
            .filter(EvalRun.tenant_id == tenant.id, EvalRun.agent_version_id.in_(
                db.query(AgentVersion.id).filter(AgentVersion.agent_id == agent.id)
            ))
            .order_by(EvalRun.created_at.desc())
            .first()
        )

        latest_run_summary = None
        if latest_run is not None:
            gate = evaluate(latest_run.id) if latest_run.status == "completed" else None
            latest_run_summary = AgentLatestRun(
                id=latest_run.id,
                status=latest_run.status,
                gate_passed=gate.passed if gate else None,
                completed_at=latest_run.completed_at,
            )

        result.append(AgentListItem(
            id=agent.id,
            name=agent.name,
            description=agent.description,
            latest_version_label=latest_version.version_label if latest_version else None,
            latest_run=latest_run_summary,
            created_at=agent.created_at,
        ))

    return result


@router.get("/agents/{agent_id}", response_model=AgentDetailResponse)
def agent_detail(agent_id: uuid.UUID, db: Session = Depends(get_db)) -> AgentDetailResponse:
    agent = db.get(Agent, agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail="agent not found")

    versions = (
        db.query(AgentVersion)
        .filter(AgentVersion.agent_id == agent.id)
        .order_by(AgentVersion.created_at.desc())
        .all()
    )

    tenant = db.query(Tenant).first()
    runs = (
        db.query(EvalRun)
        .filter(EvalRun.tenant_id == tenant.id, EvalRun.agent_version_id.in_(
            [v.id for v in versions]
        ))
        .order_by(EvalRun.created_at.desc())
        .limit(20)
        .all()
    )

    run_summaries = []
    for run in runs:
        gate = evaluate(run.id) if run.status == "completed" else None
        run_summaries.append(EvalRunSummary(
            id=run.id,
            status=run.status,
            triggered_by=run.triggered_by,
            gate_result=gate,
            started_at=run.started_at,
            completed_at=run.completed_at,
        ))

    return AgentDetailResponse(
        id=agent.id,
        name=agent.name,
        description=agent.description,
        created_at=agent.created_at,
        versions=[AgentVersionSummary.model_validate(v) for v in versions],
        recent_runs=run_summaries,
    )


@router.get("/runs/{eval_run_id}", response_model=RunDetailResponse)
def run_detail(eval_run_id: uuid.UUID, db: Session = Depends(get_db)) -> RunDetailResponse:
    run = db.get(EvalRun, eval_run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="eval run not found")

    gate = evaluate(run.id) if run.status == "completed" else None

    raw_results = (
        db.query(EvalCaseResult)
        .filter(EvalCaseResult.eval_run_id == run.id)
        .all()
    )

    case_results = []
    for r in raw_results:
        case = db.get(EvalCase, r.case_id)
        case_results.append(CaseResultItem(
            case_id=r.case_id,
            case_key=case.case_key if case else str(r.case_id),
            passed=r.passed,
            cost_usd=r.metrics.get("cost_usd", 0.0),
            latency_ms=r.metrics.get("latency_ms", 0),
            scorer_results=r.scorer_results,
        ))

    return RunDetailResponse(
        id=run.id,
        status=run.status,
        triggered_by=run.triggered_by,
        gate_result=gate,
        started_at=run.started_at,
        completed_at=run.completed_at,
        case_results=case_results,
    )