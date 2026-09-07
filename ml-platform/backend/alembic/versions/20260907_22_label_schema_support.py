"""Add label constraints, task bindings, comments and confirmations."""

from alembic import op
import sqlalchemy as sa

revision = "20260907_22"
down_revision = "20260907_21"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    tables = set(inspector.get_table_names())
    if "label_value_constraints" not in tables:
        op.create_table("label_value_constraints", sa.Column("id", sa.Uuid(), primary_key=True), sa.Column("column_id", sa.Uuid(), sa.ForeignKey("label_columns.id", ondelete="CASCADE"), nullable=False), sa.Column("kind", sa.String(32), nullable=False), sa.Column("config", sa.JSON(), nullable=False), sa.UniqueConstraint("column_id", "kind", name="uq_label_constraint_column_kind"))
    if "annotation_task_labels" not in tables:
        op.create_table("annotation_task_labels", sa.Column("id", sa.Uuid(), primary_key=True), sa.Column("task_id", sa.Uuid(), nullable=False), sa.Column("schema_id", sa.Uuid(), sa.ForeignKey("label_schemas.id"), nullable=False), sa.Column("schema_snapshot", sa.JSON(), nullable=False), sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False), sa.UniqueConstraint("task_id", name="uq_annotation_task_label_task"))
        op.create_index("ix_annotation_task_labels_schema", "annotation_task_labels", ["schema_id"])
    if "annotation_comments" not in tables:
        op.create_table("annotation_comments", sa.Column("id", sa.Uuid(), primary_key=True), sa.Column("task_id", sa.Uuid(), nullable=False), sa.Column("sample_id", sa.String(256), nullable=False), sa.Column("revision_id", sa.Uuid(), sa.ForeignKey("annotation_revisions.id"), nullable=True), sa.Column("author_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False), sa.Column("body", sa.Text(), nullable=False), sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False))
        op.create_index("ix_annotation_comments_task_sample", "annotation_comments", ["task_id", "sample_id"])
    if "annotation_confirmations" not in tables:
        op.create_table("annotation_confirmations", sa.Column("id", sa.Uuid(), primary_key=True), sa.Column("task_id", sa.Uuid(), nullable=False), sa.Column("sample_id", sa.String(256), nullable=False), sa.Column("revision_id", sa.Uuid(), sa.ForeignKey("annotation_revisions.id"), nullable=False), sa.Column("confirmer_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False), sa.Column("action", sa.String(24), nullable=False, server_default="confirm"), sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False))
        op.create_index("ix_annotation_confirmations_task_sample", "annotation_confirmations", ["task_id", "sample_id"])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    for table in ("annotation_confirmations", "annotation_comments", "annotation_task_labels", "label_value_constraints"):
        if table in inspector.get_table_names():
            op.drop_table(table)
