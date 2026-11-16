"""dashboard analytics: ARS, drift, diffs, load tests, failure mining, auth columns

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-16
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

from apps.api import models  # noqa: F401
from apps.api.core.db import Base

revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

NEW_TABLES = [
    "diff_runs",
    "ars_snapshots",
    "drift_alerts",
    "diff_case_results",
    "load_runs",
    "failure_clusters",
    "candidate_cases",
]


def upgrade() -> None:
    op.add_column("users", sa.Column("name", sa.String(), nullable=True))
    op.add_column("api_keys", sa.Column("label", sa.String(), nullable=True))
    op.add_column("api_keys", sa.Column("last_four", sa.String(), nullable=True))
    op.add_column(
        "api_keys",
        sa.Column("created_by", sa.dialects.postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key("fk_api_keys_created_by", "api_keys", "users", ["created_by"], ["id"])
    op.add_column(
        "eval_cases",
        sa.Column("is_chaos", sa.Boolean(), nullable=False, server_default="false"),
    )
    bind = op.get_bind()
    tables = [Base.metadata.tables[name] for name in NEW_TABLES]
    Base.metadata.create_all(bind, tables=tables)


def downgrade() -> None:
    bind = op.get_bind()
    tables = [Base.metadata.tables[name] for name in reversed(NEW_TABLES)]
    Base.metadata.drop_all(bind, tables=tables)
    op.drop_column("eval_cases", "is_chaos")
    op.drop_constraint("fk_api_keys_created_by", "api_keys", type_="foreignkey")
    op.drop_column("api_keys", "created_by")
    op.drop_column("api_keys", "last_four")
    op.drop_column("api_keys", "label")
    op.drop_column("users", "name")
