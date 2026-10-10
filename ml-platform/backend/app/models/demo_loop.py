"""Closed-loop demo models: inference → error data → alert → review → retrain → swap."""

import uuid

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    func,
)

from app.database import Base
from sqlalchemy.dialects.postgresql import UUID


class DemoLoopConfig(Base):
    __tablename__ = "demo_loop_configs"
    __table_args__ = (
        CheckConstraint("alert_threshold_rows >= 1", name="ck_demo_loop_alert_threshold"),
        Index("ix_demo_loop_configs_project_id", "project_id"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    name = Column(String(128), nullable=False, default="自动化闭环")
    deployment_id = Column(
        UUID(as_uuid=True),
        ForeignKey("inference_deployments.id", ondelete="SET NULL"),
        nullable=True,
    )
    # Predictions whose class lands in error_classes flow back into the error dataset.
    error_classes = Column(JSON, nullable=False, default=list)
    preprocess_enabled = Column(Boolean, nullable=False, default=False)
    # Alert fires every time error_count crosses a multiple of this threshold (1 = every row).
    alert_threshold_rows = Column(Integer, nullable=False, default=1)
    require_review = Column(Boolean, nullable=False, default=False)
    review_annotator_ids = Column(JSON, nullable=False, default=list)
    retrain_enabled = Column(Boolean, nullable=False, default=False)
    retrain_threshold_rows = Column(Integer, nullable=False, default=0)
    retrain_dataset_artifact_id = Column(
        UUID(as_uuid=True),
        ForeignKey("artifacts.id", ondelete="SET NULL"),
        nullable=True,
    )
    # Multi-dataset retrain selection (list of artifact ids); the legacy single
    # column above is kept in sync with the first entry for older readers.
    retrain_dataset_artifact_ids = Column(JSON, nullable=True, default=list)
    retrain_target_column = Column(String(128), nullable=False, default="")
    retrain_max_trials = Column(Integer, nullable=False, default=10)
    # Artifact that accumulates the error rows (kept without FK: it is created lazily).
    error_artifact_id = Column(UUID(as_uuid=True), nullable=True, index=True)
    error_count = Column(Integer, nullable=False, default=0)
    alert_count = Column(Integer, nullable=False, default=0)
    # Total rows inferred through this loop (normal + error), for monitoring.
    total_count = Column(Integer, nullable=False, default=0)
    review_task_id = Column(UUID(as_uuid=True), nullable=True)
    retrain_job_id = Column(UUID(as_uuid=True), nullable=True)
    retrain_status = Column(String(24), nullable=False, default="idle")
    swapped_model_version_id = Column(UUID(as_uuid=True), nullable=True)
    created_by_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)


class DemoLoopEvent(Base):
    __tablename__ = "demo_loop_events"
    __table_args__ = (Index("ix_demo_loop_events_config_created", "config_id", "created_at"),)

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    config_id = Column(
        UUID(as_uuid=True),
        ForeignKey("demo_loop_configs.id", ondelete="CASCADE"),
        nullable=False,
    )
    event_type = Column(String(32), nullable=False)
    severity = Column(String(16), nullable=False, default="info")
    message = Column(Text, nullable=False, default="")
    payload = Column(JSON, nullable=False, default=dict)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
