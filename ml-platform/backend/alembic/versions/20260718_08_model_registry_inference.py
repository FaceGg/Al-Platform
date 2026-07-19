"""Add immutable model registry and inference deployments."""

from alembic import op
import sqlalchemy as sa


revision = "20260718_08"
down_revision = "20260718_07"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "registered_models",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("created_by_id", sa.UUID(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("project_id", "name", name="uq_registered_models_project_name"),
    )
    op.create_index(
        "ix_registered_models_project_created",
        "registered_models",
        ["project_id", "created_at"],
    )

    op.create_table(
        "model_versions",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("registered_model_id", sa.UUID(), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("source_kind", sa.String(length=32), nullable=False),
        sa.Column("source_model_library_id", sa.UUID(), nullable=True),
        sa.Column("source_artifact_id", sa.UUID(), nullable=False),
        sa.Column("onnx_artifact_id", sa.UUID(), nullable=False),
        sa.Column("framework", sa.String(length=64), nullable=False),
        sa.Column("algorithm", sa.String(length=128), nullable=False),
        sa.Column("feature_schema", sa.JSON(), nullable=False),
        sa.Column("output_schema", sa.JSON(), nullable=False),
        sa.Column("metrics", sa.JSON(), nullable=False),
        sa.Column("conversion_metadata", sa.JSON(), nullable=False),
        sa.Column("approval_status", sa.String(length=16), nullable=False),
        sa.Column("approval_comment", sa.Text(), nullable=False),
        sa.Column("approved_by_id", sa.UUID(), nullable=True),
        sa.Column("approved_at", sa.DateTime(), nullable=True),
        sa.Column("created_by_id", sa.UUID(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "source_kind IN ('platform_joblib', 'onnx_artifact')",
            name="ck_model_versions_source_kind",
        ),
        sa.CheckConstraint(
            "approval_status IN ('pending', 'approved', 'rejected', 'archived')",
            name="ck_model_versions_approval_status",
        ),
        sa.CheckConstraint(
            "(source_kind = 'platform_joblib' AND source_model_library_id IS NOT NULL) "
            "OR (source_kind = 'onnx_artifact' AND source_model_library_id IS NULL)",
            name="ck_model_versions_source_reference",
        ),
        sa.CheckConstraint("version_number > 0", name="ck_model_versions_positive_number"),
        sa.ForeignKeyConstraint(["approved_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["onnx_artifact_id"], ["artifacts.id"],
            deferrable=True, initially="DEFERRED",
        ),
        sa.ForeignKeyConstraint(["registered_model_id"], ["registered_models.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["source_artifact_id"], ["artifacts.id"],
            deferrable=True, initially="DEFERRED",
        ),
        sa.ForeignKeyConstraint(
            ["source_model_library_id"], ["model_library.id"],
            deferrable=True, initially="DEFERRED",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "registered_model_id",
            "version_number",
            name="uq_model_versions_model_number",
        ),
    )
    op.create_index(
        "ix_model_versions_model_created",
        "model_versions",
        ["registered_model_id", "created_at"],
    )
    op.create_index(
        "ix_model_versions_approval_created",
        "model_versions",
        ["approval_status", "created_at"],
    )

    op.create_table(
        "inference_deployments",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("model_version_id", sa.UUID(), nullable=False),
        sa.Column("desired_state", sa.String(length=16), nullable=False),
        sa.Column("observed_state", sa.String(length=16), nullable=False),
        sa.Column("last_error_code", sa.String(length=64), nullable=True),
        sa.Column("last_checked_at", sa.DateTime(), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("stopped_at", sa.DateTime(), nullable=True),
        sa.Column("created_by_id", sa.UUID(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "desired_state IN ('stopped', 'running')",
            name="ck_inference_deployments_desired_state",
        ),
        sa.CheckConstraint(
            "observed_state IN ('stopped', 'starting', 'running', 'stopping', 'failed')",
            name="ck_inference_deployments_observed_state",
        ),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["model_version_id"], ["model_versions.id"],
            deferrable=True, initially="DEFERRED",
        ),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "project_id",
            "name",
            name="uq_inference_deployments_project_name",
        ),
    )
    op.create_index(
        "ix_inference_deployments_project_state",
        "inference_deployments",
        ["project_id", "observed_state"],
    )
    op.create_index(
        "ix_inference_deployments_desired_checked",
        "inference_deployments",
        ["desired_state", "last_checked_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_inference_deployments_desired_checked",
        table_name="inference_deployments",
    )
    op.drop_index(
        "ix_inference_deployments_project_state",
        table_name="inference_deployments",
    )
    op.drop_table("inference_deployments")
    op.drop_index(
        "ix_model_versions_approval_created",
        table_name="model_versions",
    )
    op.drop_index(
        "ix_model_versions_model_created",
        table_name="model_versions",
    )
    op.drop_table("model_versions")
    op.drop_index(
        "ix_registered_models_project_created",
        table_name="registered_models",
    )
    op.drop_table("registered_models")
