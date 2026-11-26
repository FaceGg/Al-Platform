"""Quality alert & disposition models (补齐路线第一批 B1-01/B1-02，F2a).

预警处置主干的数据层（技术方案 §9.1，技术决策 D14–D22）：
- quality_alerts：六类来源归一的预警表，带项目→场景→工位→设备归属
  （路线 B1-01〔更正〕）与五阶段处置状态；同因合并（E20）用
  occurrence_count/last_event_at 表达，组内展开=读轨迹表。
- quality_alert_events：处置轨迹——阶段流转、处置表单快照与
  「当时生效的 SOP/基线/模型」三要素快照（E07，不可变）。
- quality_sops：SOP 按编号/适用工况/生效时间版本化（E07）。
- quality_spc_baselines：SPC 基线冻结（E08 前移 F2a）——I-MR 口径
  （中心=均值，σ=平均移动极差/1.128），版本化并可追溯引用窗口。
- model_evidence_checks：上线检查五项留档（E21，随 F2b 消费）。

预警来源先行三类（model_risk/param_exceed/device_anomaly）随 F2a 接入；
spc_violation 由 demo 投递与 F4 基线越限接入；sensor_anomaly/curve_deviation
随 F4 接入，不改表（路线 B1-01〔规划〕）。
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
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID

from app.database import Base


# 六类预警来源（路线 B1-01）；F2a 先行三类 + demo 投递两类
ALERT_SOURCE_TYPES = (
    "model_risk",       # 模型风险：推理结果越过触发阈值（B1-16 产生）
    "param_exceed",     # 参数超限：数值特征越过规格定义（判据引擎产生）
    "device_anomaly",   # 设备异常：心跳超时离线与状态异常（B1-10 产生）
    "spc_violation",    # SPC 判异：越冻结基线控制限 / Nelson 判异（F4 接入）
    "sensor_anomaly",   # 传感器异常：数据质量检查命中（F4 接入）
    "curve_deviation",  # 曲线偏离：波形统计量偏离规格 / 曲线比对（F4/F5 接入）
)

ALERT_SEVERITIES = ("warning", "high", "critical")

# 五阶段处置状态（路线 B1-02）
ALERT_STATUSES = ("open", "acknowledged", "processing", "review_pending", "closed")

# 合法流转图：closed 为终态；review_pending 可被复核驳回回 processing
ALERT_STATUS_FLOW = {
    "open": {"acknowledged"},
    "acknowledged": {"processing", "review_pending", "closed"},
    "processing": {"review_pending", "closed"},
    "review_pending": {"processing", "closed"},
    "closed": set(),
}

# 关闭结论（resolution）
ALERT_RESOLUTIONS = ("false_positive", "confirmed_issue", "other")

# 轨迹动作枚举
ALERT_EVENT_ACTIONS = (
    "created",
    "occurred",             # 同因合并：窗口内重复事件只增计数（D15）
    "acknowledged",
    "assigned",
    "status_changed",
    "disposition_submitted",
    "transfer",
    "review_requested",
    "attachment_added",
    "comment",
    "device_recovered",
    "sla_notified",
    "review_task_created",
)


class QualityAlert(Base):
    __tablename__ = "quality_alerts"
    __table_args__ = (
        CheckConstraint(
            "source_type IN ('model_risk', 'param_exceed', 'device_anomaly', "
            "'spc_violation', 'sensor_anomaly', 'curve_deviation')",
            name="ck_quality_alerts_source_type",
        ),
        CheckConstraint(
            "severity IN ('warning', 'high', 'critical')",
            name="ck_quality_alerts_severity",
        ),
        CheckConstraint(
            "status IN ('open', 'acknowledged', 'processing', "
            "'review_pending', 'closed')",
            name="ck_quality_alerts_status",
        ),
        Index(
            "ix_quality_alerts_project_status",
            "project_id",
            "status",
        ),
        Index("ix_quality_alerts_sample_key", "sample_key"),
        Index("ix_quality_alerts_batch_no", "batch_no"),
        Index("ix_quality_alerts_sla_due", "sla_due_at"),
        Index("ix_quality_alerts_is_demo", "is_demo"),
        # F3 监控驾驶：按时间窗聚合预警走势、按工位取最近预警
        Index("ix_quality_alerts_project_created", "project_id", "created_at"),
        Index("ix_quality_alerts_station_created", "station_id", "created_at"),
        # 同因合并查找路径（E20/D15）：项目 + 合并键 + 是否仍接受合并
        Index(
            "ix_quality_alerts_merge_key",
            "project_id",
            "merge_key",
            "merge_open",
        ),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id = Column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # 归属快照（产生时点绑定；工位/设备重绑后明细不跟随漂移，与 B1-16 同口径）
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
    condition_value = Column(String(128), nullable=True)

    source_type = Column(String(32), nullable=False)
    # 模型风险分（有监督概率 / 无监督异常分数）；口径脚注在前端（诚实设计②）
    risk_score = Column(Float, nullable=True)
    severity = Column(String(16), nullable=False, default="warning")

    title = Column(String(256), nullable=False)
    sample_key = Column(String(256), nullable=True)
    batch_no = Column(String(128), nullable=True)
    product_code = Column(String(128), nullable=True)
    # 实测值/规格快照/基线引用/模型依据/判据链命中（D19；判据复算读数）
    evidence = Column(JSON, nullable=False, default=dict)
    # 来源回链（如 {"kind": "inference_result", "id": ...}）
    source_ref = Column(JSON, nullable=True)

    status = Column(String(16), nullable=False, default="open", index=True)
    # 责任人（确认防呆：ack 必填，路线 B1-01）
    assigned_to_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    # 处置运营指标原始读数（E09，F3 驾驶舱消费）
    first_ack_at = Column(DateTime, nullable=True)
    closed_at = Column(DateTime, nullable=True)
    sla_due_at = Column(DateTime, nullable=True)
    # 0 未通知 / 1 临期已通知 / 2 超时已通知（SLA beat 防重发，D21）
    sla_notify_level = Column(SmallInteger, nullable=False, default=0)
    resolution = Column(String(32), nullable=True)

    # 同因合并（E20/D15）：窗口内重复事件只增计数
    occurrence_count = Column(Integer, nullable=False, default=1)
    # 合并键 = 来源类型 + 判别因子（参数超限的字段名、模型部署、演示配置）；
    # 与项目/场景/工位/设备一起决定「同因」——不同字段超限不得并成一条
    merge_key = Column(String(256), nullable=False)
    # False = 不再接受合并（设备恢复后，新一次离线须产生新预警）
    merge_open = Column(Boolean, nullable=False, default=True)
    last_event_at = Column(
        DateTime, nullable=False, server_default=func.now()
    )

    # 演示标记（诚实设计⑥/D18）：聚合与列表默认排除
    is_demo = Column(Boolean, nullable=False, default=False)

    created_at = Column(DateTime, nullable=False, server_default=func.now())
    updated_at = Column(DateTime, nullable=False, server_default=func.now(), onupdate=func.now())


class QualityAlertEvent(Base):
    __tablename__ = "quality_alert_events"
    __table_args__ = (
        CheckConstraint(
            "action IN ('created', 'occurred', 'acknowledged', 'assigned', "
            "'status_changed', 'disposition_submitted', 'transfer', "
            "'review_requested', 'attachment_added', 'comment', "
            "'device_recovered', 'sla_notified', 'review_task_created')",
            name="ck_quality_alert_events_action",
        ),
        Index("ix_quality_alert_events_alert", "alert_id", "created_at"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    alert_id = Column(
        UUID(as_uuid=True),
        ForeignKey("quality_alerts.id", ondelete="CASCADE"),
        nullable=False,
    )
    action = Column(String(32), nullable=False)
    from_status = Column(String(16), nullable=True)
    to_status = Column(String(16), nullable=True)
    actor_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    note = Column(Text, nullable=True)
    # 处置表单快照：类型/原因/措施/停机/返工/扩大检查标记
    form_snapshot = Column(JSON, nullable=True)
    # 处置单快照（E07）：当时生效的 SOP 版本、SPC 基线版本、模型版本与
    # 判据链当时结果——不可变，后续变更不改写（路线 B1-02 验收口径）
    snapshot = Column(JSON, nullable=True)
    created_at = Column(DateTime, nullable=False, server_default=func.now())


class QualitySop(Base):
    __tablename__ = "quality_sops"
    __table_args__ = (
        Index("ix_quality_sops_project_code", "project_id", "code"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id = Column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    scene_id = Column(
        UUID(as_uuid=True),
        ForeignKey("quality_scenes.id", ondelete="SET NULL"),
        nullable=True,
    )
    code = Column(String(64), nullable=False)
    version = Column(Integer, nullable=False, default=1)
    title = Column(String(256), nullable=False)
    # 三类处置指引 {spec_exceed: [...], spc_exceed: [...], ai_risk: [...]}
    content = Column(JSON, nullable=False, default=dict)
    # 适用工况（空=全工况；路线 E07「按编号、适用工况、生效时间版本化」）
    condition_value = Column(String(128), nullable=True)
    effective_from = Column(DateTime, nullable=False, server_default=func.now())
    # 同 code+工况新版本生效时置为当前时间（当时生效查询口径见服务层）
    retired_at = Column(DateTime, nullable=True)
    created_by_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    updated_at = Column(DateTime, nullable=False, server_default=func.now(), onupdate=func.now())


class QualitySpcBaseline(Base):
    __tablename__ = "quality_spc_baselines"
    __table_args__ = (
        Index(
            "ix_quality_spc_baselines_key",
            "scene_id",
            "station_id",
            "condition_value",
            "field",
            "is_active",
        ),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id = Column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    scene_id = Column(
        UUID(as_uuid=True),
        ForeignKey("quality_scenes.id", ondelete="CASCADE"),
        nullable=False,
    )
    station_id = Column(
        UUID(as_uuid=True),
        ForeignKey("quality_stations.id", ondelete="SET NULL"),
        nullable=True,
    )
    condition_value = Column(String(128), nullable=True)
    field = Column(String(256), nullable=False)
    statistic = Column(String(16), nullable=False, default="value")

    # I-MR 口径（E08）：中心=均值，σ=平均移动极差/1.128；控制限=中心±3σ
    center = Column(Float, nullable=False)
    sigma = Column(Float, nullable=False)
    sample_count = Column(Integer, nullable=False)
    window_start = Column(DateTime, nullable=False)
    window_end = Column(DateTime, nullable=False)
    # 引用事件序号口径（路线 E08 验收：所引用的事件序号可追溯）
    reference = Column(JSON, nullable=False, default=dict)

    version = Column(Integer, nullable=False, default=1)
    # 重新冻结生成新版本并置同键旧版本为失效；旧行保留可查（路线 E08 验收）
    is_active = Column(Boolean, nullable=False, default=True)
    created_by_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at = Column(DateTime, nullable=False, server_default=func.now())


class ModelEvidenceCheck(Base):
    __tablename__ = "model_evidence_checks"
    __table_args__ = (
        Index("ix_model_evidence_checks_version", "model_version_id", "created_at"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    model_version_id = Column(
        UUID(as_uuid=True),
        ForeignKey("model_versions.id", ondelete="CASCADE"),
        nullable=False,
    )
    # 上线检查五项结果（E21/D24）：模型文件/校验和/数据版本/评估完整性/生产版本唯一
    checks = Column(JSON, nullable=False, default=dict)
    # 12 环节三态快照（导出证据包时随包留档）
    summary = Column(JSON, nullable=True)
    created_by_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at = Column(DateTime, nullable=False, server_default=func.now())
