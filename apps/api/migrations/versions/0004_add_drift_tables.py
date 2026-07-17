"""add drift_snapshots and drift_alerts

Revision ID: 0004
Revises: 0003
Create Date: 2026-07-17
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "drift_snapshots",
        sa.Column(
            "id", postgresql.UUID(as_uuid=True), primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("agent_version_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("agent_versions.id"), nullable=False),
        sa.Column("suite_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("eval_suites.id"), nullable=False),
        sa.Column("eval_run_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("eval_runs.id"), nullable=False),
        sa.Column("pass_rate", sa.Float(), nullable=False),
        sa.Column("total_cases", sa.Integer(), nullable=False),
        sa.Column("passed_cases", sa.Integer(), nullable=False),
        sa.Column("avg_cost_usd", sa.Float(), nullable=False),
        sa.Column("avg_latency_ms", sa.Float(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index(
        "ix_drift_snapshots_agent_version",
        "drift_snapshots", ["agent_version_id", "created_at"],
    )

    op.create_table(
        "drift_alerts",
        sa.Column(
            "id", postgresql.UUID(as_uuid=True), primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("agent_version_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("agent_versions.id"), nullable=False),
        sa.Column("suite_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("eval_suites.id"), nullable=False),
        sa.Column("drift_type", sa.Text(), nullable=False),
        sa.Column("baseline_pass_rate", sa.Float(), nullable=False),
        sa.Column("current_pass_rate", sa.Float(), nullable=False),
        sa.Column("delta", sa.Float(), nullable=False),
        sa.Column("threshold", sa.Float(), nullable=False),
        sa.Column("detail", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "drift_type IN ('model','behavior','rag')",
            name="ck_drift_alerts_type",
        ),
    )


def downgrade() -> None:
    op.drop_table("drift_alerts")
    op.drop_index("ix_drift_snapshots_agent_version", "drift_snapshots")
    op.drop_table("drift_snapshots")