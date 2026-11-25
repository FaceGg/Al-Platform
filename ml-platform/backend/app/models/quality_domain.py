"""Quality domain models: scene / station / spec-limit (补齐路线 B1-10).

领域模型（计划 §10.4.4）：项目 → 场景 → 工位 → 设备。
- 场景（QualityScene）是项目下的一类工序质量业务：权限继承项目、
  一个场景对应一个部署（可先建后绑）、字段角色存场景配置而非列定义表
  （数据集版本表组不可变，更正 C16）。
- 工位（QualityStation）是场景下的实体；工厂/车间/产线是工位上的
  归属字典字段（非实体）；设备复用既有边缘设备表（更正 C15）。
- 规格定义（QualitySpecLimit）是 E27 的单一来源：字段 + 波形统计量
  （值/均值/最小/最大/RMS）+ 上下限 + 单位；B1-02 判据引擎与 B1-06
  能力指数在各自阶段接读侧，不在本批。

设备影子两列（shadow_desired/shadow_reported）落在 EdgeDevice 上
（诚实设计⑤预留，B4-02 正式落地），见 models/compute.py。

外部数据源绑定列（data_source_id）随 _107 建表后同批加入（建表与
外键约束必须同迁移，避免跨迁移悬空引用）。
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
    JSON,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID

from app.database import Base


# field_roles 合法角色键（技术方案 §2.1）；值=列名。
# P1 训练排除挂钩消费：ignore + 非目标占用列进 excluded_columns。
FIELD_ROLE_KEYS = frozenset({
    "sample_key",
    "product",
    "batch",
    "shift",
    "collected_at",
    "time",
    "group",
    "target",
    "feature",
    "ignore",
    "waveform",
    "condition",
})

# 规格统计量枚举（E27 波形统计量口径）；DB CHECK 与 pydantic 双层约束
SPEC_STATISTICS = ("value", "mean", "min", "max", "rms")


class QualityScene(Base):
    __tablename__ = "quality_scenes"
    __table_args__ = (
        UniqueConstraint(
            "project_id",
            "code",
            name="uq_quality_scenes_project_code",
        ),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id = Column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    code = Column(String(64), nullable=False)
    name = Column(String(128), nullable=False)
    description = Column(Text, nullable=True)
    # 一场景一部署；场景可先建后绑（SET NULL：部署删除不拖垮场景）
    deployment_id = Column(
        UUID(as_uuid=True),
        ForeignKey("inference_deployments.id", ondelete="SET NULL"),
        nullable=True,
    )
    # 场景声明的路由键；绑定部署时须与部署的 condition_column 一致（API 层校验）
    condition_column = Column(String(128), nullable=True)
    # 角色映射 {role: 列名}，role ∈ FIELD_ROLE_KEYS
    field_roles = Column(JSON, nullable=False, default=dict)
    # 波形列声明（供 B1-02 曲线叠加把关，F2a 消费）
    waveform_column = Column(String(256), nullable=True)
    created_by_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())


class QualityStation(Base):
    __tablename__ = "quality_stations"
    __table_args__ = (
        UniqueConstraint(
            "scene_id",
            "code",
            name="uq_quality_stations_scene_code",
        ),
        # 驾驶舱四级联动（F3）的范围筛选路径
        Index(
            "ix_quality_stations_location",
            "factory",
            "workshop",
            "production_line",
        ),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    scene_id = Column(
        UUID(as_uuid=True),
        ForeignKey("quality_scenes.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    code = Column(String(64), nullable=False)
    name = Column(String(128), nullable=False)
    description = Column(Text, nullable=True)
    factory = Column(String(128), nullable=True)
    workshop = Column(String(128), nullable=True)
    production_line = Column(String(128), nullable=True)
    # 设备绑定（复用边缘设备表，更正 C15）；绑定关系放工位侧最小且可重绑（D6）
    edge_device_id = Column(
        UUID(as_uuid=True),
        ForeignKey("edge_devices.id", ondelete="SET NULL"),
        nullable=True,
    )
    # 工位责任人（B1-01 确认防呆、B2-G2 预授权的基础）
    responsible_user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    enabled = Column(Boolean, nullable=False, default=True)
    created_by_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())


class QualitySpecLimit(Base):
    __tablename__ = "quality_spec_limits"
    __table_args__ = (
        # 同一字段与统计量只能有一条规格（路线 B1-10 验收口径）
        UniqueConstraint(
            "scene_id",
            "field",
            "statistic",
            name="uq_quality_spec_limits_scene_field_statistic",
        ),
        CheckConstraint(
            "statistic IN ('value', 'mean', 'min', 'max', 'rms')",
            name="ck_quality_spec_limits_statistic",
        ),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    scene_id = Column(
        UUID(as_uuid=True),
        ForeignKey("quality_scenes.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # 规格目标：数值特征列或波形列名
    field = Column(String(256), nullable=False)
    statistic = Column(String(16), nullable=False, default="value")
    usl = Column(Float, nullable=True)
    lsl = Column(Float, nullable=True)
    target = Column(Float, nullable=True)
    unit = Column(String(32), nullable=True)
    created_by_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
