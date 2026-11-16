"""add ix_eval_runs_tenant_created

Revision ID: 0010
Revises: 0009
Create Date: 2026-08-02
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0010"
down_revision: Union[str, None] = "0009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index("ix_eval_runs_tenant_created", "eval_runs", ["tenant_id", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_eval_runs_tenant_created", "eval_runs")
