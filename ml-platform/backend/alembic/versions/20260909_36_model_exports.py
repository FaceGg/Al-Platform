"""Persist reproducible model export operations."""

from alembic import op
import sqlalchemy as sa


revision = "20260909_36"
down_revision = "20260908_35"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "model_exports" in inspector.get_table_names():
        return
    op.create_table(
        "model_exports",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("model_version_id", sa.Uuid(), nullable=False),
        sa.Column("annotation_task_id", sa.Uuid(), nullable=True),
        sa.Column("annotation_task_revision", sa.Integer(), nullable=True),
        sa.Column("idempotency_scope", sa.String(length=256), nullable=False, server_default="model"),
        sa.Column("include_runtime", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("status", sa.String(length=24), nullable=False, server_default="queued"),
        sa.Column("package_path", sa.String(length=1024), nullable=True),
        sa.Column("manifest_sha256", sa.String(length=64), nullable=True),
        sa.Column("error", sa.JSON(), nullable=True),
        sa.Column("created_by_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["model_version_id"], ["model_versions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "idempotency_scope",
            "idempotency_key",
            name="uq_model_exports_idempotency",
        ),
    )
    op.create_index(
        "ix_model_exports_model_version_status",
        "model_exports",
        ["model_version_id", "status", "created_at"],
    )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "model_exports" not in inspector.get_table_names():
        return
    index_names = {index["name"] for index in inspector.get_indexes("model_exports")}
    if "ix_model_exports_model_version_status" in index_names:
        op.drop_index("ix_model_exports_model_version_status", table_name="model_exports")
    op.drop_table("model_exports")
