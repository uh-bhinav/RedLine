"""Reliability-analytics tables used by the dashboard: ARS snapshots, drift alerts,
behavioural diffs, load tests and failure mining."""
import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from apps.api.core.db import Base


def _pk() -> Mapped[uuid.UUID]:
    return mapped_column(UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())


def _fk(table: str, nullable: bool = False) -> Mapped[uuid.UUID]:
    return mapped_column(UUID(as_uuid=True), ForeignKey(f"{table}.id"), nullable=nullable)


def _ts() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class ARSSnapshot(Base):
    """Agent Reliability Score for one completed eval run (composite + 4 components)."""

    __tablename__ = "ars_snapshots"

    id: Mapped[uuid.UUID] = _pk()
    agent_version_id: Mapped[uuid.UUID] = _fk("agent_versions")
    eval_run_id: Mapped[uuid.UUID] = _fk("eval_runs")
    ars: Mapped[float] = mapped_column(Float, nullable=False)
    correctness: Mapped[float] = mapped_column(Float, nullable=False)
    safety: Mapped[float] = mapped_column(Float, nullable=False)
    latency: Mapped[float] = mapped_column(Float, nullable=False)
    cost: Mapped[float] = mapped_column(Float, nullable=False)
    created_at: Mapped[datetime] = _ts()


class DriftAlert(Base):
    __tablename__ = "drift_alerts"

    id: Mapped[uuid.UUID] = _pk()
    agent_id: Mapped[uuid.UUID] = _fk("agents")
    drift_type: Mapped[str] = mapped_column(String, nullable=False)  # model | prompt | metric
    metric: Mapped[str] = mapped_column(String, nullable=False)
    baseline_value: Mapped[float] = mapped_column(Float, nullable=False)
    current_value: Mapped[float] = mapped_column(Float, nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    eval_run_id: Mapped[uuid.UUID | None] = _fk("eval_runs", nullable=True)
    diff_run_id: Mapped[uuid.UUID | None] = _fk("diff_runs", nullable=True)
    detected_at: Mapped[datetime] = _ts()


class DiffRun(Base):
    """Behavioural diff between two eval runs (version A vs version B) of the same suite."""

    __tablename__ = "diff_runs"

    id: Mapped[uuid.UUID] = _pk()
    tenant_id: Mapped[uuid.UUID] = _fk("tenants")
    agent_id: Mapped[uuid.UUID] = _fk("agents")
    suite_id: Mapped[uuid.UUID] = _fk("eval_suites")
    run_a_id: Mapped[uuid.UUID] = _fk("eval_runs")
    run_b_id: Mapped[uuid.UUID] = _fk("eval_runs")
    status: Mapped[str] = mapped_column(String, nullable=False, server_default="pending")
    classification: Mapped[str | None] = mapped_column(String, nullable=True)
    mean_similarity: Mapped[float | None] = mapped_column(Float, nullable=True)
    threshold: Mapped[float] = mapped_column(Float, nullable=False, server_default="0.9")
    code_changed: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    created_at: Mapped[datetime] = _ts()
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class DiffCaseResult(Base):
    __tablename__ = "diff_case_results"

    id: Mapped[uuid.UUID] = _pk()
    diff_run_id: Mapped[uuid.UUID] = _fk("diff_runs")
    case_id: Mapped[uuid.UUID] = _fk("eval_cases")
    similarity: Mapped[float] = mapped_column(Float, nullable=False)
    output_a: Mapped[str] = mapped_column(Text, nullable=False)
    output_b: Mapped[str] = mapped_column(Text, nullable=False)
    passed_a: Mapped[bool] = mapped_column(Boolean, nullable=False)
    passed_b: Mapped[bool] = mapped_column(Boolean, nullable=False)


class LoadRun(Base):
    __tablename__ = "load_runs"

    id: Mapped[uuid.UUID] = _pk()
    tenant_id: Mapped[uuid.UUID] = _fk("tenants")
    agent_version_id: Mapped[uuid.UUID] = _fk("agent_versions")
    suite_id: Mapped[uuid.UUID] = _fk("eval_suites")
    concurrency: Mapped[int] = mapped_column(Integer, nullable=False)
    duration_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, server_default="pending")
    p50_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    p95_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    p99_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    error_rate: Mapped[float | None] = mapped_column(Float, nullable=True)
    throughput_rps: Mapped[float | None] = mapped_column(Float, nullable=True)
    cost_per_hour_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    total_requests: Mapped[int | None] = mapped_column(Integer, nullable=True)
    latency_series: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = _ts()
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class FailureCluster(Base):
    __tablename__ = "failure_clusters"

    id: Mapped[uuid.UUID] = _pk()
    agent_id: Mapped[uuid.UUID] = _fk("agents")
    cluster_index: Mapped[int] = mapped_column(Integer, nullable=False)
    label: Mapped[str] = mapped_column(Text, nullable=False)
    representative: Mapped[str] = mapped_column(Text, nullable=False)
    case_count: Mapped[int] = mapped_column(Integer, nullable=False)
    bad_outcome_rate: Mapped[float] = mapped_column(Float, nullable=False)
    dismissed: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    created_at: Mapped[datetime] = _ts()


class CandidateCase(Base):
    """A mined failing input proposed for promotion into the eval suite (human review)."""

    __tablename__ = "candidate_cases"

    id: Mapped[uuid.UUID] = _pk()
    agent_id: Mapped[uuid.UUID] = _fk("agents")
    cluster_id: Mapped[uuid.UUID | None] = _fk("failure_clusters", nullable=True)
    case_key: Mapped[str] = mapped_column(String, nullable=False)
    prompt: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, server_default="pending")
    created_at: Mapped[datetime] = _ts()
