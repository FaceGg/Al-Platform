"""Agent run heartbeat column for in-process liveness recovery.

Revision ID: 20261026_84
Revises: 20261026_83
Create Date: 2026-10-27
"""

import sqlalchemy as sa
from alembic import op

revision = "20261026_84"
down_revision = "20261026_83"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "agent_runs",
        sa.Column("heartbeat_at", sa.DateTime(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("agent_runs", "heartbeat_at")
