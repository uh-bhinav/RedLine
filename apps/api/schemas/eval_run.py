import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from apps.api.services.gate_engine import GateResult


class EvalRunCreate(BaseModel):
    agent_version_id: uuid.UUID
    suite_id: uuid.UUID
    triggered_by: str = "manual"


class EvalRunResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    status: str
    triggered_by: str
    started_at: datetime | None
    completed_at: datetime | None
    gate_result: GateResult | None = None