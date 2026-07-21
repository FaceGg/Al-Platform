"""Immutable model registry versions and inference deployments."""

import uuid

from sqlalchemy import (
    JSON,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.database import Base


MODEL_SOURCE_KINDS = ("platform_joblib", "onnx_artifact")
APPROVAL_STATES = ("pending", "approved", "rejected", "archived")
DESIRED_STATES = ("stopped", "running")
OBSERVED_STATES = ("stopped", "starting", "running", "stopping", "failed")
REVISION_STRATEGIES = ("immediate", "canary", "rolling")
REVISION_STATES = ("draft", "candidate", "stable", "superseded", "failed")
ROLLOUT_STATES = (
    "pending",
    "preloading",
    "progressing",
    "paused",
    "completed",
    "failed",
    "rolled_back",
)


class RegisteredModel(Base):
    __tablename__ = "registered_models"
    __table_args__ = (
        UniqueConstraint(
            "project_id",
            "name",
            name="uq_registered_models_project_name",
        ),
        Index(
            "ix_registered_models_project_created",
            "project_id",
            "created_at",
        ),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id = Column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
    )
    name = Column(String(128), nullable=False)
    description = Column(Text, nullable=False, default="")
    created_by_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    updated_at = Column(
        DateTime,
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    versions = relationship(
        "ModelVersion",
        back_populates="registered_model",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class ModelVersion(Base):
    __tablename__ = "model_versions"
    __table_args__ = (
        UniqueConstraint(
            "registered_model_id",
            "version_number",
            name="uq_model_versions_model_number",
        ),
        CheckConstraint(
            "source_kind IN ('platform_joblib', 'onnx_artifact')",
            name="ck_model_versions_source_kind",
        ),
        CheckConstraint(
            "approval_status IN ('pending', 'approved', 'rejected', 'archived')",
            name="ck_model_versions_approval_status",
        ),
        CheckConstraint(
            "(source_kind = 'platform_joblib' AND source_model_library_id IS NOT NULL) "
            "OR (source_kind = 'onnx_artifact' AND source_model_library_id IS NULL)",
            name="ck_model_versions_source_reference",
        ),
        CheckConstraint(
            "version_number > 0",
            name="ck_model_versions_positive_number",
        ),
        Index(
            "ix_model_versions_model_created",
            "registered_model_id",
            "created_at",
        ),
        Index(
            "ix_model_versions_approval_created",
            "approval_status",
            "created_at",
        ),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    registered_model_id = Column(
        UUID(as_uuid=True),
        ForeignKey("registered_models.id", ondelete="CASCADE"),
        nullable=False,
    )
    version_number = Column(Integer, nullable=False)
    source_kind = Column(String(32), nullable=False)
    source_model_library_id = Column(
        UUID(as_uuid=True),
        ForeignKey("model_library.id", deferrable=True, initially="DEFERRED"),
        nullable=True,
    )
    source_artifact_id = Column(
        UUID(as_uuid=True),
        ForeignKey("artifacts.id", deferrable=True, initially="DEFERRED"),
        nullable=False,
    )
    onnx_artifact_id = Column(
        UUID(as_uuid=True),
        ForeignKey("artifacts.id", deferrable=True, initially="DEFERRED"),
        nullable=False,
    )
    framework = Column(String(64), nullable=False, default="")
    algorithm = Column(String(128), nullable=False, default="")
    feature_schema = Column(JSON, nullable=False, default=list)
    output_schema = Column(JSON, nullable=False, default=dict)
    metrics = Column(JSON, nullable=False, default=dict)
    conversion_metadata = Column(JSON, nullable=False, default=dict)
    approval_status = Column(String(16), nullable=False, default="pending")
    approval_comment = Column(Text, nullable=False, default="")
    approved_by_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    approved_at = Column(DateTime, nullable=True)
    created_by_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at = Column(DateTime, nullable=False, server_default=func.now())

    registered_model = relationship("RegisteredModel", back_populates="versions")


class InferenceDeployment(Base):
    __tablename__ = "inference_deployments"
    __table_args__ = (
        UniqueConstraint(
            "project_id",
            "name",
            name="uq_inference_deployments_project_name",
        ),
        CheckConstraint(
            "desired_state IN ('stopped', 'running')",
            name="ck_inference_deployments_desired_state",
        ),
        CheckConstraint(
            "observed_state IN ('stopped', 'starting', 'running', 'stopping', 'failed')",
            name="ck_inference_deployments_observed_state",
        ),
        Index(
            "ix_inference_deployments_project_state",
            "project_id",
            "observed_state",
        ),
        Index(
            "ix_inference_deployments_desired_checked",
            "desired_state",
            "last_checked_at",
        ),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id = Column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
    )
    name = Column(String(128), nullable=False)
    model_version_id = Column(
        UUID(as_uuid=True),
        ForeignKey("model_versions.id", deferrable=True, initially="DEFERRED"),
        nullable=False,
    )
    desired_state = Column(String(16), nullable=False, default="stopped")
    observed_state = Column(String(16), nullable=False, default="stopped")
    last_error_code = Column(String(64), nullable=True)
    last_checked_at = Column(DateTime, nullable=True)
    started_at = Column(DateTime, nullable=True)
    stopped_at = Column(DateTime, nullable=True)
    created_by_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    updated_at = Column(
        DateTime,
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    model_version = relationship("ModelVersion")


class DeploymentRevision(Base):
    __tablename__ = "deployment_revisions"
    __table_args__ = (
        UniqueConstraint(
            "deployment_id",
            "revision_number",
            name="uq_deployment_revisions_number",
        ),
        CheckConstraint(
            "revision_number > 0",
            name="ck_deployment_revisions_positive_number",
        ),
        CheckConstraint(
            "strategy IN ('immediate', 'canary', 'rolling')",
            name="ck_deployment_revisions_strategy",
        ),
        CheckConstraint(
            "status IN ('draft', 'candidate', 'stable', 'superseded', 'failed')",
            name="ck_deployment_revisions_status",
        ),
        Index(
            "ix_deployment_revisions_deployment_status",
            "deployment_id",
            "status",
        ),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    deployment_id = Column(
        UUID(as_uuid=True),
        ForeignKey("inference_deployments.id", ondelete="CASCADE"),
        nullable=False,
    )
    revision_number = Column(Integer, nullable=False)
    strategy = Column(String(16), nullable=False)
    status = Column(String(16), nullable=False, default="draft")
    created_by_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    activated_at = Column(DateTime, nullable=True)

    deployment = relationship("InferenceDeployment")
    targets = relationship(
        "DeploymentTarget",
        back_populates="revision",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class DeploymentTarget(Base):
    __tablename__ = "deployment_targets"
    __table_args__ = (
        UniqueConstraint(
            "revision_id",
            "model_version_id",
            name="uq_deployment_targets_revision_model",
        ),
        CheckConstraint(
            "weight_bps >= 0 AND weight_bps <= 10000",
            name="ck_deployment_targets_weight",
        ),
        CheckConstraint(
            "role IN ('stable', 'candidate')",
            name="ck_deployment_targets_role",
        ),
        Index("ix_deployment_targets_model_version", "model_version_id"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    revision_id = Column(
        UUID(as_uuid=True),
        ForeignKey("deployment_revisions.id", ondelete="CASCADE"),
        nullable=False,
    )
    model_version_id = Column(
        UUID(as_uuid=True),
        ForeignKey("model_versions.id", deferrable=True, initially="DEFERRED"),
        nullable=False,
    )
    weight_bps = Column(Integer, nullable=False)
    role = Column(String(16), nullable=False)

    revision = relationship("DeploymentRevision", back_populates="targets")
    model_version = relationship("ModelVersion")


class DeploymentRollout(Base):
    __tablename__ = "deployment_rollouts"
    __table_args__ = (
        CheckConstraint(
            "state IN ('pending', 'preloading', 'progressing', 'paused', "
            "'completed', 'failed', 'rolled_back')",
            name="ck_deployment_rollouts_state",
        ),
        CheckConstraint(
            "current_step >= 0",
            name="ck_deployment_rollouts_current_step",
        ),
        CheckConstraint(
            "lock_version > 0",
            name="ck_deployment_rollouts_lock_version",
        ),
        Index(
            "uq_deployment_rollouts_active",
            "deployment_id",
            unique=True,
            postgresql_where=text(
                "state IN ('pending', 'preloading', 'progressing', 'paused')"
            ),
            sqlite_where=text(
                "state IN ('pending', 'preloading', 'progressing', 'paused')"
            ),
        ),
        Index(
            "ix_deployment_rollouts_deployment_created",
            "deployment_id",
            "created_at",
        ),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    deployment_id = Column(
        UUID(as_uuid=True),
        ForeignKey("inference_deployments.id", ondelete="CASCADE"),
        nullable=False,
    )
    from_revision_id = Column(
        UUID(as_uuid=True),
        ForeignKey(
            "deployment_revisions.id",
            deferrable=True,
            initially="DEFERRED",
        ),
        nullable=True,
    )
    to_revision_id = Column(
        UUID(as_uuid=True),
        ForeignKey(
            "deployment_revisions.id",
            deferrable=True,
            initially="DEFERRED",
        ),
        nullable=False,
    )
    state = Column(String(16), nullable=False, default="pending")
    current_step = Column(Integer, nullable=False, default=0)
    lock_version = Column(Integer, nullable=False, default=1)
    step_schedule = Column(JSON, nullable=False, default=list)
    thresholds = Column(JSON, nullable=False, default=dict)
    last_error_code = Column(String(64), nullable=True)
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    started_at = Column(DateTime, nullable=True)
    updated_at = Column(
        DateTime,
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
    completed_at = Column(DateTime, nullable=True)

    deployment = relationship("InferenceDeployment")
    from_revision = relationship(
        "DeploymentRevision",
        foreign_keys=[from_revision_id],
    )
    to_revision = relationship(
        "DeploymentRevision",
        foreign_keys=[to_revision_id],
    )


class InferenceApiKey(Base):
    __tablename__ = "inference_api_keys"
    __table_args__ = (
        CheckConstraint(
            "length(prefix) = 12",
            name="ck_inference_api_keys_prefix_length",
        ),
        Index(
            "ix_inference_api_keys_deployment_prefix",
            "deployment_id",
            "prefix",
            unique=True,
        ),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    deployment_id = Column(
        UUID(as_uuid=True),
        ForeignKey("inference_deployments.id", ondelete="CASCADE"),
        nullable=False,
    )
    prefix = Column(String(12), nullable=False)
    secret_hash = Column(String(512), nullable=False)
    scopes = Column(JSON, nullable=False, default=list)
    expires_at = Column(DateTime, nullable=True)
    revoked_at = Column(DateTime, nullable=True)
    last_used_at = Column(DateTime, nullable=True)
    created_by_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at = Column(DateTime, nullable=False, server_default=func.now())

    deployment = relationship("InferenceDeployment")


class InferenceRequestLog(Base):
    __tablename__ = "inference_request_logs"
    __table_args__ = (
        UniqueConstraint(
            "request_id",
            name="uq_inference_request_logs_request_id",
        ),
        CheckConstraint(
            "status IN ('success', 'error', 'limited')",
            name="ck_inference_request_logs_status",
        ),
        Index(
            "ix_inference_request_logs_deployment_occurred",
            "deployment_id",
            "occurred_at",
        ),
        Index("ix_inference_request_logs_expires", "expires_at"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    request_id = Column(String(128), nullable=False)
    deployment_id = Column(
        UUID(as_uuid=True),
        ForeignKey("inference_deployments.id", ondelete="CASCADE"),
        nullable=False,
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
    api_key_id = Column(
        UUID(as_uuid=True),
        ForeignKey("inference_api_keys.id", ondelete="SET NULL"),
        nullable=True,
    )
    batch_size = Column(Integer, nullable=False)
    duration_ms = Column(Integer, nullable=False)
    status = Column(String(16), nullable=False, default="success")
    error_code = Column(String(64), nullable=True)
    occurred_at = Column(DateTime, nullable=False)
    expires_at = Column(DateTime, nullable=False)

    deployment = relationship("InferenceDeployment")
    revision = relationship("DeploymentRevision")
    model_version = relationship("ModelVersion")
    api_key = relationship("InferenceApiKey")


class InferenceMetricBucket(Base):
    __tablename__ = "inference_metric_buckets"
    __table_args__ = (
        Index(
            "uq_inference_metric_buckets_deployment_minute",
            "deployment_id",
            "bucket_start",
            unique=True,
        ),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    deployment_id = Column(
        UUID(as_uuid=True),
        ForeignKey("inference_deployments.id", ondelete="CASCADE"),
        nullable=False,
    )
    bucket_start = Column(DateTime, nullable=False)
    request_count = Column(Integer, nullable=False, default=0)
    success_count = Column(Integer, nullable=False, default=0)
    error_count = Column(Integer, nullable=False, default=0)
    limited_count = Column(Integer, nullable=False, default=0)
    load_failure_count = Column(Integer, nullable=False, default=0)
    batch_size_sum = Column(Integer, nullable=False, default=0)
    latency_sum_ms = Column(Integer, nullable=False, default=0)
    latency_max_ms = Column(Integer, nullable=False, default=0)
    latency_buckets = Column(JSON, nullable=False, default=dict)
    traffic_weights = Column(JSON, nullable=False, default=dict)

    deployment = relationship("InferenceDeployment")


class ModelCard(Base):
    __tablename__ = "model_cards"
    __table_args__ = (
        UniqueConstraint(
            "model_version_id",
            name="uq_model_cards_model_version",
        ),
        Index("ix_model_cards_release_status", "release_status"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    model_version_id = Column(
        UUID(as_uuid=True),
        ForeignKey("model_versions.id", ondelete="CASCADE"),
        nullable=False,
    )
    training_data_lineage = Column(JSON, nullable=False, default=dict)
    source_artifact_ids = Column(JSON, nullable=False, default=list)
    input_schema = Column(JSON, nullable=False, default=list)
    output_schema = Column(JSON, nullable=False, default=dict)
    metrics = Column(JSON, nullable=False, default=dict)
    approval_history = Column(JSON, nullable=False, default=list)
    approval_status = Column(String(16), nullable=False, default="pending")
    release_status = Column(String(16), nullable=False, default="unreleased")
    risk_notes = Column(Text, nullable=False, default="")
    intended_use = Column(String(4000), nullable=False, default="")
    limitations = Column(String(4000), nullable=False, default="")
    operational_guidance = Column(Text, nullable=False, default="")
    guidance_revision = Column(Integer, nullable=False, default=1)
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    updated_at = Column(
        DateTime,
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    model_version = relationship("ModelVersion")
