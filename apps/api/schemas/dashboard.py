import uuid
from datetime import datetime
from typing import Literal

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
    error: str | None = None


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
    # Phase 5.3 (dashboard v2) -- the full turn-by-turn transcript, previously
    # stored (EvalCaseResult.transcript) but never returned by any endpoint.
    # Run detail already loads every EvalCaseResult in one query, so exposing
    # it here avoids an N+1 per-case fetch a separate endpoint would require.
    transcript: list[dict]
    # True if any turn's tool_calls carry the chaos-fault marker
    # (has_chaos_marker() from adapters/chaos_adapter.py). Computed here, not
    # stored -- there is no dedicated chaos dataset, only a marker inside
    # transcripts that already exist.
    is_chaos_case: bool


class RunDetailResponse(BaseModel):
    id: uuid.UUID
    status: str
    triggered_by: str
    gate_result: GateResult | None
    started_at: datetime | None
    completed_at: datetime | None
    error: str | None = None
    case_results: list[CaseResultItem]


class ArsSnapshotItem(BaseModel):
    """One point on the ARS trend chart."""

    id: uuid.UUID
    agent_version_id: uuid.UUID
    version_label: str
    eval_run_id: uuid.UUID
    ars: float
    correctness: float
    safety: float
    latency: float
    cost: float
    created_at: datetime


class ErrorBudgetResponse(BaseModel):
    """Mirrors ars_engine.ErrorBudgetResult field-for-field."""

    exhausted: bool
    target_ars: float
    error_budget_pct: float
    window_size: int
    breaches: int
    breach_rate: float
    budget_remaining_pct: float
    detail: str


class DriftAlertItem(BaseModel):
    """Normalizes DriftAlert (model drift, pass-rate based) and BehaviorDiff
    rows classified 'silent_drift' (behavior drift, similarity based) into one
    shape -- these live in two different tables today, for good reason (see
    BehaviorDiff's own docstring), but the dashboard's alerts list is one feed."""

    id: uuid.UUID
    drift_type: Literal["model", "behavior"]
    agent_version_id: uuid.UUID
    suite_id: uuid.UUID
    metric_label: Literal["pass_rate", "similarity"]
    baseline_value: float
    current_value: float
    delta: float
    threshold: float
    detail: str
    created_at: datetime


class LoadRunSummary(BaseModel):
    """Trimmed LoadRunResponse for the agent detail page's Load Tests tab."""

    id: uuid.UUID
    status: str
    triggered_by: str
    concurrency: int
    duration_seconds: int
    p95_latency_ms: float | None
    error_rate: float | None
    cost_per_hour_usd: float | None
    started_at: datetime | None
    completed_at: datetime | None


class TraceEventItem(BaseModel):
    """One row from ClickHouse's traces table."""

    trace_id: uuid.UUID
    event_type: str
    case_key: str
    turn_index: int
    latency_ms: int
    cost_usd: float
    passed: bool | None
    detail: str
    created_at: datetime