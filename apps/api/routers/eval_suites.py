"""
Eval suite push endpoint (Phase1 roadmap Section 8, via the API).

Same upsert logic push_suite.py already proved out talking straight to the DB,
now exposed over HTTP so the CLI's `push-suite` command can call it instead of
needing direct database access (the CLI should never touch Postgres directly --
only the API server does).
"""
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from apps.api.core.db import get_db
from apps.api.core.security import require_api_key
from apps.api.models import Agent, ApiKey, EvalCase, EvalSuite
from apps.api.schemas.eval_suite_push import EvalSuitePushResponse
from apps.api.schemas.eval_suite_yaml import EvalSuiteYAML

router = APIRouter(prefix="/eval-suites", tags=["eval-suites"])


class EvalSuiteSummary(BaseModel):
    id: uuid.UUID
    agent_id: uuid.UUID
    name: str
    case_count: int
    created_at: datetime


@router.post("", response_model=EvalSuitePushResponse, status_code=200)
def push_suite(
    payload: EvalSuiteYAML,
    db: Session = Depends(get_db),
    api_key: ApiKey = Depends(require_api_key),
) -> EvalSuitePushResponse:
    agent = (
        db.query(Agent)
        .filter(Agent.tenant_id == api_key.tenant_id, Agent.name == payload.agent)
        .first()
    )
    if agent is None:
        raise HTTPException(
            status_code=404,
            detail=f"agent '{payload.agent}' not found -- create it first via POST /agents",
        )

    suite = (
        db.query(EvalSuite)
        .filter(EvalSuite.agent_id == agent.id, EvalSuite.name == payload.suite)
        .first()
    )
    created_suite = suite is None
    if suite is None:
        suite = EvalSuite(agent_id=agent.id, name=payload.suite)
        db.add(suite)
        db.flush()

    added, updated = 0, 0
    for case_def in payload.cases:
        case = (
            db.query(EvalCase)
            .filter(EvalCase.suite_id == suite.id, EvalCase.case_key == case_def.case_key)
            .first()
        )
        turns_data = [t.model_dump() for t in case_def.turns]
        expectations_data = case_def.expectations.model_dump(exclude_none=True)

        if case is None:
            db.add(
                EvalCase(
                    suite_id=suite.id,
                    case_key=case_def.case_key,
                    description=case_def.description,
                    turns=turns_data,
                    expectations=expectations_data,
                )
            )
            added += 1
        else:
            case.description = case_def.description
            case.turns = turns_data
            case.expectations = expectations_data
            updated += 1

    db.commit()
    return EvalSuitePushResponse(
        suite_id=suite.id, created_suite=created_suite, cases_added=added, cases_updated=updated
    )


@router.get("", response_model=list[EvalSuiteSummary])
def list_eval_suites(
    agent_id: uuid.UUID,
    db: Session = Depends(get_db),
    api_key: ApiKey = Depends(require_api_key),
) -> list[EvalSuiteSummary]:
    """Phase 5.3 (dashboard v2) -- lets the frontend populate a suite picker when
    triggering an eval/diff/load/mining run. Only POST existed before this."""
    agent = db.get(Agent, agent_id)
    if agent is None or agent.tenant_id != api_key.tenant_id:
        # 404, not 403 -- same "don't confirm existence" discipline as
        # dashboard.py's _owned_agent().
        raise HTTPException(status_code=404, detail="agent not found")

    suites = db.query(EvalSuite).filter(EvalSuite.agent_id == agent.id).all()
    counts = dict(
        db.query(EvalCase.suite_id, func.count(EvalCase.id))
        .filter(EvalCase.suite_id.in_([s.id for s in suites]))
        .group_by(EvalCase.suite_id)
        .all()
    )

    return [
        EvalSuiteSummary(
            id=s.id,
            agent_id=s.agent_id,
            name=s.name,
            case_count=counts.get(s.id, 0),
            created_at=s.created_at,
        )
        for s in suites
    ]