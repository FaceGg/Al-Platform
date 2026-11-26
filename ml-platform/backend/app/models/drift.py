"""Drift monitoring models (补齐路线第一批 F4, B1-09).

特征级漂移检测的数据层（技术方案 §9C，D38–D40）：

- inference_feature_histograms：落库时按基线分箱累计的**特征直方图**。推理明细窄表
  不存特征值（F1 的容量决策），快照样本有偏；直方图覆盖全部样本、每特征每小时一行，
  是特征级 PSI 的唯一全量数据来源。箱边界取自该模型版本的训练分布基线。
- drift_baselines：模型版本的训练分布基线（等概率分箱的边界与比例），按血缘从训练
  数据集版本惰性计算；没有基线的模型版本不产生直方图。
- drift_reports / drift_report_features：定时批检产出的分级报告与特征级明细。

分片部署说明（D39）：落库的 model_version_id 是部署主版本，直方图按部署主版本的
基线分箱，分片间的分布差异会被平均掉。
"""
import uuid

from sqlalchemy import (
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID

from app.database import Base


DRIFT_LEVELS = ("severe", "watch", "stable", "insufficient")

DRIFT_SIGNAL_KINDS = ("feature_psi", "dq_missing", "dq_constant")


class InferenceFeatureHistogram(Base):
    __tablename__ = "inference_feature_histograms"
    __table_args__ = (
        # 键含 NULL（无场景/工位/工况上下文）时唯一约束在 PG 下互异：写侧用
        # 「先查后改」保证不重复（与聚合桶同样的处理）
        UniqueConstraint(
            "bucket_start",
            "scene_id",
            "station_id",
            "condition_value",
            "model_version_id",
            "feature_name",
            name="uq_inference_feature_histograms_key",
        ),
        Index(
            "ix_inference_feature_histograms_version_bucket",
            "model_version_id",
            "bucket_start",
        ),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    bucket_start = Column(DateTime, nullable=False)
    project_id = Column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    scene_id = Column(
        UUID(as_uuid=True),
        ForeignKey("quality_scenes.id", ondelete="CASCADE"),
        nullable=True,
    )
    station_id = Column(
        UUID(as_uuid=True),
        ForeignKey("quality_stations.id", ondelete="CASCADE"),
        nullable=True,
    )
    condition_value = Column(String(128), nullable=True)
    model_version_id = Column(
        UUID(as_uuid=True),
        ForeignKey("model_versions.id", ondelete="CASCADE"),
        nullable=False,
    )
    feature_name = Column(String(256), nullable=False)
    # 与基线的箱一一对应的计数
    bin_counts = Column(JSON, nullable=False, default=list)
    missing_count = Column(Integer, nullable=False, default=0)
    total_count = Column(Integer, nullable=False, default=0)
    updated_at = Column(DateTime, nullable=False, server_default=func.now())


class DriftBaseline(Base):
    __tablename__ = "drift_baselines"
    __table_args__ = (
        UniqueConstraint(
            "model_version_id",
            "feature_name",
            name="uq_drift_baselines_version_feature",
        ),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    model_version_id = Column(
        UUID(as_uuid=True),
        ForeignKey("model_versions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    feature_name = Column(String(256), nullable=False)
    # bins + 1 个边界
    bin_edges = Column(JSON, nullable=False, default=list)
    # bins 个比例，和为 1
    bin_probs = Column(JSON, nullable=False, default=list)
    sample_count = Column(Integer, nullable=False, default=0)
    # training_dataset：按血缘从训练数据集版本计算
    source = Column(String(32), nullable=False, default="training_dataset")
    dataset_version_id = Column(
        UUID(as_uuid=True),
        ForeignKey("dataset_versions.id", ondelete="SET NULL"),
        nullable=True,
    )
    content_hash = Column(String(128), nullable=True)
    created_at = Column(DateTime, nullable=False, server_default=func.now())


class DriftReport(Base):
    __tablename__ = "drift_reports"
    __table_args__ = (
        Index("ix_drift_reports_project_created", "project_id", "created_at"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id = Column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    deployment_id = Column(
        UUID(as_uuid=True),
        ForeignKey("inference_deployments.id", ondelete="SET NULL"),
        nullable=True,
    )
    model_version_id = Column(
        UUID(as_uuid=True),
        ForeignKey("model_versions.id", ondelete="SET NULL"),
        nullable=True,
    )
    started_at = Column(DateTime, nullable=False)
    ended_at = Column(DateTime, nullable=False)
    level = Column(String(16), nullable=False)
    sample_count = Column(Integer, nullable=False, default=0)
    summary = Column(JSON, nullable=False, default=dict)
    proposal_at = Column(DateTime, nullable=True)
    proposal_by_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at = Column(DateTime, nullable=False, server_default=func.now())


class DriftReportFeature(Base):
    __tablename__ = "drift_report_features"
    __table_args__ = (
        Index("ix_drift_report_features_report", "report_id", "feature_name"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    report_id = Column(
        UUID(as_uuid=True),
        ForeignKey("drift_reports.id", ondelete="CASCADE"),
        nullable=False,
    )
    feature_name = Column(String(256), nullable=False)
    signal_kind = Column(String(32), nullable=False)
    value = Column(Float, nullable=False)
    threshold = Column(Float, nullable=False)
    level = Column(String(16), nullable=False)
    detail = Column(JSON, nullable=False, default=dict)
