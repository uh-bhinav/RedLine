"""add entrypoint to agent_versions

DEVIATION NOTE (roadmap rule 5): Section 4's schema omitted an `entrypoint` column
on agent_versions, but Section 6 (AgentAdapter) and Section 13 (`agentbench
register-version`) both require one -- LocalPythonAdapter needs a Python import
path string per version, and the CLI explicitly captures + registers it. This is
an additive, backward-compatible fix (table is still empty at this point in the
build, so NOT NULL with no default is safe).

Revision ID: 0002
Revises: 0001
Create Date: 2026-06-29

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # agent_versions is still empty at this point in the build -- a NOT NULL
    # column with no default is safe; no existing rows to violate it.
    op.add_column("agent_versions", sa.Column("entrypoint", sa.Text(), nullable=False))


def downgrade() -> None:
    op.drop_column("agent_versions", "entrypoint")