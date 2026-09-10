"""Add generic annotator assignment and return batch tables."""

from alembic import op
import sqlalchemy as sa

revision = "20260908_31"
down_revision = "20260908_30"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())
    if "annotation_assignments" not in tables:
        op.create_table(
            "annotation_assignments",
            sa.Column("id", sa.Uuid(), nullable=False),
            sa.Column("task_id", sa.Uuid(), nullable=False),
            sa.Column("annotator_subject_id", sa.Uuid(), nullable=False),
            sa.Column("sample_scope", sa.JSON(), nullable=False),
            sa.Column("scope_hash", sa.String(length=128), nullable=False),
            sa.Column("due_at", sa.DateTime(), nullable=True),
            sa.Column("state", sa.String(length=32), nullable=False, server_default="pending"),
            sa.Column("task_revision", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("last_edit_revision", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("created_by", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("task_id", "annotator_subject_id", "scope_hash", name="uq_annotation_assignment_scope"),
        )
        op.create_index("ix_annotation_assignments_task_state", "annotation_assignments", ["task_id", "state"])
        op.create_index("ix_annotation_assignments_subject", "annotation_assignments", ["annotator_subject_id", "state"])
    if "annotation_assignment_samples" not in tables:
        op.create_table(
            "annotation_assignment_samples",
            sa.Column("id", sa.Uuid(), nullable=False),
            sa.Column("assignment_id", sa.Uuid(), sa.ForeignKey("annotation_assignments.id", ondelete="CASCADE"), nullable=False),
            sa.Column("sample_id", sa.String(length=256), nullable=False),
            sa.Column("revision_no", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("values", sa.JSON(), nullable=False),
            sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("assignment_id", "sample_id", name="uq_annotation_assignment_sample"),
        )
        op.create_index("ix_annotation_assignment_samples_sample", "annotation_assignment_samples", ["sample_id"])
    if "annotation_return_batches" not in tables:
        op.create_table(
            "annotation_return_batches",
            sa.Column("id", sa.Uuid(), nullable=False),
            sa.Column("assignment_id", sa.Uuid(), sa.ForeignKey("annotation_assignments.id", ondelete="CASCADE"), nullable=False),
            sa.Column("task_revision", sa.Integer(), nullable=False),
            sa.Column("scope_hash", sa.String(length=128), nullable=False),
            sa.Column("idempotency_key", sa.String(length=128), nullable=False),
            sa.Column("state", sa.String(length=32), nullable=False, server_default="pending"),
            sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("assignment_id", "idempotency_key", name="uq_annotation_return_batch_idempotency"),
        )
        op.create_index("ix_annotation_return_batches_assignment", "annotation_return_batches", ["assignment_id", "created_at"])


def downgrade():
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())
    if "annotation_return_batches" in tables:
        op.drop_table("annotation_return_batches")
    if "annotation_assignment_samples" in tables:
        op.drop_table("annotation_assignment_samples")
    if "annotation_assignments" in tables:
        op.drop_table("annotation_assignments")
