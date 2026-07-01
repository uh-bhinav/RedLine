import uuid

from pydantic import BaseModel


class CiCheckCreate(BaseModel):
    agent_version_id: uuid.UUID
    suite_id: uuid.UUID
    pr_number: int | None = None


class CiCheckResponse(BaseModel):
    eval_run_id: uuid.UUID
    status: str
    poll_url: str