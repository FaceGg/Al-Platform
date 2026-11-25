# -*- coding: utf-8 -*-
"""Inference results: per-sample detail table + aggregate buckets (B1-16).

补齐路线第一批 F1（技术方案 §3）：
- inference_results：全量窄表（所有样本的键 + 结果 + 归属快照），保留期
  由 expires_at 驱动（独立配置 90 天，每日 beat 清理）；channel 枚举是
  诚实设计⑥落点（聚合与查询默认排除 demo）。
- inference_result_buckets：按（小时, 场景, 工位, 工况值）的聚合桶，
  永久保留；键含 NULL 的组合在 PG/SQLite 默认唯一约束下互异——写侧
  NULL 键走 SELECT→INSERT，重复桶由读侧 SUM 兜底。
"""
import sqlalchemy as sa
from alembic import op

revision = "20261125_106"
down_revision = "20261125_105"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "inference_results",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("request_id", sa.String(128), nullable=False),
        sa.Column("sample_key", sa.String(256), nullable=True),
        sa.Column("channel", sa.String(16), nullable=False, server_default="online"),
        sa.Column(
            "project_id", sa.Uuid(),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "scene_id", sa.Uuid(),
            sa.ForeignKey("quality_scenes.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "station_id", sa.Uuid(),
            sa.ForeignKey("quality_stations.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "device_id", sa.Uuid(),
            sa.ForeignKey("edge_devices.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("condition_value", sa.String(128), nullable=True),
        sa.Column(
            "deployment_id", sa.Uuid(),
            sa.ForeignKey("inference_deployments.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "revision_id", sa.Uuid(),
            sa.ForeignKey("deployment_revisions.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "model_version_id", sa.Uuid(),
            sa.ForeignKey("model_versions.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("predicted_label", sa.String(128), nullable=True),
        sa.Column("predicted_value", sa.Float(), nullable=True),
        sa.Column("probability", sa.Float(), nullable=True),
        sa.Column("anomaly_score", sa.Float(), nullable=True),
        sa.Column("is_anomaly", sa.Boolean(), nullable=True),
        sa.Column("threshold", sa.Float(), nullable=True),
        sa.Column("batch_no", sa.String(128), nullable=True),
        sa.Column("shift", sa.String(128), nullable=True),
        sa.Column("product_code", sa.String(128), nullable=True),
        sa.Column("collected_at", sa.DateTime(), nullable=True),
        sa.Column("extra", sa.JSON(), nullable=True),
        sa.Column("occurred_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=True),
        sa.Column("alert_triggered", sa.Boolean(), nullable=True),
        sa.Column("alert_id", sa.String(36), nullable=True),
        sa.Column("snapshot_uri", sa.String(512), nullable=True),
        sa.Column("source_uri", sa.String(512), nullable=True),
        sa.CheckConstraint(
            "channel IN ('online', 'batch', 'shadow', 'replay', 'demo')",
            name="ck_inference_results_channel",
        ),
    )
    op.create_index("ix_inference_results_request_id", "inference_results", ["request_id"])
    op.create_index("ix_inference_results_sample_key", "inference_results", ["sample_key"])
    op.create_index("ix_inference_results_occurred", "inference_results", ["occurred_at"])
    op.create_index("ix_inference_results_expires", "inference_results", ["expires_at"])
    op.create_index(
        "ix_inference_results_project_occurred", "inference_results",
        ["project_id", "occurred_at"],
    )
    op.create_index(
        "ix_inference_results_scene_occurred", "inference_results",
        ["scene_id", "occurred_at"],
    )

    op.create_table(
        "inference_result_buckets",
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
        sa.Column("total", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("ok_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("anomaly_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("ng_confirmed_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("avg_score", sa.Float(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint(
            "bucket_start", "scene_id", "station_id", "condition_value",
            name="uq_inference_result_buckets_key",
        ),
    )
    op.create_index("ix_inference_result_buckets_project_id", "inference_result_buckets", ["project_id"])
    op.create_index("ix_inference_result_buckets_bucket", "inference_result_buckets", ["bucket_start"])


def downgrade() -> None:
    op.drop_index("ix_inference_result_buckets_bucket", table_name="inference_result_buckets")
    op.drop_index("ix_inference_result_buckets_project_id", table_name="inference_result_buckets")
    op.drop_table("inference_result_buckets")
    op.drop_index("ix_inference_results_scene_occurred", table_name="inference_results")
    op.drop_index("ix_inference_results_project_occurred", table_name="inference_results")
    op.drop_index("ix_inference_results_expires", table_name="inference_results")
    op.drop_index("ix_inference_results_occurred", table_name="inference_results")
    op.drop_index("ix_inference_results_sample_key", table_name="inference_results")
    op.drop_index("ix_inference_results_request_id", table_name="inference_results")
    op.drop_table("inference_results")
