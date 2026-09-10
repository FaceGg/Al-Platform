"""Persist immutable automatic annotation strategy artifacts."""

from alembic import op
import sqlalchemy as sa

revision = "20260908_29"
down_revision = "20260908_28"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "annotation_strategy_artifacts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("task_id", sa.Uuid(), nullable=False),
        sa.Column("task_revision", sa.Integer(), nullable=False),
        sa.Column("config_hash", sa.String(length=128), nullable=False),
        sa.Column("strategy", sa.String(length=32), nullable=False),
        sa.Column("artifact", sa.JSON(), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("task_id", "task_revision", "config_hash", name="uq_annotation_strategy_artifact_revision_config"),
    )
    op.create_index("ix_annotation_strategy_artifacts_task", "annotation_strategy_artifacts", ["task_id", "created_at"])


def downgrade():
    op.drop_index("ix_annotation_strategy_artifacts_task", table_name="annotation_strategy_artifacts")
    op.drop_table("annotation_strategy_artifacts")
