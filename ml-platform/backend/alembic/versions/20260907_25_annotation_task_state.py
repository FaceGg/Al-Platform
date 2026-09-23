"""Add task revisions and preview operations."""
from alembic import op
import sqlalchemy as sa

revision = "20260907_25"
down_revision = "20260907_24"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "task_revision" not in {item["name"] for item in inspector.get_columns("generic_annotation_tasks")}:
        op.add_column("generic_annotation_tasks", sa.Column("task_revision", sa.Integer(), nullable=False, server_default="0"))
    if "annotation_task_previews" not in inspector.get_table_names():
        op.create_table("annotation_task_previews", sa.Column("id", sa.Uuid(), primary_key=True), sa.Column("task_id", sa.Uuid(), sa.ForeignKey("generic_annotation_tasks.id", ondelete="CASCADE"), nullable=False), sa.Column("task_revision", sa.Integer(), nullable=False), sa.Column("config_hash", sa.String(128), nullable=False), sa.Column("operation_id", sa.Uuid(), nullable=False, unique=True), sa.Column("status", sa.String(24), nullable=False, server_default="queued"), sa.Column("summary", sa.JSON(), nullable=False), sa.Column("created_by", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False), sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False), sa.UniqueConstraint("task_id", "task_revision", "config_hash", name="uq_annotation_preview_task_revision_config"))
        op.create_index("ix_annotation_task_previews_task", "annotation_task_previews", ["task_id", "created_at"])


def downgrade():
    bind = op.get_bind()
    if "annotation_task_previews" in sa.inspect(bind).get_table_names():
        op.drop_table("annotation_task_previews")
    if "task_revision" in {item["name"] for item in sa.inspect(bind).get_columns("generic_annotation_tasks")}:
        op.drop_column("generic_annotation_tasks", "task_revision")
