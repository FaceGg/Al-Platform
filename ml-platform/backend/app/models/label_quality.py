"""Label quality models (补齐路线第二批 S3, B2-05/B2-06/B2-G4/E15).

主动学习选样运行 / 一致性轮与逐标注员盲标通道（并行通道——门户单通道零
改动，§12.13）/ 仲裁队列 / 伪标签批与凭证（红线：伪标签永不进开发验证
与独立盲测）。
"""
import uuid

from sqlalchemy import (
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

# B2-05 九策略（hybrid 按权重混合；random 为基线）
ACTIVE_LEARNING_STRATEGIES = (
    "entropy",
    "margin",
    "least_confidence",
    "cluster_diversity",
    "boundary",
    "rarity",
    "diversity",
    "business_priority",
    "random",
    "hybrid",
)

ROUND_STATUSES = ("open", "completed", "arbitrated")
ARBITRATION_STATUSES = ("pending", "decided")


class ActiveLearningSelection(Base):
    __tablename__ = "active_learning_selections"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id = Column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
    )
    task_id = Column(UUID(as_uuid=True), nullable=True)
    model_version_id = Column(UUID(as_uuid=True), nullable=True)
    strategy = Column(JSON, nullable=False, default=dict)
    budget_initial = Column(Integer, nullable=False, default=0)
    budget_per_round = Column(Integer, nullable=False, default=0)
    selected_sample_ids = Column(JSON, nullable=False, default=list)
    strategy_stats = Column(JSON, nullable=False, default=dict)
    fingerprint = Column(String(64), nullable=False)
    created_by_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at = Column(DateTime, nullable=False, server_default=func.now())


class ConsistencyRound(Base):
    __tablename__ = "consistency_rounds"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id = Column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
    )
    task_id = Column(UUID(as_uuid=True), nullable=True)
    label_schema_id = Column(UUID(as_uuid=True), nullable=True)
    annotator_subject_ids = Column(JSON, nullable=False, default=list)
    sample_ids = Column(JSON, nullable=False, default=list)
    status = Column(String(16), nullable=False, default="open")
    kappa_pairwise = Column(JSON, nullable=True)
    kappa_average = Column(Float, nullable=True)
    kappa_threshold = Column(Float, nullable=False, default=0.6)
    created_by_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at = Column(DateTime, nullable=False, server_default=func.now())


class AnnotationBlindLabel(Base):
    __tablename__ = "annotation_blind_labels"
    __table_args__ = (
        UniqueConstraint(
            "round_id", "subject_id", "sample_id",
            name="uq_blind_labels_round_subject_sample",
        ),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    round_id = Column(
        UUID(as_uuid=True),
        ForeignKey("consistency_rounds.id", ondelete="CASCADE"),
        nullable=False,
    )
    subject_id = Column(String(128), nullable=False)
    sample_id = Column(String(128), nullable=False)
    values = Column(JSON, nullable=False, default=dict)
    created_at = Column(DateTime, nullable=False, server_default=func.now())


class LabelArbitration(Base):
    __tablename__ = "label_arbitrations"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'decided')",
            name="ck_label_arbitrations_status",
        ),
        Index("ix_label_arbitrations_round_status", "round_id", "status"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    round_id = Column(
        UUID(as_uuid=True),
        ForeignKey("consistency_rounds.id", ondelete="CASCADE"),
        nullable=False,
    )
    sample_id = Column(String(128), nullable=False)
    conflict = Column(JSON, nullable=False, default=dict)
    decision_values = Column(JSON, nullable=True)
    decision_note = Column(String(256), nullable=True)
    arbiter_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    status = Column(String(16), nullable=False, default="pending")
    decided_at = Column(DateTime, nullable=True)


class PseudoLabelBatch(Base):
    __tablename__ = "pseudo_label_batches"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id = Column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
    )
    dataset_version_id = Column(UUID(as_uuid=True), nullable=True)
    model_version_id = Column(UUID(as_uuid=True), nullable=True)
    threshold = Column(Float, nullable=False, default=0.9)
    per_class_quota = Column(JSON, nullable=False, default=dict)
    selected = Column(JSON, nullable=False, default=list)
    dev_comparison = Column(JSON, nullable=True)
    winner = Column(Integer, nullable=False, default=0)
    credential_fingerprint = Column(String(64), nullable=False)
    created_by_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at = Column(DateTime, nullable=False, server_default=func.now())
