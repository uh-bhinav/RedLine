"""Response models for the dashboard, auth, diff, load and mining endpoints."""
import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from apps.api.services.ars_engine import ErrorBudget
from apps.api.services.gate_engine import GateResult


# ---------- auth ----------
class RegisterRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class UserOut(BaseModel):
    id: uuid.UUID
    name: str | None
    email: str
    role: str
    tenant_id: uuid.UUID


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut


class ApiKeyCreated(BaseModel):
    id: uuid.UUID
    key: str  # raw key -- shown exactly once
    label: str | None
    created_at: datetime


class ApiKeyOut(BaseModel):
    id: uuid.UUID
    label: str | None
    masked_key: str
    created_at: datetime
    revoked: bool


# ---------- summary / agents ----------
class PlatformSummary(BaseModel):
    total_agents: int
    runs_last_7d: int
    gate_pass_rate: float | None
    healthy_budget_count: int
    total_budget_count: int


class AgentLatestRun(BaseModel):
    id: uuid.UUID
    status: str
    gate_passed: bool | None
    created_at: datetime


class AgentListItem(BaseModel):
    id: uuid.UUID
    name: str
    description: str | None
    latest_version_label: str | None
    latest_run: AgentLatestRun | None
    latest_ars: float | None
    error_budget_status: str
    created_at: datetime


class VersionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    version_label: str
    model_name: str
    content_hash: str
    entrypoint: str
    created_at: datetime


class SuiteOut(BaseModel):
    id: uuid.UUID
    agent_id: uuid.UUID
    name: str
    case_count: int


class RunListItem(BaseModel):
    id: uuid.UUID
    agent_id: uuid.UUID
    agent_name: str
    version_label: str
    suite_name: str
    status: str
    triggered_by: str
    gate_passed: bool | None
    ars: float | None
    created_at: datetime
    completed_at: datetime | None


class ARSPoint(BaseModel):
    eval_run_id: uuid.UUID
    version_label: str
    ars: float
    correctness: float
    safety: float
    latency: float
    cost: float
    created_at: datetime


class DriftAlertOut(BaseModel):
    id: uuid.UUID
    agent_id: uuid.UUID
    agent_name: str | None = None
    drift_type: str
    metric: str
    baseline_value: float
    current_value: float
    message: str
    eval_run_id: uuid.UUID | None
    diff_run_id: uuid.UUID | None
    detected_at: datetime


class LoadRunOut(BaseModel):
    id: uuid.UUID
    agent_id: uuid.UUID
    agent_name: str
    status: str
    concurrency: int
    duration_seconds: int
    p50_ms: float | None
    p95_ms: float | None
    p99_ms: float | None
    error_rate: float | None
    throughput_rps: float | None
    cost_per_hour_usd: float | None
    total_requests: int | None
    latency_series: list[dict[str, Any]] | None
    created_at: datetime


class DiffRunOut(BaseModel):
    id: uuid.UUID
    agent_id: uuid.UUID
    agent_name: str
    version_a_label: str
    version_b_label: str
    status: str
    classification: str | None
    mean_similarity: float | None
    threshold: float
    code_changed: bool | None
    created_at: datetime


class DiffCaseOut(BaseModel):
    case_key: str
    description: str | None
    similarity: float
    output_a: str
    output_b: str
    passed_a: bool
    passed_b: bool


class DiffDetail(DiffRunOut):
    cases: list[DiffCaseOut]


class AgentDetail(BaseModel):
    id: uuid.UUID
    name: str
    description: str | None
    created_at: datetime
    latest_version: VersionOut | None
    versions: list[VersionOut]
    suites: list[SuiteOut]
    recent_runs: list[RunListItem]
    latest_ars: float | None
    latest_gate: GateResult | None
    error_budget: ErrorBudget
    drift_alerts: list[DriftAlertOut]
    load_runs: list[LoadRunOut]


# ---------- run detail ----------
class CaseResultOut(BaseModel):
    id: uuid.UUID
    case_key: str
    description: str | None
    is_chaos: bool
    passed: bool
    metrics: dict[str, Any]
    transcript: list[dict[str, Any]]
    scorer_results: dict[str, Any]


class ARSBreakdown(BaseModel):
    ars: float
    correctness: float
    safety: float
    latency: float
    cost: float


class RunDetail(BaseModel):
    id: uuid.UUID
    status: str
    triggered_by: str
    agent_id: uuid.UUID
    agent_name: str
    version_label: str
    suite_name: str
    started_at: datetime | None
    completed_at: datetime | None
    created_at: datetime
    gate_result: GateResult | None
    ars: ARSBreakdown | None
    cases: list[CaseResultOut]


class TraceEvent(BaseModel):
    case_key: str
    turn: int
    kind: str  # user | assistant | tool
    name: str | None = None
    content: str
    latency_ms: int | None = None
    cost_usd: float | None = None
    passed: bool | None = None


# ---------- mining ----------
class FailureClusterOut(BaseModel):
    id: uuid.UUID
    cluster_index: int
    label: str
    representative: str
    case_count: int
    bad_outcome_rate: float
    dismissed: bool
    created_at: datetime


class CandidateOut(BaseModel):
    id: uuid.UUID
    case_key: str
    prompt: str
    status: str
    created_at: datetime


# ---------- requests ----------
class DiffCreate(BaseModel):
    agent_id: uuid.UUID
    suite_id: uuid.UUID
    version_a_id: uuid.UUID
    version_b_id: uuid.UUID
    threshold: float = Field(default=0.9, ge=0.0, le=1.0)


class LoadCreate(BaseModel):
    agent_version_id: uuid.UUID
    suite_id: uuid.UUID
    concurrency: int = Field(default=10, ge=1, le=50)
    duration_seconds: int = Field(default=20, ge=5, le=120)


class ReviewRequest(BaseModel):
    decision: str = Field(pattern="^(approve|reject)$")
