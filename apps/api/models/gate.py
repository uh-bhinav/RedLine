import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from apps.api.core.db import Base


class GatePolicy(Base):
    """The thresholds the Gate Engine (roadmap Section 11) reads to decide pass/block.
    One policy per agent for Phase 1 — multiple named policies per agent can come later
    without a schema rewrite (just drop the unique constraint)."""

    __tablename__ = "gate_policies"
    __table_args__ = (UniqueConstraint("agent_id", name="uq_gate_policies_agent"),)

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    agent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agents.id"), nullable=False
    )
    min_pass_rate: Mapped[float] = mapped_column(Float, nullable=False, server_default="0.9")
    max_avg_cost_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    max_avg_latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )