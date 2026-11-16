"""Suites listing, behavioural diffs, load tests and failure mining."""
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from apps.api.core.db import get_db
from apps.api.core.jobqueue import PostgresJobQueue
from apps.api.core.security import TenantContext, require_tenant_role
from apps.api.models import (
    Agent,
    AgentVersion,
    CandidateCase,
    DiffCaseResult,
    DiffRun,
    EvalCase,
    EvalRun,
    EvalSuite,
    FailureCluster,
    LoadRun,
)
from apps.api.routers.dashboard import load_run_out
from apps.api.schemas.dashboard import (
    CandidateOut,
    DiffCreate,
    DiffDetail,
    DiffRunOut,
    DiffCaseOut,
    FailureClusterOut,
    LoadCreate,
    LoadRunOut,
    ReviewRequest,
    SuiteOut,
)
from apps.api.services import diff_engine, mining_engine

router = APIRouter(tags=["analytics"])
Viewer = Depends(require_tenant_role("viewer"))
Developer = Depends(require_tenant_role("developer"))


def _agent_or_404(db: Session, ctx: TenantContext, agent_id: uuid.UUID) -> Agent:
    agent = db.get(Agent, agent_id)
    if agent is None or agent.tenant_id != ctx.tenant_id:
        raise HTTPException(status_code=404, detail="agent not found")
    return agent


def _version_or_404(db: Session, ctx: TenantContext, version_id: uuid.UUID) -> tuple[AgentVersion, Agent]:
    version = db.get(AgentVersion, version_id)
    agent = db.get(Agent, version.agent_id) if version else None
    if version is None or agent is None or agent.tenant_id != ctx.tenant_id:
        raise HTTPException(status_code=404, detail="agent version not found")
    return version, agent


def _suite_or_404(db: Session, agent: Agent, suite_id: uuid.UUID) -> EvalSuite:
    suite = db.get(EvalSuite, suite_id)
    if suite is None or suite.agent_id != agent.id:
        raise HTTPException(status_code=404, detail="suite not found for this agent")
    return suite


# ---------------- suites ----------------
@router.get("/eval-suites", response_model=list[SuiteOut])
def list_suites(
    agent_id: uuid.UUID | None = Query(default=None),
    ctx: TenantContext = Viewer,
    db: Session = Depends(get_db),
) -> list[SuiteOut]:
    q = db.query(EvalSuite).join(Agent, Agent.id == EvalSuite.agent_id).filter(Agent.tenant_id == ctx.tenant_id)
    if agent_id:
        q = q.filter(EvalSuite.agent_id == agent_id)
    return [
        SuiteOut(
            id=s.id, agent_id=s.agent_id, name=s.name,
            case_count=db.query(EvalCase).filter(EvalCase.suite_id == s.id).count(),
        )
        for s in q.all()
    ]


# ---------------- diffs ----------------
def _diff_out(db: Session, diff: DiffRun) -> DiffRunOut:
    agent = db.get(Agent, diff.agent_id)
    run_a, run_b = db.get(EvalRun, diff.run_a_id), db.get(EvalRun, diff.run_b_id)
    ver_a, ver_b = db.get(AgentVersion, run_a.agent_version_id), db.get(AgentVersion, run_b.agent_version_id)
    return DiffRunOut(
        id=diff.id, agent_id=agent.id, agent_name=agent.name,
        version_a_label=ver_a.version_label, version_b_label=ver_b.version_label,
        status=diff.status, classification=diff.classification,
        mean_similarity=diff.mean_similarity, threshold=diff.threshold,
        code_changed=diff.code_changed, created_at=diff.created_at,
    )


@router.post("/diffs", response_model=DiffRunOut, status_code=201)
def create_diff(payload: DiffCreate, ctx: TenantContext = Developer, db: Session = Depends(get_db)) -> DiffRunOut:
    agent = _agent_or_404(db, ctx, payload.agent_id)
    suite = _suite_or_404(db, agent, payload.suite_id)
    ver_a, _ = _version_or_404(db, ctx, payload.version_a_id)
    ver_b, _ = _version_or_404(db, ctx, payload.version_b_id)

    def pick(version: AgentVersion, force_new: bool) -> EvalRun:
        existing = None if force_new else diff_engine.latest_completed_run(db, version.id, suite.id)
        if existing:
            return existing
        run = EvalRun(
            tenant_id=ctx.tenant_id, agent_version_id=version.id, suite_id=suite.id,
            status="pending", triggered_by="manual",
        )
        db.add(run)
        db.flush()
        return run

    run_a = pick(ver_a, force_new=False)
    run_b = pick(ver_b, force_new=ver_a.id == ver_b.id)  # same version twice => a genuine re-run
    diff = DiffRun(
        tenant_id=ctx.tenant_id, agent_id=agent.id, suite_id=suite.id,
        run_a_id=run_a.id, run_b_id=run_b.id, threshold=payload.threshold,
    )
    db.add(diff)
    db.commit()
    db.refresh(diff)
    PostgresJobQueue(db).publish(ctx.tenant_id, "diff.requested", {"diff_run_id": str(diff.id)})
    return _diff_out(db, diff)


@router.get("/diffs", response_model=list[DiffRunOut])
def list_diffs(ctx: TenantContext = Viewer, db: Session = Depends(get_db)) -> list[DiffRunOut]:
    rows = db.query(DiffRun).filter(DiffRun.tenant_id == ctx.tenant_id).order_by(DiffRun.created_at.desc()).limit(100).all()
    return [_diff_out(db, d) for d in rows]


@router.get("/diffs/{diff_id}", response_model=DiffDetail)
def get_diff(diff_id: uuid.UUID, ctx: TenantContext = Viewer, db: Session = Depends(get_db)) -> DiffDetail:
    diff = db.get(DiffRun, diff_id)
    if diff is None or diff.tenant_id != ctx.tenant_id:
        raise HTTPException(status_code=404, detail="diff not found")
    cases = {c.id: c for c in db.query(EvalCase).filter(EvalCase.suite_id == diff.suite_id)}
    results = db.query(DiffCaseResult).filter(DiffCaseResult.diff_run_id == diff.id).all()
    return DiffDetail(
        **_diff_out(db, diff).model_dump(),
        cases=[
            DiffCaseOut(
                case_key=cases[r.case_id].case_key, description=cases[r.case_id].description,
                similarity=r.similarity, output_a=r.output_a, output_b=r.output_b,
                passed_a=r.passed_a, passed_b=r.passed_b,
            )
            for r in sorted(results, key=lambda r: r.similarity)
            if r.case_id in cases
        ],
    )


# ---------------- load tests ----------------
@router.post("/load-runs", response_model=LoadRunOut, status_code=201)
def create_load_run(payload: LoadCreate, ctx: TenantContext = Developer, db: Session = Depends(get_db)) -> LoadRunOut:
    version, agent = _version_or_404(db, ctx, payload.agent_version_id)
    _suite_or_404(db, agent, payload.suite_id)
    load = LoadRun(
        tenant_id=ctx.tenant_id, agent_version_id=version.id, suite_id=payload.suite_id,
        concurrency=payload.concurrency, duration_seconds=payload.duration_seconds,
    )
    db.add(load)
    db.commit()
    db.refresh(load)
    PostgresJobQueue(db).publish(ctx.tenant_id, "load.requested", {"load_run_id": str(load.id)})
    return load_run_out(load, db)


@router.get("/load-runs", response_model=list[LoadRunOut])
def list_load_runs(
    agent_id: uuid.UUID | None = Query(default=None),
    ctx: TenantContext = Viewer,
    db: Session = Depends(get_db),
) -> list[LoadRunOut]:
    q = db.query(LoadRun).filter(LoadRun.tenant_id == ctx.tenant_id)
    if agent_id:
        q = q.join(AgentVersion, AgentVersion.id == LoadRun.agent_version_id).filter(AgentVersion.agent_id == agent_id)
    return [load_run_out(load, db) for load in q.order_by(LoadRun.created_at.desc()).limit(100).all()]


@router.get("/load-runs/{load_id}", response_model=LoadRunOut)
def get_load_run(load_id: uuid.UUID, ctx: TenantContext = Viewer, db: Session = Depends(get_db)) -> LoadRunOut:
    load = db.get(LoadRun, load_id)
    if load is None or load.tenant_id != ctx.tenant_id:
        raise HTTPException(status_code=404, detail="load run not found")
    return load_run_out(load, db)


# ---------------- failure mining ----------------
@router.post("/mining/{agent_id}/run", response_model=list[FailureClusterOut])
def run_mining(agent_id: uuid.UUID, ctx: TenantContext = Developer, db: Session = Depends(get_db)):
    _agent_or_404(db, ctx, agent_id)
    return mining_engine.mine(db, agent_id)


@router.get("/mining/{agent_id}/clusters", response_model=list[FailureClusterOut])
def list_clusters(agent_id: uuid.UUID, ctx: TenantContext = Viewer, db: Session = Depends(get_db)):
    _agent_or_404(db, ctx, agent_id)
    return (
        db.query(FailureCluster)
        .filter(FailureCluster.agent_id == agent_id, FailureCluster.dismissed.is_(False))
        .order_by(FailureCluster.bad_outcome_rate.desc(), FailureCluster.case_count.desc())
        .all()
    )


@router.post("/mining/clusters/{cluster_id}/dismiss", status_code=204)
def dismiss_cluster(cluster_id: uuid.UUID, ctx: TenantContext = Developer, db: Session = Depends(get_db)) -> None:
    cluster = db.get(FailureCluster, cluster_id)
    if cluster is None:
        raise HTTPException(status_code=404, detail="cluster not found")
    _agent_or_404(db, ctx, cluster.agent_id)
    cluster.dismissed = True
    db.commit()


@router.get("/mining/{agent_id}/candidates", response_model=list[CandidateOut])
def list_candidates(agent_id: uuid.UUID, ctx: TenantContext = Viewer, db: Session = Depends(get_db)):
    _agent_or_404(db, ctx, agent_id)
    return (
        db.query(CandidateCase)
        .filter(CandidateCase.agent_id == agent_id, CandidateCase.status == "pending")
        .order_by(CandidateCase.created_at.desc())
        .all()
    )


@router.post("/mining/candidates/{candidate_id}/review", response_model=CandidateOut)
def review_candidate(
    candidate_id: uuid.UUID, payload: ReviewRequest,
    ctx: TenantContext = Developer, db: Session = Depends(get_db),
):
    cand = db.get(CandidateCase, candidate_id)
    if cand is None:
        raise HTTPException(status_code=404, detail="candidate not found")
    _agent_or_404(db, ctx, cand.agent_id)
    cand.status = "approved" if payload.decision == "approve" else "rejected"
    db.commit()
    db.refresh(cand)
    return cand
