import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from apps.api.services.gate_engine import GateResult


class AgentLatestRun(BaseModel):
    """Minimal run summary for the agents list page."""

    id: uuid.UUID
    status: str
    gate_passed: bool | None
    completed_at: datetime | None


class AgentListItem(BaseModel):
    """One row in the agents list table."""

    id: uuid.UUID
    name: str
    description: str | None
    latest_version_label: str | None
    latest_run: AgentLatestRun | None
    created_at: datetime


class AgentVersionSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    version_label: str
    model_name: str
    content_hash: str
    entrypoint: str
    created_at: datetime


class EvalRunSummary(BaseModel):
    """One row in the runs list on the agent detail page."""

    id: uuid.UUID
    status: str
    triggered_by: str
    gate_result: GateResult | None
    started_at: datetime | None
    completed_at: datetime | None


class AgentDetailResponse(BaseModel):
    id: uuid.UUID
    name: str
    description: str | None
    created_at: datetime
    versions: list[AgentVersionSummary]
    recent_runs: list[EvalRunSummary]


class CaseResultItem(BaseModel):
    """One row in the per-case results table on the run detail page."""

    case_id: uuid.UUID
    case_key: str
    passed: bool
    cost_usd: float
    latency_ms: int
    scorer_results: dict


class RunDetailResponse(BaseModel):
    id: uuid.UUID
    status: str
    triggered_by: str
    gate_result: GateResult | None
    started_at: datetime | None
    completed_at: datetime | None
    case_results: list[CaseResultItem]