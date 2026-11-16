"""add load_runs

Revision ID: 0007
Revises: 0006
Create Date: 2026-07-29
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0007"
down_revision: Union[str, None] = "0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "load_runs",
        sa.Column(
            "id", postgresql.UUID(as_uuid=True), primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("agent_version_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("agent_versions.id"), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("concurrency", sa.Integer(), nullable=False),
        sa.Column("duration_seconds", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="pending"),
        sa.Column("triggered_by", sa.String(), nullable=False, server_default="manual"),
        sa.Column("total_requests", sa.Integer(), nullable=True),
        sa.Column("successful_requests", sa.Integer(), nullable=True),
        sa.Column("p50_latency_ms", sa.Float(), nullable=True),
        sa.Column("p95_latency_ms", sa.Float(), nullable=True),
        sa.Column("p99_latency_ms", sa.Float(), nullable=True),
        sa.Column("error_rate", sa.Float(), nullable=True),
        sa.Column("total_cost_usd", sa.Float(), nullable=True),
        sa.Column("cost_per_hour_usd", sa.Float(), nullable=True),
        sa.Column("throughput_rps", sa.Float(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "status IN ('pending','running','completed','failed')",
            name="ck_load_runs_status",
        ),
    )
    op.create_index(
        "ix_load_runs_tenant_created",
        "load_runs", ["tenant_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_load_runs_tenant_created", "load_runs")
    op.drop_table("load_runs")
