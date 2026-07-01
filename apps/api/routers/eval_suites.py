"""
Eval suite push endpoint (Phase1 roadmap Section 8, via the API).

Same upsert logic push_suite.py already proved out talking straight to the DB,
now exposed over HTTP so the CLI's `push-suite` command can call it instead of
needing direct database access (the CLI should never touch Postgres directly --
only the API server does).
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from apps.api.core.db import get_db
from apps.api.core.security import require_api_key
from apps.api.models import Agent, ApiKey, EvalCase, EvalSuite
from apps.api.schemas.eval_suite_push import EvalSuitePushResponse
from apps.api.schemas.eval_suite_yaml import EvalSuiteYAML

router = APIRouter(prefix="/eval-suites", tags=["eval-suites"])


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