"""add failure_clusters and candidate_cases

Revision ID: 0008
Revises: 0007
Create Date: 2026-07-29
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0008"
down_revision: Union[str, None] = "0007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "failure_clusters",
        sa.Column(
            "id", postgresql.UUID(as_uuid=True), primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("agent_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("agents.id"), nullable=False),
        sa.Column("cluster_label", sa.Integer(), nullable=False),
        sa.Column("size", sa.Integer(), nullable=False),
        sa.Column("bad_outcome_rate", sa.Float(), nullable=False),
        sa.Column("representative_case_result_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("eval_case_results.id"), nullable=False),
        sa.Column("representative_text", sa.Text(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index(
        "ix_failure_clusters_agent_created",
        "failure_clusters", ["agent_id", "created_at"],
    )

    op.create_table(
        "candidate_cases",
        sa.Column(
            "id", postgresql.UUID(as_uuid=True), primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("failure_cluster_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("failure_clusters.id"), nullable=False),
        sa.Column("source_case_result_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("eval_case_results.id"), nullable=False),
        sa.Column("case_key", sa.Text(), nullable=False),
        sa.Column("turns", postgresql.JSONB(), nullable=False),
        sa.Column("expectations", postgresql.JSONB(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="pending"),
        sa.Column("promoted_case_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("eval_cases.id"), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('pending','approved','rejected')",
            name="ck_candidate_cases_status",
        ),
    )
    op.create_index(
        "ix_candidate_cases_cluster",
        "candidate_cases", ["failure_cluster_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_candidate_cases_cluster", "candidate_cases")
    op.drop_table("candidate_cases")
    op.drop_index("ix_failure_clusters_agent_created", "failure_clusters")
    op.drop_table("failure_clusters")
