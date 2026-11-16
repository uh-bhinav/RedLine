import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class FailureClusterResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    cluster_label: int
    size: int
    bad_outcome_rate: float
    representative_text: str
    created_at: datetime


class CandidateCaseResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    failure_cluster_id: uuid.UUID
    case_key: str
    turns: list
    expectations: dict
    status: str
    promoted_case_id: uuid.UUID | None
    created_at: datetime
    reviewed_at: datetime | None
