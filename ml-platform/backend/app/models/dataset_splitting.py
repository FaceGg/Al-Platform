"""Dataset split management + modeling rounds + blind-test ledger (补齐路线第二批 S2a, B2-G1).

划分管理从零建（更正 C3：平台此前无划分管理，automl_search 硬编码 20%/seed42）。
兼容红线：默认训练路径零变化——split 仅在训练契约显式传 dataset_split_id 时生效；
盲测段永不进训练（S2b 发布终验/不回退才消费）。
入库即定永不重分（E04）：数据集版本表组不可变，划分归属存独立成员表，
创建后无任何修改端点；轮次创建即锁定（路线「建模轮次开始时锁定」）。
"""
import uuid

from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
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

SPLIT_STRATEGIES = ("random_stratified", "group", "temporal")
SPLIT_ROLES = ("development", "blind")
ROUND_STATUSES = ("open", "locked", "closed")
BLIND_PURPOSES = ("release_final_validation", "no_regression_check", "other")

# 每轮盲测评估次数上限默认值（E03：防「在盲测集上试到过为止」）
DEFAULT_BLIND_EVAL_CAP = 2


class DatasetSplit(Base):
    __tablename__ = "dataset_splits"
    __table_args__ = (
        CheckConstraint(
            "strategy IN ('random_stratified', 'group', 'temporal')",
            name="ck_dataset_splits_strategy",
        ),
        Index("ix_dataset_splits_project_version", "project_id", "dataset_version_id"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id = Column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
    )
    # 数据集版本 id 不加 FK：版本表组整组不可变（models/data_version.py 触发器），
    # 划分不应参与其级联生命周期
    dataset_version_id = Column(UUID(as_uuid=True), nullable=False)
    name = Column(String(128), nullable=False)
    strategy = Column(String(16), nullable=False, default="random_stratified")
    params = Column(JSON, nullable=False, default=dict)
    split_fingerprint = Column(String(64), nullable=False)
    created_by_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at = Column(DateTime, nullable=False, server_default=func.now())


class DatasetSplitMember(Base):
    __tablename__ = "dataset_split_members"
    __table_args__ = (
        UniqueConstraint("split_id", "row_index", name="uq_split_members_row"),
        Index("ix_split_members_role", "split_id", "role"),
        CheckConstraint(
            "role IN ('development', 'blind')",
            name="ck_split_members_role",
        ),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    split_id = Column(
        UUID(as_uuid=True),
        ForeignKey("dataset_splits.id", ondelete="CASCADE"),
        nullable=False,
    )
    row_index = Column(Integer, nullable=False)
    sample_key = Column(String(256), nullable=True)
    role = Column(String(16), nullable=False)


class ModelingRound(Base):
    __tablename__ = "modeling_rounds"
    __table_args__ = (
        CheckConstraint(
            "status IN ('open', 'locked', 'closed')",
            name="ck_modeling_rounds_status",
        ),
        Index("ix_modeling_rounds_project_status", "project_id", "status"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id = Column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
    )
    dataset_version_id = Column(UUID(as_uuid=True), nullable=False)
    split_id = Column(
        UUID(as_uuid=True),
        ForeignKey("dataset_splits.id", ondelete="CASCADE"),
        nullable=False,
    )
    status = Column(String(16), nullable=False, default="locked")
    blind_eval_count = Column(Integer, nullable=False, default=0)
    blind_eval_cap = Column(Integer, nullable=False, default=DEFAULT_BLIND_EVAL_CAP)
    blind_fingerprint = Column(String(64), nullable=True)
    locked_at = Column(DateTime, nullable=False, server_default=func.now())
    closed_at = Column(DateTime, nullable=True)
    created_by_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    updated_at = Column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now()
    )


class BlindTestUsage(Base):
    __tablename__ = "blind_test_usages"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id = Column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
    )
    round_id = Column(
        UUID(as_uuid=True),
        ForeignKey("modeling_rounds.id", ondelete="CASCADE"),
        nullable=False,
    )
    split_id = Column(
        UUID(as_uuid=True),
        ForeignKey("dataset_splits.id", ondelete="CASCADE"),
        nullable=False,
    )
    purpose = Column(String(32), nullable=False, default="other")
    sample_count = Column(Integer, nullable=False, default=0)
    samples_fingerprint = Column(String(64), nullable=False)
    ref = Column(JSON, nullable=True)
    note = Column(String(256), nullable=True)
    used_by_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    used_at = Column(DateTime, nullable=False, server_default=func.now())
