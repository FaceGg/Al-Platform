"""Demo loop: separate correct-data collection artifact.

Revision ID: 20261020_74
Revises: 20261020_73
Create Date: 2026-10-20
"""

import sqlalchemy as sa
from alembic import op

revision = "20261020_74"
down_revision = "20261020_73"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("demo_loop_configs") as batch_op:
        batch_op.add_column(
            sa.Column("correct_artifact_id", sa.UUID(), nullable=True)
        )
        batch_op.create_index(
            "ix_demo_loop_configs_correct_artifact_id", ["correct_artifact_id"]
        )


def downgrade() -> None:
    with op.batch_alter_table("demo_loop_configs") as batch_op:
        batch_op.drop_index("ix_demo_loop_configs_correct_artifact_id")
        batch_op.drop_column("correct_artifact_id")
