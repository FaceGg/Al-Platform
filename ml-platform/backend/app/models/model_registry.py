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
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.database import Base


MODEL_SOURCE_KINDS = ("platform_joblib", "onnx_artifact")
APPROVAL_STATES = ("pending", "approved", "rejected", "archived")
DESIRED_STATES = ("stopped", "running")
OBSERVED_STATES = ("stopped", "starting", "running", "stopping", "failed")


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
