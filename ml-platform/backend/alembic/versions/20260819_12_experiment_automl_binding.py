"""Add permanent one-to-one experiment AutoML bindings.

Revision ID: 20260819_12
Revises: 20260815_11
Create Date: 2026-08-19
"""

from alembic import op
import sqlalchemy as sa


revision = "20260819_12"
down_revision = "20260815_11"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "experiment_automl_bindings",
        sa.Column("experiment_id", sa.UUID(), nullable=False),
        sa.Column("job_id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["experiment_id"], ["experiments.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("experiment_id"),
    )
    op.create_index(
        "ix_experiment_automl_bindings_job_id",
        "experiment_automl_bindings",
        ["job_id"],
    )
    op.execute(sa.text("""
        INSERT INTO experiment_automl_bindings (experiment_id, job_id, created_at)
        SELECT experiment_id, id, COALESCE(created_at, CURRENT_TIMESTAMP)
        FROM (
            SELECT
                experiment_id,
                id,
                created_at,
                ROW_NUMBER() OVER (
                    PARTITION BY experiment_id
                    ORDER BY
                        CASE WHEN created_at IS NULL THEN 1 ELSE 0 END,
                        created_at,
                        id
                ) AS row_number
            FROM training_jobs
            WHERE operator_id = 'automl' AND experiment_id IS NOT NULL
        ) ranked_jobs
        WHERE row_number = 1
    """))


def downgrade() -> None:
    op.drop_index(
        "ix_experiment_automl_bindings_job_id",
        table_name="experiment_automl_bindings",
    )
    op.drop_table("experiment_automl_bindings")
