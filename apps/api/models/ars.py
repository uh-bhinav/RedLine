import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from apps.api.core.db import Base


class SLOPolicy(Base):
    """The error-budget policy the Gate Engine (Phase 4 Section 1) reads to decide
    whether an agent's deployments are frozen.

    One policy per agent, same shape as GatePolicy and for the same reason: multiple
    named policies per agent can come later without a schema rewrite.

    target_ars: the ARS score a run is expected to meet (e.g. 0.90).
    error_budget_pct: the fraction of recent runs allowed to fall below target_ars
        before the budget is considered exhausted (e.g. 0.10 = 10%). This is the SRE
        error-budget concept applied to ARS instead of uptime.
    window_days: how far back "recent runs" looks when computing the budget burn.
    """

    __tablename__ = "slo_policies"
    __table_args__ = (UniqueConstraint("agent_id", name="uq_slo_policies_agent"),)

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    agent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agents.id"), nullable=False
    )
    target_ars: Mapped[float] = mapped_column(Float, nullable=False, server_default="0.9")
    error_budget_pct: Mapped[float] = mapped_column(Float, nullable=False, server_default="0.1")
    window_days: Mapped[int] = mapped_column(Integer, nullable=False, server_default="7")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ARSSnapshot(Base):
    """One eval run's computed Agent Reliability Score and its four sub-scores.

    Stored per eval_run (not just per agent_version) so the error-budget burn-rate
    calculation in ars_engine.compute_error_budget() can walk history ordered by
    created_at without re-deriving scores from eval_case_results every time.
    """

    __tablename__ = "ars_snapshots"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    agent_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agent_versions.id"), nullable=False
    )
    eval_run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("eval_runs.id"), nullable=False, unique=True
    )
    ars: Mapped[float] = mapped_column(Float, nullable=False)
    correctness: Mapped[float] = mapped_column(Float, nullable=False)
    safety: Mapped[float] = mapped_column(Float, nullable=False)
    latency: Mapped[float] = mapped_column(Float, nullable=False)
    cost: Mapped[float] = mapped_column(Float, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
