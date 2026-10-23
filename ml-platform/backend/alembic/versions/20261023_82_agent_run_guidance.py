"""AgentRun guidance archive column (design: five-step wizard submission).

Revision ID: 20261023_82
Revises: 20261023_81
Create Date: 2026-10-23
"""

import sqlalchemy as sa
from alembic import op

revision = "20261023_82"
down_revision = "20261023_81"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("agent_runs", sa.Column("guidance_json", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("agent_runs", "guidance_json")
