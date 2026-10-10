"""Demo loop: multi-dataset retrain selection and total prediction counter.

Revision ID: 20261010_68
Revises: 20261010_67
Create Date: 2026-10-10
"""

import json

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
    # Backfill the list column from the legacy single-dataset column using
    # dialect-neutral Python (json_build_array/::text are PostgreSQL-only and
    # break SQLite upgrades, violating the dual-dialect migration contract).
    conn = op.get_bind()
    rows = conn.execute(
        sa.text(
            "SELECT id, retrain_dataset_artifact_id FROM demo_loop_configs "
            "WHERE retrain_dataset_artifact_id IS NOT NULL "
            "AND retrain_dataset_artifact_ids IS NULL"
        )
    ).fetchall()
    for row_id, artifact_id in rows:
        conn.execute(
            sa.text(
                "UPDATE demo_loop_configs SET retrain_dataset_artifact_ids = :ids "
                "WHERE id = :row_id"
            ),
            {"ids": json.dumps([str(artifact_id)]), "row_id": str(row_id)},
        )


def downgrade() -> None:
    # Restore the legacy column from the first element of the JSON list using
    # dialect-neutral Python (the ->> operator is PostgreSQL-only).
    conn = op.get_bind()
    rows = conn.execute(
        sa.text(
            "SELECT id, retrain_dataset_artifact_ids FROM demo_loop_configs "
            "WHERE retrain_dataset_artifact_ids IS NOT NULL"
        )
    ).fetchall()
    for row_id, ids_json in rows:
        try:
            ids = json.loads(ids_json) if isinstance(ids_json, str) else (ids_json or [])
        except ValueError:
            ids = []
        first = str(ids[0]) if ids else None
        conn.execute(
            sa.text(
                "UPDATE demo_loop_configs SET retrain_dataset_artifact_id = :first "
                "WHERE id = :row_id"
            ),
            {"first": first, "row_id": str(row_id)},
        )
    op.drop_column("demo_loop_configs", "total_count")
    op.drop_column("demo_loop_configs", "retrain_dataset_artifact_ids")
