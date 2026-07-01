"""
Agent + AgentVersion endpoints (Phase1 roadmap Section 13 dependency).

The CLI's `init` and `register-version` commands call these directly -- this is
the real API surface that replaces what push_suite.py / register_agent_version.py
did by talking straight to the DB. Both are idempotent by design: registering the
same agent name or the same content_hash twice returns the existing row, not a
duplicate or an error.
"""
import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from apps.api.core.db import get_db
from apps.api.core.security import require_api_key
from apps.api.models import Agent, AgentVersion, ApiKey
from apps.api.schemas.agent import AgentCreate, AgentResponse, AgentVersionCreate, AgentVersionResponse

router = APIRouter(prefix="/agents", tags=["agents"])


@router.post("", response_model=AgentResponse, status_code=201)
def create_agent(
    payload: AgentCreate,
    db: Session = Depends(get_db),
    api_key: ApiKey = Depends(require_api_key),
) -> Agent:
    agent = (
        db.query(Agent)
        .filter(Agent.tenant_id == api_key.tenant_id, Agent.name == payload.name)
        .first()
    )
    if agent is not None:
        return agent  # idempotent: registering the same name twice is a no-op

    agent = Agent(tenant_id=api_key.tenant_id, name=payload.name, description=payload.description)
    db.add(agent)
    db.commit()
    db.refresh(agent)
    return agent


@router.post("/{agent_id}/versions", response_model=AgentVersionResponse, status_code=201)
def register_version(
    agent_id: uuid.UUID,
    payload: AgentVersionCreate,
    db: Session = Depends(get_db),
    api_key: ApiKey = Depends(require_api_key),
) -> AgentVersion:
    agent = db.get(Agent, agent_id)
    if agent is None or agent.tenant_id != api_key.tenant_id:
        raise HTTPException(status_code=404, detail="agent not found")

    existing = (
        db.query(AgentVersion)
        .filter(AgentVersion.agent_id == agent.id, AgentVersion.content_hash == payload.content_hash)
        .first()
    )
    if existing is not None:
        return existing  # idempotent: same content_hash twice is a no-op

    version = AgentVersion(
        agent_id=agent.id,
        version_label=payload.version_label,
        model_name=payload.model_name,
        prompt_text=payload.prompt_text,
        tool_schema=payload.tool_schema,
        content_hash=payload.content_hash,
        entrypoint=payload.entrypoint,
        git_commit_sha=payload.git_commit_sha,
    )
    db.add(version)
    db.commit()
    db.refresh(version)
    return version