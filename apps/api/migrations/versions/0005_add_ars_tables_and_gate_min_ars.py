"""add slo_policies, ars_snapshots, and gate_policies.min_ars

Revision ID: 0005
Revises: 0004
Create Date: 2026-07-29
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005"
down_revision: Union[str, None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "gate_policies",
        sa.Column("min_ars", sa.Float(), nullable=True),
    )

    op.create_table(
        "slo_policies",
        sa.Column(
            "id", postgresql.UUID(as_uuid=True), primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("agent_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("agents.id"), nullable=False),
        sa.Column("target_ars", sa.Float(), nullable=False, server_default="0.9"),
        sa.Column("error_budget_pct", sa.Float(), nullable=False, server_default="0.1"),
        sa.Column("window_days", sa.Integer(), nullable=False, server_default="7"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint("agent_id", name="uq_slo_policies_agent"),
    )

    op.create_table(
        "ars_snapshots",
        sa.Column(
            "id", postgresql.UUID(as_uuid=True), primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("agent_version_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("agent_versions.id"), nullable=False),
        sa.Column("eval_run_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("eval_runs.id"), nullable=False),
        sa.Column("ars", sa.Float(), nullable=False),
        sa.Column("correctness", sa.Float(), nullable=False),
        sa.Column("safety", sa.Float(), nullable=False),
        sa.Column("latency", sa.Float(), nullable=False),
        sa.Column("cost", sa.Float(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint("eval_run_id", name="uq_ars_snapshots_eval_run"),
    )
    op.create_index(
        "ix_ars_snapshots_agent_version_created",
        "ars_snapshots", ["agent_version_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_ars_snapshots_agent_version_created", "ars_snapshots")
    op.drop_table("ars_snapshots")
    op.drop_table("slo_policies")
    op.drop_column("gate_policies", "min_ars")
