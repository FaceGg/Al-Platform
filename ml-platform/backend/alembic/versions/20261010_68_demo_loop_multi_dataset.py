"""Demo loop: multi-dataset retrain selection and total prediction counter.

Revision ID: 20261010_68
Revises: 20261010_67
Create Date: 2026-10-10
"""

import sqlalchemy as sa
from alembic import op

revision = "20261010_68"
down_revision = "20261010_67"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "demo_loop_configs",
        sa.Column("retrain_dataset_artifact_ids", sa.JSON(), nullable=True),
    )
    op.add_column(
        "demo_loop_configs",
        sa.Column(
            "total_count",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
    )
    # Backfill the list column from the legacy single-dataset column.
    op.execute(
        "UPDATE demo_loop_configs "
        "SET retrain_dataset_artifact_ids = json_build_array(retrain_dataset_artifact_id::text) "
        "WHERE retrain_dataset_artifact_id IS NOT NULL "
        "AND retrain_dataset_artifact_ids IS NULL"
    )


def downgrade() -> None:
    op.execute(
        "UPDATE demo_loop_configs "
        "SET retrain_dataset_artifact_id = NULLIF(retrain_dataset_artifact_ids->>0, '')::uuid "
        "WHERE retrain_dataset_artifact_ids IS NOT NULL"
    )
    op.drop_column("demo_loop_configs", "total_count")
    op.drop_column("demo_loop_configs", "retrain_dataset_artifact_ids")
