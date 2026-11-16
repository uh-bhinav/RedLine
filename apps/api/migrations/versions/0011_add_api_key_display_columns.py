"""add api_keys.key_prefix and last_four for masked display

Revision ID: 0011
Revises: 0010
Create Date: 2026-11-17
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0011"
down_revision: Union[str, None] = "0010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("api_keys", sa.Column("key_prefix", sa.String(), nullable=True))
    op.add_column("api_keys", sa.Column("last_four", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("api_keys", "last_four")
    op.drop_column("api_keys", "key_prefix")
