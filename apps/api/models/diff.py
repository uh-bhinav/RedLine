import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, Float, ForeignKey, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from apps.api.core.db import Base


class BehaviorDiff(Base):
    """One comparison between two agent versions' observed behavior on a shared
    suite (Phase 4 Section 2 -- foundational doc §5.2).

    Append-only, like drift_snapshots -- each computation is its own historical
    record, not upserted, since re-diffing the same version pair after either one
    gets a fresh eval run is a meaningful new data point, not a correction of the
    old one.

    Deliberately does NOT reuse drift_alerts. drift_alerts's columns
    (baseline_pass_rate, current_pass_rate, delta) are shaped for a pass-rate
    comparison, which is model drift's language, not behavioral similarity's. A
    'silent_drift' classification on THIS table already is the alert -- there is no
    second table to also write to. drift_alerts stays exclusively about pass-rate
    deltas (model drift).
    """

    __tablename__ = "behavior_diffs"
    __table_args__ = (
        CheckConstraint(
            "classification IN "
            "('no_op','safe_refactor','expected_change','silent_drift','insufficient_data')",
            name="ck_behavior_diffs_classification",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    agent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agents.id"), nullable=False
    )
    version_a_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agent_versions.id"), nullable=False
    )
    version_b_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agent_versions.id"), nullable=False
    )
    suite_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("eval_suites.id"), nullable=False
    )
    eval_run_a_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("eval_runs.id"), nullable=False
    )
    eval_run_b_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("eval_runs.id"), nullable=False
    )
    code_changed: Mapped[bool] = mapped_column(nullable=False)
    behavior_changed: Mapped[bool] = mapped_column(nullable=False)
    mean_similarity: Mapped[float] = mapped_column(Float, nullable=False)
    similarity_threshold: Mapped[float] = mapped_column(Float, nullable=False)
    classification: Mapped[str] = mapped_column(Text, nullable=False)
    # {case_key: cosine_similarity} -- only for case_keys present in both runs.
    per_case_similarity: Mapped[dict] = mapped_column(JSONB, nullable=False)
    detail: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
