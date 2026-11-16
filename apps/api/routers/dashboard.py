"""Read models for the dashboard UI. Everything is scoped to the caller's tenant."""
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from apps.api.core.db import get_db
from apps.api.core.security import TenantContext, require_tenant_role
from apps.api.models import (
    Agent,
    AgentVersion,
    ARSSnapshot,
    DriftAlert,
    EvalCase,
    EvalCaseResult,
    EvalRun,
    EvalSuite,
    LoadRun,
)
from apps.api.schemas.dashboard import (
    AgentDetail,
    AgentLatestRun,
    AgentListItem,
    ARSBreakdown,
    ARSPoint,
    CaseResultOut,
    DriftAlertOut,
    LoadRunOut,
    PlatformSummary,
    RunDetail,
    RunListItem,
    SuiteOut,
    TraceEvent,
    VersionOut,
)
from apps.api.services import ars_engine, gate_engine

router = APIRouter(prefix="/dashboard", tags=["dashboard"])
Viewer = Depends(require_tenant_role("viewer"))


def _gate(run: EvalRun) -> gate_engine.GateResult | None:
    if run.status != "completed":
        return None
    try:
        return gate_engine.evaluate(run.id)
    except Exception:  # noqa: BLE001
        return None


def _agent_or_404(db: Session, ctx: TenantContext, agent_id: uuid.UUID) -> Agent:
    agent = db.get(Agent, agent_id)
    if agent is None or agent.tenant_id != ctx.tenant_id:
        raise HTTPException(status_code=404, detail="agent not found")
    return agent


def _tenant_runs(db: Session, ctx: TenantContext):
    return (
        db.query(EvalRun, AgentVersion, Agent, EvalSuite)
        .join(AgentVersion, AgentVersion.id == EvalRun.agent_version_id)
        .join(Agent, Agent.id == AgentVersion.agent_id)
        .join(EvalSuite, EvalSuite.id == EvalRun.suite_id)
        .filter(Agent.tenant_id == ctx.tenant_id)
    )


def _run_item(db: Session, run, version, agent, suite) -> RunListItem:
    gate = _gate(run)
    snap = db.query(ARSSnapshot).filter(ARSSnapshot.eval_run_id == run.id).first()
    return RunListItem(
        id=run.id,
        agent_id=agent.id,
        agent_name=agent.name,
        version_label=version.version_label,
        suite_name=suite.name,
        status=run.status,
        triggered_by=run.triggered_by,
        gate_passed=gate.passed if gate else None,
        ars=snap.ars if snap else None,
        created_at=run.created_at,
        completed_at=run.completed_at,
    )


def _alert_out(alert: DriftAlert, agent_name: str | None = None) -> DriftAlertOut:
    return DriftAlertOut(
        id=alert.id,
        agent_id=alert.agent_id,
        agent_name=agent_name,
        drift_type=alert.drift_type,
        metric=alert.metric,
        baseline_value=alert.baseline_value,
        current_value=alert.current_value,
        message=alert.message,
        eval_run_id=alert.eval_run_id,
        diff_run_id=alert.diff_run_id,
        detected_at=alert.detected_at,
    )


def load_run_out(load: LoadRun, db: Session) -> LoadRunOut:
    version = db.get(AgentVersion, load.agent_version_id)
    agent = db.get(Agent, version.agent_id)
    return LoadRunOut(
        id=load.id,
        agent_id=agent.id,
        agent_name=agent.name,
        status=load.status,
        concurrency=load.concurrency,
        duration_seconds=load.duration_seconds,
        p50_ms=load.p50_ms,
        p95_ms=load.p95_ms,
        p99_ms=load.p99_ms,
        error_rate=load.error_rate,
        throughput_rps=load.throughput_rps,
        cost_per_hour_usd=load.cost_per_hour_usd,
        total_requests=load.total_requests,
        latency_series=load.latency_series,
        created_at=load.created_at,
    )


@router.get("/summary", response_model=PlatformSummary)
def platform_summary(ctx: TenantContext = Viewer, db: Session = Depends(get_db)) -> PlatformSummary:
    week_ago = datetime.now(timezone.utc) - timedelta(days=7)
    agents = ars_engine.tenant_agents(db, ctx.tenant_id)
    rows = _tenant_runs(db, ctx).order_by(EvalRun.created_at.desc()).limit(200).all()

    runs_last_7d = sum(1 for run, *_ in rows if run.created_at >= week_ago)
    verdicts = [g.passed for run, *_ in rows if (g := _gate(run)) is not None]
    gate_pass_rate = round(sum(verdicts) / len(verdicts), 3) if verdicts else None

    healthy = sum(1 for a in agents if not ars_engine.evaluate_error_budget(db, a.id).exhausted)
    return PlatformSummary(
        total_agents=len(agents),
        runs_last_7d=runs_last_7d,
        gate_pass_rate=gate_pass_rate,
        healthy_budget_count=healthy,
        total_budget_count=len(agents),
    )


@router.get("/agents", response_model=list[AgentListItem])
def list_agents(ctx: TenantContext = Viewer, db: Session = Depends(get_db)) -> list[AgentListItem]:
    items: list[AgentListItem] = []
    for agent in ars_engine.tenant_agents(db, ctx.tenant_id):
        version = (
            db.query(AgentVersion)
            .filter(AgentVersion.agent_id == agent.id)
            .order_by(AgentVersion.created_at.desc())
            .first()
        )
        latest = (
            _tenant_runs(db, ctx)
            .filter(Agent.id == agent.id)
            .order_by(EvalRun.created_at.desc())
            .first()
        )
        latest_run = None
        if latest:
            gate = _gate(latest[0])
            latest_run = AgentLatestRun(
                id=latest[0].id,
                status=latest[0].status,
                gate_passed=gate.passed if gate else None,
                created_at=latest[0].created_at,
            )
        snaps = ars_engine.agent_snapshots(db, agent.id, limit=1)
        items.append(
            AgentListItem(
                id=agent.id,
                name=agent.name,
                description=agent.description,
                latest_version_label=version.version_label if version else None,
                latest_run=latest_run,
                latest_ars=snaps[0].ars if snaps else None,
                error_budget_status=ars_engine.evaluate_error_budget(db, agent.id).status,
                created_at=agent.created_at,
            )
        )
    return items


@router.get("/agents/{agent_id}", response_model=AgentDetail)
def agent_detail(
    agent_id: uuid.UUID, ctx: TenantContext = Viewer, db: Session = Depends(get_db)
) -> AgentDetail:
    agent = _agent_or_404(db, ctx, agent_id)
    versions = (
        db.query(AgentVersion)
        .filter(AgentVersion.agent_id == agent.id)
        .order_by(AgentVersion.created_at.desc())
        .all()
    )
    suites = []
    for s in db.query(EvalSuite).filter(EvalSuite.agent_id == agent.id).all():
        n = db.query(EvalCase).filter(EvalCase.suite_id == s.id).count()
        suites.append(SuiteOut(id=s.id, agent_id=agent.id, name=s.name, case_count=n))

    run_rows = (
        _tenant_runs(db, ctx)
        .filter(Agent.id == agent.id)
        .order_by(EvalRun.created_at.desc())
        .limit(15)
        .all()
    )
    recent_runs = [_run_item(db, r, v, a, s) for r, v, a, s in run_rows]
    snaps = ars_engine.agent_snapshots(db, agent.id, limit=1)
    latest_completed = next((r for r, *_ in run_rows if r.status == "completed"), None)

    alerts = (
        db.query(DriftAlert)
        .filter(DriftAlert.agent_id == agent.id)
        .order_by(DriftAlert.detected_at.desc())
        .limit(20)
        .all()
    )
    loads = (
        db.query(LoadRun)
        .join(AgentVersion, AgentVersion.id == LoadRun.agent_version_id)
        .filter(AgentVersion.agent_id == agent.id)
        .order_by(LoadRun.created_at.desc())
        .limit(10)
        .all()
    )
    return AgentDetail(
        id=agent.id,
        name=agent.name,
        description=agent.description,
        created_at=agent.created_at,
        latest_version=VersionOut.model_validate(versions[0]) if versions else None,
        versions=[VersionOut.model_validate(v) for v in versions],
        suites=suites,
        recent_runs=recent_runs,
        latest_ars=snaps[0].ars if snaps else None,
        latest_gate=_gate(latest_completed) if latest_completed else None,
        error_budget=ars_engine.evaluate_error_budget(db, agent.id),
        drift_alerts=[_alert_out(a, agent.name) for a in alerts],
        load_runs=[load_run_out(load, db) for load in loads],
    )


@router.get("/agents/{agent_id}/ars-history", response_model=list[ARSPoint])
def ars_history(
    agent_id: uuid.UUID, ctx: TenantContext = Viewer, db: Session = Depends(get_db)
) -> list[ARSPoint]:
    agent = _agent_or_404(db, ctx, agent_id)
    versions = {v.id: v for v in db.query(AgentVersion).filter(AgentVersion.agent_id == agent.id)}
    snaps = sorted(ars_engine.agent_snapshots(db, agent.id), key=lambda s: s.created_at)
    return [
        ARSPoint(
            eval_run_id=s.eval_run_id,
            version_label=versions[s.agent_version_id].version_label,
            ars=s.ars,
            correctness=s.correctness,
            safety=s.safety,
            latency=s.latency,
            cost=s.cost,
            created_at=s.created_at,
        )
        for s in snaps
    ]


@router.get("/agents/{agent_id}/error-budget", response_model=ars_engine.ErrorBudget)
def error_budget(
    agent_id: uuid.UUID, ctx: TenantContext = Viewer, db: Session = Depends(get_db)
) -> ars_engine.ErrorBudget:
    _agent_or_404(db, ctx, agent_id)
    return ars_engine.evaluate_error_budget(db, agent_id)


@router.get("/agents/{agent_id}/drift-alerts", response_model=list[DriftAlertOut])
def drift_alerts(
    agent_id: uuid.UUID, ctx: TenantContext = Viewer, db: Session = Depends(get_db)
) -> list[DriftAlertOut]:
    agent = _agent_or_404(db, ctx, agent_id)
    rows = (
        db.query(DriftAlert)
        .filter(DriftAlert.agent_id == agent.id)
        .order_by(DriftAlert.detected_at.desc())
        .all()
    )
    return [_alert_out(a, agent.name) for a in rows]


@router.get("/runs", response_model=list[RunListItem])
def list_runs(
    agent_id: uuid.UUID | None = Query(default=None),
    ctx: TenantContext = Viewer,
    db: Session = Depends(get_db),
) -> list[RunListItem]:
    q = _tenant_runs(db, ctx)
    if agent_id:
        q = q.filter(Agent.id == agent_id)
    return [_run_item(db, r, v, a, s) for r, v, a, s in q.order_by(EvalRun.created_at.desc()).limit(100).all()]


@router.get("/runs/{run_id}", response_model=RunDetail)
def run_detail(run_id: uuid.UUID, ctx: TenantContext = Viewer, db: Session = Depends(get_db)) -> RunDetail:
    row = _tenant_runs(db, ctx).filter(EvalRun.id == run_id).first()
    if row is None:
        raise HTTPException(status_code=404, detail="run not found")
    run, version, agent, suite = row

    cases = {c.id: c for c in db.query(EvalCase).filter(EvalCase.suite_id == suite.id)}
    results = (
        db.query(EvalCaseResult)
        .filter(EvalCaseResult.eval_run_id == run.id)
        .order_by(EvalCaseResult.created_at)
        .all()
    )
    snap = db.query(ARSSnapshot).filter(ARSSnapshot.eval_run_id == run.id).first()
    return RunDetail(
        id=run.id,
        status=run.status,
        triggered_by=run.triggered_by,
        agent_id=agent.id,
        agent_name=agent.name,
        version_label=version.version_label,
        suite_name=suite.name,
        started_at=run.started_at,
        completed_at=run.completed_at,
        created_at=run.created_at,
        gate_result=_gate(run),
        ars=ARSBreakdown(
            ars=snap.ars, correctness=snap.correctness, safety=snap.safety,
            latency=snap.latency, cost=snap.cost,
        ) if snap else None,
        cases=[
            CaseResultOut(
                id=r.id,
                case_key=cases[r.case_id].case_key,
                description=cases[r.case_id].description,
                is_chaos=cases[r.case_id].is_chaos,
                passed=r.passed,
                metrics=r.metrics,
                transcript=r.transcript,
                scorer_results=r.scorer_results,
            )
            for r in results
            if r.case_id in cases
        ],
    )


@router.get("/runs/{run_id}/traces", response_model=list[TraceEvent])
def run_traces(run_id: uuid.UUID, ctx: TenantContext = Viewer, db: Session = Depends(get_db)) -> list[TraceEvent]:
    detail = run_detail(run_id, ctx, db)
    events: list[TraceEvent] = []
    for case in detail.cases:
        turn = 0
        for t in case.transcript:
            if t["role"] == "user":
                turn += 1
                events.append(TraceEvent(case_key=case.case_key, turn=turn, kind="user", content=t["content"]))
                continue
            for call in t.get("tool_calls") or []:
                events.append(
                    TraceEvent(
                        case_key=case.case_key, turn=turn, kind="tool", name=call.get("name"),
                        content=f"{call.get('name')}({call.get('arguments')}) -> {call.get('result')}",
                        latency_ms=call.get("latency_ms"),
                    )
                )
            events.append(
                TraceEvent(
                    case_key=case.case_key, turn=turn, kind="assistant", content=t["content"],
                    latency_ms=t.get("latency_ms"), cost_usd=t.get("cost_usd"), passed=case.passed,
                )
            )
    return events
