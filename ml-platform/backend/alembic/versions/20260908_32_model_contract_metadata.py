"""Add model registration contract and lifecycle metadata."""

from alembic import op
import sqlalchemy as sa


revision = "20260908_32"
down_revision = "20260908_31"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    existing_columns = {column["name"] for column in sa.inspect(bind).get_columns("model_versions")}
    with op.batch_alter_table("model_versions") as batch:
        if "lifecycle_state" not in existing_columns:
            batch.add_column(sa.Column("lifecycle_state", sa.String(16), nullable=False, server_default="pending_review"))
        if "registration_task_id" not in existing_columns:
            batch.add_column(sa.Column("registration_task_id", sa.Uuid(), nullable=True))
        if "registration_candidate_id" not in existing_columns:
            batch.add_column(sa.Column("registration_candidate_id", sa.String(128), nullable=True))
        if "registration_idempotency_key" not in existing_columns:
            batch.add_column(sa.Column("registration_idempotency_key", sa.String(128), nullable=True))
        batch.create_index(
            "uq_model_versions_registration_idempotency",
            ["registration_task_id", "registration_candidate_id", "registration_idempotency_key"],
            unique=True,
        )


def downgrade():
    with op.batch_alter_table("model_versions") as batch:
        batch.drop_index("uq_model_versions_registration_idempotency")
        for name in ("registration_idempotency_key", "registration_candidate_id", "registration_task_id", "lifecycle_state"):
            batch.drop_column(name)
