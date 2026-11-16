import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, Float, ForeignKey, Integer, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from apps.api.core.db import Base


class FailureCluster(Base):
    """One cluster of semantically-similar assistant responses across an agent's
    eval history, found to correlate with bad outcomes (Phase 4 Section 6 --
    foundational doc §5.3: "continuously embed production traces, cluster them,
    flag clusters that correlate with bad outcomes").

    Append-only, like drift_snapshots and behavior_diffs -- each mining run is its
    own historical record. agent_id, not suite_id: mining deliberately looks across
    ALL of an agent's eval history (every suite, every version), because a failure
    mode that shows up in one suite's cases is exactly the kind of thing worth
    surfacing regardless of which suite happened to trigger it.
    """

    __tablename__ = "failure_clusters"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    agent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agents.id"), nullable=False
    )
    cluster_label: Mapped[int] = mapped_column(Integer, nullable=False)
    size: Mapped[int] = mapped_column(Integer, nullable=False)
    bad_outcome_rate: Mapped[float] = mapped_column(Float, nullable=False)
    representative_case_result_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("eval_case_results.id"), nullable=False
    )
    representative_text: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class CandidateCase(Base):
    """A regression-test case mined from a FailureCluster, awaiting human review
    before it becomes a real EvalCase. This is the closed loop the foundational
    document describes: "each significant cluster becomes a candidate regression
    test automatically" -- automatically generated, never automatically trusted.
    Approval is a deliberate, separate action (routers/mining.py), not a side
    effect of mining itself.
    """

    __tablename__ = "candidate_cases"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending','approved','rejected')",
            name="ck_candidate_cases_status",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    failure_cluster_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("failure_clusters.id"), nullable=False
    )
    source_case_result_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("eval_case_results.id"), nullable=False
    )
    case_key: Mapped[str] = mapped_column(Text, nullable=False)
    turns: Mapped[list] = mapped_column(JSONB, nullable=False)
    expectations: Mapped[dict] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="pending")
    # Set only on approval -- the real EvalCase this candidate became.
    promoted_case_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("eval_cases.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
