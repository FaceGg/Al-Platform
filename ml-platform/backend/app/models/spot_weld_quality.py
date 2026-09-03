"""Legacy spot-weld persistence retained only as a migration/read adapter."""

LEGACY_ADAPTER_ONLY = True

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
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.database import Base


class SpotWeldQualityRun(Base):
    __tablename__ = "spot_weld_quality_runs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id = Column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    dataset_artifact_id = Column(
        UUID(as_uuid=True), ForeignKey("artifacts.id"), nullable=False, index=True,
    )
    created_by_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    status = Column(String(32), nullable=False, default="queued", index=True)
    field_mapping = Column(JSON, nullable=False, default=dict)
    feature_schema = Column(JSON, nullable=False, default=list)
    input_fingerprint = Column(JSON, nullable=False, default=dict)
    statistics = Column(JSON, nullable=False, default=dict)
    automl_results = Column(JSON, nullable=False, default=list)
    clustering_results = Column(JSON, nullable=False, default=dict)
    output_artifacts = Column(JSON, nullable=False, default=dict)
    rule_set_version = Column(String(64), nullable=False, default="report_v1")
    task_id = Column(String(128), nullable=True, index=True)
    worker_id = Column(String(128), nullable=True)
    error_code = Column(String(64), nullable=True)
    error_details = Column(JSON, nullable=False, default=dict)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)

    project = relationship("Project", backref="spot_weld_quality_runs")
    dataset_artifact = relationship("Artifact", foreign_keys=[dataset_artifact_id])
    created_by = relationship("User", foreign_keys=[created_by_id])
    samples = relationship(
        "SpotWeldQualitySample",
        back_populates="run",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class SpotWeldQualitySample(Base):
    __tablename__ = "spot_weld_quality_samples"
    __table_args__ = (
        UniqueConstraint(
            "run_id", "source_row_index",
            name="uq_spot_weld_quality_sample_run_row",
        ),
        Index("ix_spot_weld_quality_samples_run_review", "run_id", "review_status"),
        Index("ix_spot_weld_quality_samples_run_warning", "run_id", "warning_level"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    run_id = Column(
        UUID(as_uuid=True),
        ForeignKey("spot_weld_quality_runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    source_row_index = Column(Integer, nullable=False)
    display_id = Column(String(64), nullable=False)
    table_values = Column(JSON, nullable=False, default=dict)
    feature_values = Column(JSON, nullable=False, default=dict)
    waveforms = Column(JSON, nullable=False, default=dict)
    automatic_label = Column(String(64), nullable=True)
    current_label = Column(String(64), nullable=True)
    current_note = Column(Text, nullable=True)
    rule_hits = Column(JSON, nullable=False, default=list)
    cluster_id = Column(Integer, nullable=True)
    defect_probability = Column(Float, nullable=True)
    warning_level = Column(String(24), nullable=False, default="none")
    review_status = Column(String(24), nullable=False, default="pending_review")
    current_revision_id = Column(UUID(as_uuid=True), nullable=True)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)

    run = relationship("SpotWeldQualityRun", back_populates="samples")


class SpotWeldQualityRuleSet(Base):
    __tablename__ = "spot_weld_quality_rule_sets"
    __table_args__ = (
        UniqueConstraint("run_id", "version", name="uq_spot_weld_quality_rule_set_run_version"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id = Column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    run_id = Column(
        UUID(as_uuid=True),
        ForeignKey("spot_weld_quality_runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    version = Column(String(64), nullable=False, default="report_v1")
    thresholds = Column(JSON, nullable=False, default=dict)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)


class SpotWeldLabelRevision(Base):
    __tablename__ = "spot_weld_label_revisions"
    __table_args__ = (
        Index("ix_spot_weld_label_revisions_sample_created", "sample_id", "created_at"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id = Column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    run_id = Column(
        UUID(as_uuid=True),
        ForeignKey("spot_weld_quality_runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    sample_id = Column(
        UUID(as_uuid=True),
        ForeignKey("spot_weld_quality_samples.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    author_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    label = Column(String(64), nullable=False)
    note = Column(Text, nullable=True)
    action = Column(String(24), nullable=False, default="submitted")
    decision = Column(String(24), nullable=True)
    review_comment = Column(Text, nullable=True)
    parent_revision_id = Column(UUID(as_uuid=True), nullable=True)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)


class SpotWeldLabelSnapshot(Base):
    __tablename__ = "spot_weld_label_snapshots"
    __table_args__ = (
        UniqueConstraint("run_id", "name", name="uq_spot_weld_label_snapshot_run_name"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id = Column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    run_id = Column(
        UUID(as_uuid=True),
        ForeignKey("spot_weld_quality_runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    created_by_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    name = Column(String(128), nullable=False, default="approved-labels")
    labels = Column(JSON, nullable=False, default=list)
    label_counts = Column(JSON, nullable=False, default=dict)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
