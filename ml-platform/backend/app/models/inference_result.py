"""Per-sample inference result persistence (补齐路线第一批 B1-16).

三层存储的落库层（技术方案 §3）：
- inference_results：全量窄表——所有样本的键 + 结果 + 归属快照
  （项目→场景→工位→设备产生时点绑定），保留期由 expires_at 驱动
  （每日 beat 清理，独立配置 inference_result_retention_days，默认 90 天）。
- inference_result_buckets：聚合桶——按（小时, 场景, 工位, 工况值）聚合的
  计数与均分，永久保留；驾驶舱/趋势（F3）读桶不扫明细。

channel 枚举是诚实设计⑥的落点：聚合与查询默认排除 demo（D13）；
shadow/replay/batch 随后续阶段接入。alert_id 在 F1 只留字符串占位，
F2 alerts 表落码时改建 FK 回填。
"""
import uuid

from sqlalchemy import (
    Boolean,
    CheckConstraint,
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


class InferenceResult(Base):
    __tablename__ = "inference_results"
    __table_args__ = (
        CheckConstraint(
            "channel IN ('online', 'batch', 'shadow', 'replay', 'demo')",
            name="ck_inference_results_channel",
        ),
        Index("ix_inference_results_request_id", "request_id"),
        Index("ix_inference_results_sample_key", "sample_key"),
        Index("ix_inference_results_occurred", "occurred_at"),
        Index("ix_inference_results_expires", "expires_at"),
        Index(
            "ix_inference_results_project_occurred",
            "project_id",
            "occurred_at",
        ),
        Index(
            "ix_inference_results_scene_occurred",
            "scene_id",
            "occurred_at",
        ),
        # F3 实时监控：按工位取最新一条推理结果（工位卡）
        Index("ix_inference_results_station_occurred", "station_id", "occurred_at"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    request_id = Column(String(128), nullable=False)
    # context.sample_key；缺省空（无上下文的既有调用方不受影响）
    sample_key = Column(String(256), nullable=True)

    # 诚实设计⑥落点列：online/batch/shadow/replay/demo
    channel = Column(String(16), nullable=False, default="online")

    # 归属（项目必填；场景/工位/设备是产生时点绑定快照——工位/设备
    # 可能在结果产生后重绑，明细不跟随漂移）
    project_id = Column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
    )
    scene_id = Column(
        UUID(as_uuid=True),
        ForeignKey("quality_scenes.id", ondelete="SET NULL"),
        nullable=True,
    )
    station_id = Column(
        UUID(as_uuid=True),
        ForeignKey("quality_stations.id", ondelete="SET NULL"),
        nullable=True,
    )
    device_id = Column(
        UUID(as_uuid=True),
        ForeignKey("edge_devices.id", ondelete="SET NULL"),
        nullable=True,
    )
    # 工况值（分片路由结果回显，先例 api/inference_production.py condition_values）
    condition_value = Column(String(128), nullable=True)

    deployment_id = Column(
        UUID(as_uuid=True),
        ForeignKey("inference_deployments.id", ondelete="SET NULL"),
        nullable=True,
    )
    revision_id = Column(
        UUID(as_uuid=True),
        ForeignKey("deployment_revisions.id", ondelete="SET NULL"),
        nullable=True,
    )
    model_version_id = Column(
        UUID(as_uuid=True),
        ForeignKey("model_versions.id", ondelete="SET NULL"),
        nullable=True,
    )

    # 结果三形态：有监督标签 / 有监督数值与概率 / 无监督三要素
    predicted_label = Column(String(128), nullable=True)
    predicted_value = Column(Float, nullable=True)
    probability = Column(Float, nullable=True)
    anomaly_score = Column(Float, nullable=True)
    is_anomaly = Column(Boolean, nullable=True)
    threshold = Column(Float, nullable=True)

    # 业务维度保留键（context）
    batch_no = Column(String(128), nullable=True)
    shift = Column(String(128), nullable=True)
    product_code = Column(String(128), nullable=True)
    collected_at = Column(DateTime, nullable=True)
    # context 其余键进 extra（诚实口径：只存调用方主动上报的业务键）
    extra = Column(JSON, nullable=True)

    occurred_at = Column(DateTime, nullable=False, server_default=func.now())
    expires_at = Column(DateTime, nullable=True)

    # 预警标记（F2 起由预警产生器写入）
    alert_triggered = Column(Boolean, nullable=True)
    # 命中的预警（F2 _109 建 FK；F1 只留占位列）
    alert_id = Column(
        UUID(as_uuid=True),
        ForeignKey("quality_alerts.id", ondelete="SET NULL"),
        nullable=True,
    )

    snapshot_uri = Column(String(512), nullable=True)
    source_uri = Column(String(512), nullable=True)


class InferenceResultBucket(Base):
    __tablename__ = "inference_result_buckets"
    __table_args__ = (
        # 聚合键（小时桶）；scene/station/condition 可空（无场景上下文的
        # 写入退化为 project 级桶）——NULL 组合在 PG/SQLite 唯一约束下互异，
        # 并发首建仲裁依赖本约束（先例 InferenceMetricBucket）
        UniqueConstraint(
            "bucket_start",
            "scene_id",
            "station_id",
            "condition_value",
            name="uq_inference_result_buckets_key",
        ),
        Index("ix_inference_result_buckets_bucket", "bucket_start"),
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

    total = Column(Integer, nullable=False, default=0)
    ok_count = Column(Integer, nullable=False, default=0)
    anomaly_count = Column(Integer, nullable=False, default=0)
    # NG 人工确认数（F2 起随处置单回写，F1 恒 0）
    ng_confirmed_count = Column(Integer, nullable=False, default=0)
    avg_score = Column(Float, nullable=True)
    updated_at = Column(DateTime, nullable=False, server_default=func.now())
