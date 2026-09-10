"""Scope model registration idempotency to one task and request key."""

from alembic import op
import sqlalchemy as sa


revision = "20260909_37"
down_revision = "20260909_36"
branch_labels = None
depends_on = None


INDEX_NAME = "uq_model_versions_registration_idempotency"


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "model_versions" not in inspector.get_table_names():
        return
    existing = {item["name"] for item in inspector.get_indexes("model_versions")}
    if INDEX_NAME in existing:
        op.drop_index(INDEX_NAME, table_name="model_versions")
    op.create_index(
        INDEX_NAME,
        "model_versions",
        ["registration_task_id", "registration_idempotency_key"],
        unique=True,
    )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "model_versions" not in inspector.get_table_names():
        return
    existing = {item["name"] for item in inspector.get_indexes("model_versions")}
    if INDEX_NAME in existing:
        op.drop_index(INDEX_NAME, table_name="model_versions")
    op.create_index(
        INDEX_NAME,
        "model_versions",
        ["registration_task_id", "registration_candidate_id", "registration_idempotency_key"],
        unique=True,
    )
