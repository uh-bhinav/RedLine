import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class LoadRunCreate(BaseModel):
    agent_version_id: uuid.UUID
    message: str
    concurrency: int = Field(gt=0, le=1000)
    duration_seconds: int = Field(gt=0, le=3600)
    triggered_by: str = "manual"


class LoadRunResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    status: str
    triggered_by: str
    concurrency: int
    duration_seconds: int
    started_at: datetime | None
    completed_at: datetime | None
    total_requests: int | None
    successful_requests: int | None
    error_rate: float | None
    p50_latency_ms: float | None
    p95_latency_ms: float | None
    p99_latency_ms: float | None
    total_cost_usd: float | None
    cost_per_hour_usd: float | None
    throughput_rps: float | None
    error: str | None
