"""
CI check endpoint (Phase1 roadmap Section 12, corrected design).

This endpoint is deliberately GitHub-agnostic -- it has no idea a GitHub Action
is calling it. It just creates an EvalRun (triggered_by: "ci") and returns
immediately, the same pattern as POST /eval-runs. The CLI's ci-check command is
what talks to GitHub directly, using that job's own ambient token -- the only
thing GitHub now allows to create/update a Check Run (platform change, Feb 2025).
Nothing in the API server ever needs to know GitHub exists.
"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from apps.api.core.db import get_db
from apps.api.core.jobqueue import PostgresJobQueue
from apps.api.core.security import require_api_key
from apps.api.models import ApiKey, EvalRun
from apps.api.schemas.ci_check import CiCheckCreate, CiCheckResponse

router = APIRouter(prefix="/ci", tags=["ci"])


@router.post("/check", response_model=CiCheckResponse, status_code=201)
def create_ci_check(
    payload: CiCheckCreate,
    db: Session = Depends(get_db),
    api_key: ApiKey = Depends(require_api_key),
) -> CiCheckResponse:
    eval_run = EvalRun(
        tenant_id=api_key.tenant_id,
        agent_version_id=payload.agent_version_id,
        suite_id=payload.suite_id,
        status="pending",
        triggered_by="ci",
        git_pr_number=payload.pr_number,
    )
    db.add(eval_run)
    db.commit()
    db.refresh(eval_run)

    queue = PostgresJobQueue(db)
    queue.publish(api_key.tenant_id, "eval.requested", {"eval_run_id": str(eval_run.id)})

    return CiCheckResponse(
        eval_run_id=eval_run.id,
        status=eval_run.status,
        poll_url=f"/eval-runs/{eval_run.id}",
    )