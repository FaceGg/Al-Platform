"""Persist generic annotation task execution results."""

from alembic import op
import sqlalchemy as sa


revision = "20260910_41"
down_revision = "20260909_40"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "annotation_task_execution_results" in inspector.get_table_names():
        return
    op.create_table(
        "annotation_task_execution_results",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("task_id", sa.Uuid(), nullable=False),
        sa.Column("operation_id", sa.Uuid(), nullable=False),
        sa.Column("preview_id", sa.Uuid(), nullable=False),
        sa.Column("task_revision", sa.Integer(), nullable=False),
        sa.Column("sample_id", sa.String(length=256), nullable=False),
        sa.Column("row_index", sa.Integer(), nullable=False),
        sa.Column("values", sa.JSON(), nullable=False),
        sa.Column("provenance", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["task_id"], ["generic_annotation_tasks.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["preview_id"], ["annotation_task_previews.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("operation_id", "sample_id", name="uq_annotation_execution_result_sample"),
    )
    op.create_index(
        "ix_annotation_execution_results_task",
        "annotation_task_execution_results",
        ["task_id", "task_revision", "row_index"],
    )
    op.create_index(
        "ix_annotation_execution_results_operation",
        "annotation_task_execution_results",
        ["operation_id", "row_index"],
    )


def downgrade():
    bind = op.get_bind()
    if "annotation_task_execution_results" not in sa.inspect(bind).get_table_names():
        return
    op.drop_index("ix_annotation_execution_results_operation", table_name="annotation_task_execution_results")
    op.drop_index("ix_annotation_execution_results_task", table_name="annotation_task_execution_results")
    op.drop_table("annotation_task_execution_results")
