import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from apps.api.core.db import Base


class LoadRun(Base):
    """One load test: N concurrent simulated users repeatedly calling an agent
    version with a fixed message for a fixed duration (Phase 4 Section 5 --
    foundational doc §5.5).

    Deliberately separate from EvalRun/EvalCaseResult: load testing answers "how
    does this agent behave under concurrency" (throughput, latency percentiles,
    cost at scale), not "is this response correct" -- conflating the two would mean
    reusing eval-suite semantics (cases, expectations, scorers) for a concern that
    has none of those. The raw per-request samples live in ClickHouse
    (load_samples); this row holds the run's configuration and the computed
    aggregate result -- same split as EvalRun (Postgres metadata) vs. traces
    (ClickHouse per-turn events).
    """

    __tablename__ = "load_runs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending','running','completed','failed')",
            name="ck_load_runs_status",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False
    )
    agent_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agent_versions.id"), nullable=False
    )
    message: Mapped[str] = mapped_column(Text, nullable=False)
    concurrency: Mapped[int] = mapped_column(Integer, nullable=False)
    duration_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, server_default="pending")
    triggered_by: Mapped[str] = mapped_column(String, nullable=False, server_default="manual")

    # Aggregate result -- null until the run completes.
    total_requests: Mapped[int | None] = mapped_column(Integer, nullable=True)
    successful_requests: Mapped[int | None] = mapped_column(Integer, nullable=True)
    p50_latency_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    p95_latency_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    p99_latency_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    error_rate: Mapped[float | None] = mapped_column(Float, nullable=True)
    total_cost_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    cost_per_hour_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    throughput_rps: Mapped[float | None] = mapped_column(Float, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
