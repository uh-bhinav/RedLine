"""job reliability: attempts, retry backoff, heartbeat columns

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-16
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("jobs", sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("jobs", sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="3"))
    op.add_column(
        "jobs",
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.add_column("jobs", sa.Column("started_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("jobs", sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index("ix_jobs_status_available_at", "jobs", ["status", "available_at"])


def downgrade() -> None:
    op.drop_index("ix_jobs_status_available_at", table_name="jobs")
    for col in ("heartbeat_at", "started_at", "available_at", "max_attempts", "attempts"):
        op.drop_column("jobs", col)
