import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class AgentCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)


class AgentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    description: str | None
    created_at: datetime


class AgentVersionCreate(BaseModel):
    version_label: str = Field(min_length=1, max_length=100)
    model_name: str = Field(min_length=1, max_length=200)
    prompt_text: str = Field(max_length=200_000)
    tool_schema: list[dict] = Field(default=[], max_length=200)
    content_hash: str = Field(min_length=1, max_length=128)
    entrypoint: str = Field(min_length=1, max_length=500)
    git_commit_sha: str | None = Field(default=None, max_length=64)


class AgentVersionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    agent_id: uuid.UUID
    version_label: str
    model_name: str
    content_hash: str
    entrypoint: str
    created_at: datetime