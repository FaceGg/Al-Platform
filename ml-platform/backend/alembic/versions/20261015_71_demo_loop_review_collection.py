"""Demo loop review collection: correct-data sampling and field descriptions.

Revision ID: 20261015_71
Revises: 20261015_70
Create Date: 2026-10-15
"""

import sqlalchemy as sa
from alembic import op

revision = "20261015_71"
down_revision = "20261015_70"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("demo_loop_configs") as batch_op:
        batch_op.add_column(
            sa.Column(
                "collect_correct_enabled",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("false"),
            )
        )
        batch_op.add_column(sa.Column("correct_sample_ratio", sa.String(length=16), nullable=True))
        batch_op.add_column(sa.Column("field_descriptions", sa.JSON(), nullable=True))
        batch_op.add_column(sa.Column("correct_buffer", sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("demo_loop_configs") as batch_op:
        batch_op.drop_column("correct_buffer")
        batch_op.drop_column("field_descriptions")
        batch_op.drop_column("correct_sample_ratio")
        batch_op.drop_column("collect_correct_enabled")
