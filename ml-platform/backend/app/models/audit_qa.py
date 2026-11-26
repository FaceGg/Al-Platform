"""Audit QA + model trust models (补齐路线第二批 S4, B2-01/B2-04)."""
import uuid

from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    JSON,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import UUID

from app.database import Base

REPORT_TEMPLATES = (
    "quality", "alerts", "spc", "drift", "model",
    "labeling", "agent_actions", "root_cause", "process_window", "disposition",
)


class AuditReport(Base):
    __tablename__ = "audit_reports"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id = Column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
    )
    template_key = Column(String(32), nullable=False)
    params = Column(JSON, nullable=False, default=dict)
    content_markdown = Column(Text, nullable=False, default="")
    evidence = Column(JSON, nullable=False, default=list)
    citation_errors = Column(JSON, nullable=False, default=list)
    status = Column(String(16), nullable=False, default="draft")
    created_by_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at = Column(DateTime, nullable=False, server_default=func.now())


class ModelTrustScore(Base):
    __tablename__ = "model_trust_scores"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    model_version_id = Column(UUID(as_uuid=True), nullable=False)
    project_id = Column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
    )
    score = Column(Float, nullable=False)
    grade = Column(String(1), nullable=False)
    factors = Column(JSON, nullable=False, default=dict)
    computed_by_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    computed_at = Column(DateTime, nullable=False, server_default=func.now())

    __table_args__ = (
        CheckConstraint("grade IN ('A','B','C','D')", name="ck_model_trust_grade"),
        Index("ix_model_trust_version_time", "model_version_id", "computed_at"),
    )
