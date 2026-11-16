"""
Behavioral diff endpoints (Phase 4 Section 2).

Owned by eval_service, same as /eval-runs -- diffing is eval-logic territory (it
reads eval_case_results and calls an embedding model), not agent-registry or
gate-policy territory. See .claude/rules/architecture.md's route-ownership table.

POST /diff-runs computes synchronously (an embedding call per shared case, typically
a handful of cases -- not the multi-minute eval runs that justify being async) and
returns the result immediately, matching rule #1's synchronous model.
"""
import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from apps.api.core.db import get_db
from apps.api.core.security import TenantContext, get_tenant_context, require_tenant_role
from apps.api.models import Agent, AgentVersion, BehaviorDiff, EvalSuite
from apps.api.schemas.diff import DiffRunCreate, DiffRunResponse
from apps.api.services.diff_engine import DiffEngineError, compute_diff_for_versions

router = APIRouter(prefix="/diff-runs", tags=["diff"])


def _diff_context(diff: BehaviorDiff, db: Session) -> dict:
    """Agent name + version A/B labels + suite name for a stored diff row."""
    agent = db.get(Agent, diff.agent_id)
    va = db.get(AgentVersion, diff.version_a_id)
    vb = db.get(AgentVersion, diff.version_b_id)
    suite = db.get(EvalSuite, diff.suite_id)
    return dict(
        agent_id=diff.agent_id,
        agent_name=agent.name if agent else None,
        version_a_id=diff.version_a_id,
        version_b_id=diff.version_b_id,
        version_a_label=va.version_label if va else None,
        version_b_label=vb.version_label if vb else None,
        suite_id=diff.suite_id,
        suite_name=suite.name if suite else None,
        created_at=diff.created_at,
    )


def _owned_version(version_id: uuid.UUID, tenant_id: uuid.UUID, db: Session) -> AgentVersion:
    version = db.get(AgentVersion, version_id)
    if version is None:
        raise HTTPException(status_code=404, detail=f"agent version {version_id} not found")
    agent = db.get(Agent, version.agent_id)
    if agent is None or agent.tenant_id != tenant_id:
        raise HTTPException(status_code=404, detail=f"agent version {version_id} not found")
    return version


@router.post("", response_model=DiffRunResponse, status_code=201)
def create_diff_run(
    payload: DiffRunCreate,
    ctx: TenantContext = Depends(require_tenant_role("admin", "developer")),
    db: Session = Depends(get_db),
) -> DiffRunResponse:
    _owned_version(payload.version_a_id, ctx.tenant_id, db)
    _owned_version(payload.version_b_id, ctx.tenant_id, db)

    try:
        result = compute_diff_for_versions(
            payload.version_a_id, payload.version_b_id, payload.suite_id
        )
    except DiffEngineError as e:
        raise HTTPException(status_code=422, detail=str(e))

    # id/eval_run_a_id/eval_run_b_id are always set on this path -- compute_diff()
    # (which compute_diff_for_versions() delegates to) populates them after
    # persisting, unconditionally. Only the pure _classify_diff() ever leaves
    # them None, and that function is never called on this DB-backed path.
    assert result.id is not None
    assert result.eval_run_a_id is not None
    assert result.eval_run_b_id is not None

    stored = db.get(BehaviorDiff, result.id)
    extra = _diff_context(stored, db) if stored is not None else {}

    return DiffRunResponse(
        id=result.id,
        classification=result.classification.value,
        code_changed=result.code_changed,
        behavior_changed=result.behavior_changed,
        mean_similarity=result.mean_similarity,
        threshold=result.threshold,
        per_case_similarity=result.per_case_similarity,
        detail=result.detail,
        eval_run_a_id=result.eval_run_a_id,
        eval_run_b_id=result.eval_run_b_id,
        **extra,
    )


@router.get("/{diff_id}", response_model=DiffRunResponse)
def get_diff_run(
    diff_id: uuid.UUID,
    ctx: TenantContext = Depends(get_tenant_context),
    db: Session = Depends(get_db),
) -> DiffRunResponse:
    diff = db.get(BehaviorDiff, diff_id)
    if diff is None:
        raise HTTPException(status_code=404, detail="diff run not found")
    agent = db.get(Agent, diff.agent_id)
    if agent is None or agent.tenant_id != ctx.tenant_id:
        raise HTTPException(status_code=404, detail="diff run not found")

    return DiffRunResponse(
        id=diff.id,
        classification=diff.classification,
        code_changed=diff.code_changed,
        behavior_changed=diff.behavior_changed,
        mean_similarity=diff.mean_similarity,
        threshold=diff.similarity_threshold,
        per_case_similarity=diff.per_case_similarity,
        detail=diff.detail,
        eval_run_a_id=diff.eval_run_a_id,
        eval_run_b_id=diff.eval_run_b_id,
        **_diff_context(diff, db),
    )
