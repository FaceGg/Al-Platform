# -*- coding: utf-8 -*-
"""Drift monitoring tables (B1-09, F4).

补齐路线第一批 F4（技术方案 §9C.2，D38–D40）：
- inference_feature_histograms：落库时按基线分箱累计的特征直方图（特征级 PSI 的全量数据来源）；
- drift_baselines：模型版本的训练分布基线（等概率分箱），按血缘惰性计算；
- drift_reports / drift_report_features：定时批检的分级报告与特征级明细。

全新建表，不改既有表、不动数据。PG 与 SQLite 均为普通 create_table。
"""
import sqlalchemy as sa
from alembic import op

revision = "20261126_111"
down_revision = "20261126_110"
branch_labels = None
depends_on = None


def _table_names() -> set:
    inspector = sa.inspect(op.get_bind())
    return set(inspector.get_table_names())


def upgrade() -> None:
    op.create_table(
        "inference_feature_histograms",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("bucket_start", sa.DateTime(), nullable=False),
        sa.Column(
            "project_id", sa.Uuid(),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "scene_id", sa.Uuid(),
            sa.ForeignKey("quality_scenes.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column(
            "station_id", sa.Uuid(),
            sa.ForeignKey("quality_stations.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("condition_value", sa.String(128), nullable=True),
        sa.Column(
            "model_version_id", sa.Uuid(),
            sa.ForeignKey("model_versions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("feature_name", sa.String(256), nullable=False),
        sa.Column("bin_counts", sa.JSON(), nullable=False),
        sa.Column("missing_count", sa.Integer(), nullable=False),
        sa.Column("total_count", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint(
            "bucket_start", "scene_id", "station_id", "condition_value",
            "model_version_id", "feature_name",
            name="uq_inference_feature_histograms_key",
        ),
    )
    op.create_index(
        "ix_inference_feature_histograms_project_id", "inference_feature_histograms",
        ["project_id"],
    )
    op.create_index(
        "ix_inference_feature_histograms_version_bucket", "inference_feature_histograms",
        ["model_version_id", "bucket_start"],
    )

    op.create_table(
        "drift_baselines",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "model_version_id", sa.Uuid(),
            sa.ForeignKey("model_versions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("feature_name", sa.String(256), nullable=False),
        sa.Column("bin_edges", sa.JSON(), nullable=False),
        sa.Column("bin_probs", sa.JSON(), nullable=False),
        sa.Column("sample_count", sa.Integer(), nullable=False),
        sa.Column("source", sa.String(32), nullable=False),
        sa.Column(
            "dataset_version_id", sa.Uuid(),
            sa.ForeignKey("dataset_versions.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("content_hash", sa.String(128), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint(
            "model_version_id", "feature_name",
            name="uq_drift_baselines_version_feature",
        ),
    )
    op.create_index(
        "ix_drift_baselines_model_version_id", "drift_baselines", ["model_version_id"]
    )

    op.create_table(
        "drift_reports",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "project_id", sa.Uuid(),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "deployment_id", sa.Uuid(),
            sa.ForeignKey("inference_deployments.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "model_version_id", sa.Uuid(),
            sa.ForeignKey("model_versions.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("ended_at", sa.DateTime(), nullable=False),
        sa.Column("level", sa.String(16), nullable=False),
        sa.Column("sample_count", sa.Integer(), nullable=False),
        sa.Column("summary", sa.JSON(), nullable=False),
        sa.Column("proposal_at", sa.DateTime(), nullable=True),
        sa.Column(
            "proposal_by_id", sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
    )
    op.create_index(
        "ix_drift_reports_project_id", "drift_reports", ["project_id"]
    )
    op.create_index(
        "ix_drift_reports_project_created", "drift_reports", ["project_id", "created_at"]
    )

    op.create_table(
        "drift_report_features",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "report_id", sa.Uuid(),
            sa.ForeignKey("drift_reports.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("feature_name", sa.String(256), nullable=False),
        sa.Column("signal_kind", sa.String(32), nullable=False),
        sa.Column("value", sa.Float(), nullable=False),
        sa.Column("threshold", sa.Float(), nullable=False),
        sa.Column("level", sa.String(16), nullable=False),
        sa.Column("detail", sa.JSON(), nullable=False),
    )
    op.create_index(
        "ix_drift_report_features_report", "drift_report_features",
        ["report_id", "feature_name"],
    )

    assert {
        "inference_feature_histograms",
        "drift_baselines",
        "drift_reports",
        "drift_report_features",
    } <= _table_names()


def downgrade() -> None:
    op.drop_index("ix_drift_report_features_report", table_name="drift_report_features")
    op.drop_table("drift_report_features")
    op.drop_index("ix_drift_reports_project_created", table_name="drift_reports")
    op.drop_index("ix_drift_reports_project_id", table_name="drift_reports")
    op.drop_table("drift_reports")
    op.drop_index("ix_drift_baselines_model_version_id", table_name="drift_baselines")
    op.drop_table("drift_baselines")
    op.drop_index(
        "ix_inference_feature_histograms_version_bucket",
        table_name="inference_feature_histograms",
    )
    op.drop_index(
        "ix_inference_feature_histograms_project_id",
        table_name="inference_feature_histograms",
    )
    op.drop_table("inference_feature_histograms")
