"""Persist high-cardinality frozen automatic-annotation decisions."""

from alembic import op
import sqlalchemy as sa


revision = "20260916_51"
down_revision = "20260916_50"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "annotation_strategy_decisions" not in inspector.get_table_names():
        op.create_table(
            "annotation_strategy_decisions",
            sa.Column("id", sa.Uuid(), nullable=False),
            sa.Column("strategy_artifact_id", sa.Uuid(), nullable=False),
            sa.Column("sample_id", sa.String(length=256), nullable=False),
            sa.Column("row_index", sa.Integer(), nullable=False),
            sa.Column("status", sa.String(length=24), nullable=False),
            sa.Column("values", sa.JSON(), nullable=False),
            sa.Column("provenance", sa.JSON(), nullable=False),
            sa.Column("model_output", sa.JSON(), nullable=False),
            sa.Column("cluster_id", sa.Integer(), nullable=True),
            sa.Column("matched_rule_ids", sa.JSON(), nullable=False),
            sa.Column("decision_hash", sa.String(length=71), nullable=False),
            sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
            sa.ForeignKeyConstraint(
                ["strategy_artifact_id"],
                ["annotation_strategy_artifacts.id"],
                ondelete="CASCADE",
            ),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "strategy_artifact_id",
                "sample_id",
                name="uq_annotation_strategy_decision_sample",
            ),
        )
    indexes = {
        index["name"]
        for index in sa.inspect(bind).get_indexes("annotation_strategy_decisions")
    }
    if "ix_annotation_strategy_decisions_artifact_row" not in indexes:
        op.create_index(
            "ix_annotation_strategy_decisions_artifact_row",
            "annotation_strategy_decisions",
            ["strategy_artifact_id", "row_index", "id"],
        )
    if "ix_annotation_strategy_decisions_artifact_cluster" not in indexes:
        op.create_index(
            "ix_annotation_strategy_decisions_artifact_cluster",
            "annotation_strategy_decisions",
            ["strategy_artifact_id", "cluster_id"],
        )


def downgrade():
    raise RuntimeError("Refusing destructive downgrade of frozen annotation strategy decisions")
