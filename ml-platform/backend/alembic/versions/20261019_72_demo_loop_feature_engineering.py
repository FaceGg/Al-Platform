"""Demo loop feature engineering mode: builtin bridge / workflow operator / script.

Revision ID: 20261019_72
Revises: 20261015_71
Create Date: 2026-10-19
"""

import sqlalchemy as sa
from alembic import op

revision = "20261019_72"
down_revision = "20261015_71"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("demo_loop_configs") as batch_op:
        batch_op.add_column(
            sa.Column(
                "feature_engineering_mode",
                sa.String(length=16),
                nullable=False,
                server_default=sa.text("'legacy'"),
            )
        )
        batch_op.add_column(sa.Column("feature_operator_id", sa.String(length=64), nullable=True))
        batch_op.add_column(sa.Column("feature_script", sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("demo_loop_configs") as batch_op:
        batch_op.drop_column("feature_script")
        batch_op.drop_column("feature_operator_id")
        batch_op.drop_column("feature_engineering_mode")
