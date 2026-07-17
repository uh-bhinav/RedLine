import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from apps.api.core.db import Base


class DriftSnapshot(Base):
    """One scheduled drift-check run's results for one agent version + suite."""

    __tablename__ = "drift_snapshots"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    agent_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agent_versions.id"), nullable=False
    )
    suite_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("eval_suites.id"), nullable=False
    )
    eval_run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("eval_runs.id"), nullable=False
    )
    pass_rate: Mapped[float] = mapped_column(Float, nullable=False)
    total_cases: Mapped[int] = mapped_column(Integer, nullable=False)
    passed_cases: Mapped[int] = mapped_column(Integer, nullable=False)
    avg_cost_usd: Mapped[float] = mapped_column(Float, nullable=False)
    avg_latency_ms: Mapped[float] = mapped_column(Float, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class DriftAlert(Base):
    """Raised when a scheduled drift check detects a regression beyond the threshold."""

    __tablename__ = "drift_alerts"
    __table_args__ = (
        CheckConstraint("drift_type IN ('model','behavior','rag')", name="ck_drift_alerts_type"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    agent_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agent_versions.id"), nullable=False
    )
    suite_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("eval_suites.id"), nullable=False
    )
    drift_type: Mapped[str] = mapped_column(String, nullable=False)
    baseline_pass_rate: Mapped[float] = mapped_column(Float, nullable=False)
    current_pass_rate: Mapped[float] = mapped_column(Float, nullable=False)
    delta: Mapped[float] = mapped_column(Float, nullable=False)
    threshold: Mapped[float] = mapped_column(Float, nullable=False)
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )