"""Add report-compatible spot-weld quality persistence."""

from alembic import op
import sqlalchemy as sa


revision = "20260730_09"
down_revision = "20260718_08"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "spot_weld_quality_runs",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("dataset_artifact_id", sa.UUID(), nullable=False),
        sa.Column("created_by_id", sa.UUID(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("field_mapping", sa.JSON(), nullable=False),
        sa.Column("feature_schema", sa.JSON(), nullable=False),
        sa.Column("input_fingerprint", sa.JSON(), nullable=False),
        sa.Column("statistics", sa.JSON(), nullable=False),
        sa.Column("automl_results", sa.JSON(), nullable=False),
        sa.Column("clustering_results", sa.JSON(), nullable=False),
        sa.Column("output_artifacts", sa.JSON(), nullable=False),
        sa.Column("rule_set_version", sa.String(length=64), nullable=False),
        sa.Column("task_id", sa.String(length=128), nullable=True),
        sa.Column("worker_id", sa.String(length=128), nullable=True),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("error_details", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["dataset_artifact_id"], ["artifacts.id"]),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_spot_weld_quality_runs_project_id", "spot_weld_quality_runs", ["project_id"])
    op.create_index("ix_spot_weld_quality_runs_dataset_artifact_id", "spot_weld_quality_runs", ["dataset_artifact_id"])
    op.create_index("ix_spot_weld_quality_runs_status", "spot_weld_quality_runs", ["status"])
    op.create_index("ix_spot_weld_quality_runs_task_id", "spot_weld_quality_runs", ["task_id"])

    op.create_table(
        "spot_weld_quality_samples",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("run_id", sa.UUID(), nullable=False),
        sa.Column("source_row_index", sa.Integer(), nullable=False),
        sa.Column("display_id", sa.String(length=64), nullable=False),
        sa.Column("table_values", sa.JSON(), nullable=False),
        sa.Column("feature_values", sa.JSON(), nullable=False),
        sa.Column("waveforms", sa.JSON(), nullable=False),
        sa.Column("automatic_label", sa.String(length=64), nullable=True),
        sa.Column("current_label", sa.String(length=64), nullable=True),
        sa.Column("current_note", sa.Text(), nullable=True),
        sa.Column("rule_hits", sa.JSON(), nullable=False),
        sa.Column("cluster_id", sa.Integer(), nullable=True),
        sa.Column("defect_probability", sa.Float(), nullable=True),
        sa.Column("warning_level", sa.String(length=24), nullable=False),
        sa.Column("review_status", sa.String(length=24), nullable=False),
        sa.Column("current_revision_id", sa.UUID(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["run_id"], ["spot_weld_quality_runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("run_id", "source_row_index", name="uq_spot_weld_quality_sample_run_row"),
    )
    op.create_index("ix_spot_weld_quality_samples_run_id", "spot_weld_quality_samples", ["run_id"])
    op.create_index("ix_spot_weld_quality_samples_run_review", "spot_weld_quality_samples", ["run_id", "review_status"])
    op.create_index("ix_spot_weld_quality_samples_run_warning", "spot_weld_quality_samples", ["run_id", "warning_level"])

    op.create_table(
        "spot_weld_quality_rule_sets",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("run_id", sa.UUID(), nullable=False),
        sa.Column("version", sa.String(length=64), nullable=False),
        sa.Column("thresholds", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["run_id"], ["spot_weld_quality_runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("run_id", "version", name="uq_spot_weld_quality_rule_set_run_version"),
    )
    op.create_index("ix_spot_weld_quality_rule_sets_project_id", "spot_weld_quality_rule_sets", ["project_id"])
    op.create_index("ix_spot_weld_quality_rule_sets_run_id", "spot_weld_quality_rule_sets", ["run_id"])

    op.create_table(
        "spot_weld_label_revisions",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("run_id", sa.UUID(), nullable=False),
        sa.Column("sample_id", sa.UUID(), nullable=False),
        sa.Column("author_id", sa.UUID(), nullable=False),
        sa.Column("label", sa.String(length=64), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("action", sa.String(length=24), nullable=False),
        sa.Column("decision", sa.String(length=24), nullable=True),
        sa.Column("review_comment", sa.Text(), nullable=True),
        sa.Column("parent_revision_id", sa.UUID(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["author_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["run_id"], ["spot_weld_quality_runs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["sample_id"], ["spot_weld_quality_samples.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_spot_weld_label_revisions_project_id", "spot_weld_label_revisions", ["project_id"])
    op.create_index("ix_spot_weld_label_revisions_run_id", "spot_weld_label_revisions", ["run_id"])
    op.create_index("ix_spot_weld_label_revisions_sample_id", "spot_weld_label_revisions", ["sample_id"])
    op.create_index("ix_spot_weld_label_revisions_sample_created", "spot_weld_label_revisions", ["sample_id", "created_at"])

    op.create_table(
        "spot_weld_label_snapshots",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("run_id", sa.UUID(), nullable=False),
        sa.Column("created_by_id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("labels", sa.JSON(), nullable=False),
        sa.Column("label_counts", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["run_id"], ["spot_weld_quality_runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("run_id", "name", name="uq_spot_weld_label_snapshot_run_name"),
    )
    op.create_index("ix_spot_weld_label_snapshots_project_id", "spot_weld_label_snapshots", ["project_id"])
    op.create_index("ix_spot_weld_label_snapshots_run_id", "spot_weld_label_snapshots", ["run_id"])


def downgrade() -> None:
    op.drop_index("ix_spot_weld_label_snapshots_run_id", table_name="spot_weld_label_snapshots")
    op.drop_index("ix_spot_weld_label_snapshots_project_id", table_name="spot_weld_label_snapshots")
    op.drop_table("spot_weld_label_snapshots")
    op.drop_index("ix_spot_weld_label_revisions_sample_created", table_name="spot_weld_label_revisions")
    op.drop_index("ix_spot_weld_label_revisions_sample_id", table_name="spot_weld_label_revisions")
    op.drop_index("ix_spot_weld_label_revisions_run_id", table_name="spot_weld_label_revisions")
    op.drop_index("ix_spot_weld_label_revisions_project_id", table_name="spot_weld_label_revisions")
    op.drop_table("spot_weld_label_revisions")
    op.drop_index("ix_spot_weld_quality_rule_sets_run_id", table_name="spot_weld_quality_rule_sets")
    op.drop_index("ix_spot_weld_quality_rule_sets_project_id", table_name="spot_weld_quality_rule_sets")
    op.drop_table("spot_weld_quality_rule_sets")
    op.drop_index("ix_spot_weld_quality_samples_run_warning", table_name="spot_weld_quality_samples")
    op.drop_index("ix_spot_weld_quality_samples_run_review", table_name="spot_weld_quality_samples")
    op.drop_index("ix_spot_weld_quality_samples_run_id", table_name="spot_weld_quality_samples")
    op.drop_table("spot_weld_quality_samples")
    op.drop_index("ix_spot_weld_quality_runs_task_id", table_name="spot_weld_quality_runs")
    op.drop_index("ix_spot_weld_quality_runs_status", table_name="spot_weld_quality_runs")
    op.drop_index("ix_spot_weld_quality_runs_dataset_artifact_id", table_name="spot_weld_quality_runs")
    op.drop_index("ix_spot_weld_quality_runs_project_id", table_name="spot_weld_quality_runs")
    op.drop_table("spot_weld_quality_runs")
