"""Persisted pipeline schedules and their idempotent occurrences."""

import uuid

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.database import Base


class PipelineSchedule(Base):
    __tablename__ = "pipeline_schedules"
    __table_args__ = (Index("ix_pipeline_schedules_due", "enabled", "next_run_at"),)

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    workflow_id = Column(UUID(as_uuid=True), ForeignKey("workflows.id", ondelete="CASCADE"), nullable=False)
    name = Column(String(128), nullable=False)
    cron_expression = Column(String(128), nullable=False)
    timezone = Column(String(64), nullable=False, default="UTC")
    enabled = Column(Boolean, nullable=False, default=True)
    paused_at = Column(DateTime, nullable=True)
    max_concurrency = Column(Integer, nullable=False, default=1)
    dependencies = Column(JSON, nullable=False, default=list)
    retry_policy = Column(JSON, nullable=False, default=dict)
    timeout_seconds = Column(Integer, nullable=True)
    workflow_version = Column(Integer, nullable=True)
    next_run_at = Column(DateTime, nullable=False)
    last_run_at = Column(DateTime, nullable=True)
    last_error_code = Column(String(64), nullable=True)
    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    occurrences = relationship(
        "PipelineScheduleRun",
        back_populates="schedule",
        cascade="all, delete-orphan",
    )
    workflow = relationship("Workflow")


class PipelineScheduleRun(Base):
    __tablename__ = "pipeline_schedule_runs"
    __table_args__ = (
        UniqueConstraint(
            "schedule_id",
            "scheduled_for",
            name="uq_pipeline_schedule_runs_schedule_time",
        ),
        Index("ix_pipeline_schedule_runs_history", "schedule_id", "scheduled_for"),
        Index("ix_pipeline_schedule_runs_retry", "status", "next_attempt_at"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    schedule_id = Column(
        UUID(as_uuid=True),
        ForeignKey("pipeline_schedules.id", ondelete="CASCADE"),
        nullable=False,
    )
    workflow_run_id = Column(
        UUID(as_uuid=True),
        ForeignKey("workflow_runs.id", ondelete="SET NULL"),
        nullable=True,
    )
    scheduled_for = Column(DateTime, nullable=False)
    claimed_at = Column(DateTime, nullable=True)
    next_attempt_at = Column(DateTime, nullable=True)
    finished_at = Column(DateTime, nullable=True)
    status = Column(String(16), nullable=False, default="pending")
    attempt = Column(Integer, nullable=False, default=1)
    skip_reason = Column(String(64), nullable=True)
    error_code = Column(String(64), nullable=True)
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime, server_default=func.now())

    schedule = relationship("PipelineSchedule", back_populates="occurrences")
    workflow_run = relationship("WorkflowRun")
