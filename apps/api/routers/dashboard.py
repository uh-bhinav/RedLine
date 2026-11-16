"""
Dashboard read endpoints (Phase1 roadmap Section 14, Phase 3 Section 1).

Phase 1 shipped these unauthenticated with the comment "the dashboard is a read-only
internal tool." That is true on a laptop with one seeded tenant and false everywhere
else: unauthenticated + `db.query(Tenant).first()` means any caller could read the
first tenant's agents, runs and full transcripts.

Phase 3 Section 1 closes that:
  - every route requires auth (any role -- these are read-only)
  - the tenant comes from the auth context, never from `Tenant.first()`
  - single-object lookups (agent, run) verify tenant ownership before returning,
    so a valid credential for tenant A cannot read tenant B's run by guessing a UUID
"""
import dataclasses
import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from apps.api.core.clickhouse_client import get_clickhouse
from apps.api.core.db import get_db
from apps.api.core.security import TenantContext, get_tenant_context
from apps.api.models import (
    Agent,
    AgentVersion,
    ARSSnapshot,
    BehaviorDiff,
    DriftAlert,
    EvalCase,
    EvalCaseResult,
    EvalRun,
    LoadRun,
)
from apps.api.schemas.dashboard import (
    AgentDetailResponse,
    AgentLatestRun,
    AgentListItem,
    AgentVersionSummary,
    ArsSnapshotItem,
    CaseResultItem,
    DriftAlertItem,
    ErrorBudgetResponse,
    EvalRunSummary,
    LoadRunSummary,
    RunDetailResponse,
    TraceEventItem,
)
from apps.api.services import ars_engine
from apps.api.services.adapters.chaos_adapter import has_chaos_marker
from apps.api.services.gate_engine import evaluate

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


def _owned_agent(agent_id: uuid.UUID, tenant_id: uuid.UUID, db: Session) -> Agent:
    """Loads an agent, 404ing if it does not exist *or* belongs to another tenant.

    Deliberately 404 and not 403: a 403 would confirm the resource exists, which
    leaks the existence of another tenant's agents to anyone probing UUIDs.
    """
    agent = db.get(Agent, agent_id)
    if agent is None or agent.tenant_id != tenant_id:
        raise HTTPException(status_code=404, detail="agent not found")
    return agent


@router.get("/agents", response_model=list[AgentListItem])
def list_agents(
    ctx: TenantContext = Depends(get_tenant_context),
    db: Session = Depends(get_db),
) -> list[AgentListItem]:
    agents = (
        db.query(Agent)
        .filter(Agent.tenant_id == ctx.tenant_id)
        .order_by(Agent.created_at)
        .all()
    )
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
            .filter(
                EvalRun.tenant_id == ctx.tenant_id,
                EvalRun.agent_version_id.in_(
                    db.query(AgentVersion.id).filter(AgentVersion.agent_id == agent.id)
                ),
            )
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
def agent_detail(
    agent_id: uuid.UUID,
    ctx: TenantContext = Depends(get_tenant_context),
    db: Session = Depends(get_db),
) -> AgentDetailResponse:
    agent = _owned_agent(agent_id, ctx.tenant_id, db)

    versions = (
        db.query(AgentVersion)
        .filter(AgentVersion.agent_id == agent.id)
        .order_by(AgentVersion.created_at.desc())
        .all()
    )

    runs = (
        db.query(EvalRun)
        .filter(
            EvalRun.tenant_id == ctx.tenant_id,
            EvalRun.agent_version_id.in_([v.id for v in versions]),
        )
        .order_by(EvalRun.created_at.desc())
        .limit(20)
        .all()
    ) if versions else []

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
            error=run.error,
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
def run_detail(
    eval_run_id: uuid.UUID,
    ctx: TenantContext = Depends(get_tenant_context),
    db: Session = Depends(get_db),
) -> RunDetailResponse:
    run = db.get(EvalRun, eval_run_id)
    if run is None or run.tenant_id != ctx.tenant_id:
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
            transcript=r.transcript,
            is_chaos_case=any(
                has_chaos_marker(turn.get("tool_calls")) for turn in r.transcript
            ),
        ))

    return RunDetailResponse(
        id=run.id,
        status=run.status,
        triggered_by=run.triggered_by,
        gate_result=gate,
        started_at=run.started_at,
        completed_at=run.completed_at,
        error=run.error,
        case_results=case_results,
    )


@router.get("/agents/{agent_id}/ars-history", response_model=list[ArsSnapshotItem])
def agent_ars_history(
    agent_id: uuid.UUID,
    ctx: TenantContext = Depends(get_tenant_context),
    db: Session = Depends(get_db),
) -> list[ArsSnapshotItem]:
    agent = _owned_agent(agent_id, ctx.tenant_id, db)

    versions = db.query(AgentVersion).filter(AgentVersion.agent_id == agent.id).all()
    version_labels = {v.id: v.version_label for v in versions}

    snapshots = (
        db.query(ARSSnapshot)
        .filter(ARSSnapshot.agent_version_id.in_(version_labels.keys()))
        .order_by(ARSSnapshot.created_at.asc())
        .all()
    )

    return [
        ArsSnapshotItem(
            id=s.id,
            agent_version_id=s.agent_version_id,
            version_label=version_labels.get(s.agent_version_id, "unknown"),
            eval_run_id=s.eval_run_id,
            ars=s.ars,
            correctness=s.correctness,
            safety=s.safety,
            latency=s.latency,
            cost=s.cost,
            created_at=s.created_at,
        )
        for s in snapshots
    ]


@router.get("/agents/{agent_id}/error-budget", response_model=ErrorBudgetResponse)
def agent_error_budget(
    agent_id: uuid.UUID,
    ctx: TenantContext = Depends(get_tenant_context),
    db: Session = Depends(get_db),
) -> ErrorBudgetResponse:
    agent = _owned_agent(agent_id, ctx.tenant_id, db)
    result = ars_engine.evaluate_error_budget(agent.id)
    return ErrorBudgetResponse(**dataclasses.asdict(result))


@router.get("/agents/{agent_id}/drift-alerts", response_model=list[DriftAlertItem])
def agent_drift_alerts(
    agent_id: uuid.UUID,
    ctx: TenantContext = Depends(get_tenant_context),
    db: Session = Depends(get_db),
) -> list[DriftAlertItem]:
    """Merges DriftAlert (model drift, pass-rate based) and BehaviorDiff rows
    classified 'silent_drift' (behavior drift, similarity based) into one feed --
    these are stored in two different tables for good reason (see BehaviorDiff's
    own docstring), but the dashboard's alerts list is one normalized stream."""
    agent = _owned_agent(agent_id, ctx.tenant_id, db)
    version_ids = [
        v.id for v in db.query(AgentVersion.id).filter(AgentVersion.agent_id == agent.id)
    ]

    model_alerts = (
        db.query(DriftAlert).filter(DriftAlert.agent_version_id.in_(version_ids)).all()
    )
    behavior_alerts = (
        db.query(BehaviorDiff)
        .filter(
            BehaviorDiff.version_a_id.in_(version_ids),
            BehaviorDiff.classification == "silent_drift",
        )
        .all()
    )

    items = [
        DriftAlertItem(
            id=a.id,
            drift_type="model",
            agent_version_id=a.agent_version_id,
            suite_id=a.suite_id,
            metric_label="pass_rate",
            baseline_value=a.baseline_pass_rate,
            current_value=a.current_pass_rate,
            delta=a.delta,
            threshold=a.threshold,
            detail=a.detail or "",
            created_at=a.created_at,
        )
        for a in model_alerts
    ] + [
        DriftAlertItem(
            id=d.id,
            drift_type="behavior",
            agent_version_id=d.version_a_id,
            suite_id=d.suite_id,
            metric_label="similarity",
            baseline_value=1.0,
            current_value=d.mean_similarity,
            delta=1.0 - d.mean_similarity,
            threshold=d.similarity_threshold,
            detail=d.detail,
            created_at=d.created_at,
        )
        for d in behavior_alerts
    ]

    items.sort(key=lambda i: i.created_at, reverse=True)
    return items


@router.get("/agents/{agent_id}/load-runs", response_model=list[LoadRunSummary])
def agent_load_runs(
    agent_id: uuid.UUID,
    ctx: TenantContext = Depends(get_tenant_context),
    db: Session = Depends(get_db),
) -> list[LoadRunSummary]:
    agent = _owned_agent(agent_id, ctx.tenant_id, db)
    version_ids = [
        v.id for v in db.query(AgentVersion.id).filter(AgentVersion.agent_id == agent.id)
    ]

    runs = (
        db.query(LoadRun)
        .filter(LoadRun.agent_version_id.in_(version_ids))
        .order_by(LoadRun.created_at.desc())
        .limit(20)
        .all()
    )

    return [
        LoadRunSummary(
            id=r.id,
            status=r.status,
            triggered_by=r.triggered_by,
            concurrency=r.concurrency,
            duration_seconds=r.duration_seconds,
            p95_latency_ms=r.p95_latency_ms,
            error_rate=r.error_rate,
            cost_per_hour_usd=r.cost_per_hour_usd,
            started_at=r.started_at,
            completed_at=r.completed_at,
        )
        for r in runs
    ]


@router.get("/runs/{eval_run_id}/traces", response_model=list[TraceEventItem])
def run_traces(
    eval_run_id: uuid.UUID,
    ctx: TenantContext = Depends(get_tenant_context),
    db: Session = Depends(get_db),
) -> list[TraceEventItem]:
    # Ownership checked in Postgres first (same 404-not-403 discipline as every
    # other single-object lookup in this file), THEN queried from ClickHouse by
    # eval_run_id AND tenant_id -- defense in depth even though the Postgres
    # check already scoped which run_id is legitimate to query.
    run = db.get(EvalRun, eval_run_id)
    if run is None or run.tenant_id != ctx.tenant_id:
        raise HTTPException(status_code=404, detail="eval run not found")

    ch = get_clickhouse()
    rows = ch.execute(
        """
        SELECT trace_id, event_type, case_key, turn_index, latency_ms, cost_usd, passed, detail, created_at
        FROM traces
        WHERE eval_run_id = %(eval_run_id)s AND tenant_id = %(tenant_id)s
        ORDER BY created_at ASC
        """,
        {"eval_run_id": eval_run_id, "tenant_id": ctx.tenant_id},
    )

    return [
        TraceEventItem(
            trace_id=row[0],
            event_type=row[1],
            case_key=row[2],
            turn_index=row[3],
            latency_ms=row[4],
            cost_usd=row[5],
            passed=bool(row[6]) if row[6] is not None else None,
            detail=row[7],
            created_at=row[8],
        )
        for row in rows
    ]
