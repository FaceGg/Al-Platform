"""Add owner-scoped AutoML request idempotency."""

from alembic import op
import sqlalchemy as sa


revision = "20260905_19"
down_revision = "20260904_18"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {column["name"] for column in inspector.get_columns("training_jobs")}
    if "automl_idempotency_key" not in columns:
        op.add_column("training_jobs", sa.Column("automl_idempotency_key", sa.String(128), nullable=True))
    indexes = {index["name"] for index in sa.inspect(bind).get_indexes("training_jobs")}
    if "ix_training_jobs_automl_idempotency_key" not in indexes:
        op.create_index("ix_training_jobs_automl_idempotency_key", "training_jobs", ["automl_idempotency_key"])
    uniques = {constraint["name"] for constraint in sa.inspect(bind).get_unique_constraints("training_jobs")}
    if "uq_training_jobs_user_automl_idempotency" not in uniques:
        with op.batch_alter_table("training_jobs") as batch:
            batch.create_unique_constraint(
                "uq_training_jobs_user_automl_idempotency",
                ["user_id", "automl_idempotency_key"],
            )


def downgrade() -> None:
    raise RuntimeError("Refusing destructive downgrade of AutoML idempotency")
