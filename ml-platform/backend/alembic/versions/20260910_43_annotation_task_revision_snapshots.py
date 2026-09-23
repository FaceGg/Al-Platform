"""Persist immutable generic task configuration revisions."""

from alembic import op
import sqlalchemy as sa


revision = "20260910_43"
down_revision = "20260910_42"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    if "annotation_task_revision_snapshots" in sa.inspect(bind).get_table_names():
        return
    op.create_table(
        "annotation_task_revision_snapshots",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("task_id", sa.Uuid(), nullable=False),
        sa.Column("task_revision", sa.Integer(), nullable=False),
        sa.Column("snapshot", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["task_id"], ["generic_annotation_tasks.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("task_id", "task_revision", name="uq_annotation_task_revision_snapshot"),
    )
    op.create_index(
        "ix_annotation_task_revision_snapshots_task",
        "annotation_task_revision_snapshots",
        ["task_id", "task_revision"],
    )


def downgrade():
    bind = op.get_bind()
    if "annotation_task_revision_snapshots" not in sa.inspect(bind).get_table_names():
        return
    op.drop_index("ix_annotation_task_revision_snapshots_task", table_name="annotation_task_revision_snapshots")
    op.drop_table("annotation_task_revision_snapshots")
