"""Orchestration API showcase: per-API reflow/alert counters and event stream.

Revision ID: 20261015_70
Revises: 20261014_69
Create Date: 2026-10-15
"""

import sqlalchemy as sa
from alembic import op

revision = "20261015_70"
down_revision = "20261014_69"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("platform_apis") as batch_op:
        batch_op.add_column(
            sa.Column("error_calls", sa.Integer(), nullable=False, server_default=sa.text("0"))
        )
        batch_op.add_column(
            sa.Column("alert_calls", sa.Integer(), nullable=False, server_default=sa.text("0"))
        )
        batch_op.add_column(sa.Column("showcase_state", sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("platform_apis") as batch_op:
        batch_op.drop_column("showcase_state")
        batch_op.drop_column("alert_calls")
        batch_op.drop_column("error_calls")
