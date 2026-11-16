"""add behavior_diffs

Revision ID: 0006
Revises: 0005
Create Date: 2026-07-29
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0006"
down_revision: Union[str, None] = "0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "behavior_diffs",
        sa.Column(
            "id", postgresql.UUID(as_uuid=True), primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("agent_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("agents.id"), nullable=False),
        sa.Column("version_a_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("agent_versions.id"), nullable=False),
        sa.Column("version_b_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("agent_versions.id"), nullable=False),
        sa.Column("suite_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("eval_suites.id"), nullable=False),
        sa.Column("eval_run_a_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("eval_runs.id"), nullable=False),
        sa.Column("eval_run_b_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("eval_runs.id"), nullable=False),
        sa.Column("code_changed", sa.Boolean(), nullable=False),
        sa.Column("behavior_changed", sa.Boolean(), nullable=False),
        sa.Column("mean_similarity", sa.Float(), nullable=False),
        sa.Column("similarity_threshold", sa.Float(), nullable=False),
        sa.Column("classification", sa.Text(), nullable=False),
        sa.Column("per_case_similarity", postgresql.JSONB(), nullable=False),
        sa.Column("detail", sa.Text(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "classification IN "
            "('no_op','safe_refactor','expected_change','silent_drift','insufficient_data')",
            name="ck_behavior_diffs_classification",
        ),
    )
    op.create_index(
        "ix_behavior_diffs_agent_created",
        "behavior_diffs", ["agent_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_behavior_diffs_agent_created", "behavior_diffs")
    op.drop_table("behavior_diffs")
