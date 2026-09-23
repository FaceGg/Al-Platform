"""Store frozen annotation task scopes outside task snapshot JSON."""

from alembic import op
import sqlalchemy as sa


revision = "20260916_52"
down_revision = "20260916_51"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "annotation_task_scope_samples" not in inspector.get_table_names():
        op.create_table(
            "annotation_task_scope_samples",
            sa.Column("id", sa.Uuid(), nullable=False),
            sa.Column("task_id", sa.Uuid(), nullable=False),
            sa.Column("task_revision", sa.Integer(), nullable=False),
            sa.Column("sample_id", sa.String(length=256), nullable=False),
            sa.Column("row_index", sa.Integer(), nullable=False),
            sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
            sa.ForeignKeyConstraint(["task_id"], ["generic_annotation_tasks.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "task_id",
                "task_revision",
                "sample_id",
                name="uq_annotation_task_scope_sample",
            ),
        )
    indexes = {
        index["name"]
        for index in sa.inspect(bind).get_indexes("annotation_task_scope_samples")
    }
    if "ix_annotation_task_scope_samples_page" not in indexes:
        op.create_index(
            "ix_annotation_task_scope_samples_page",
            "annotation_task_scope_samples",
            ["task_id", "task_revision", "row_index", "id"],
        )


def downgrade():
    raise RuntimeError("Refusing destructive downgrade of frozen annotation task scopes")
