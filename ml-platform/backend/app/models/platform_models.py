"""Dataset, annotation, and orchestration app ORM models."""
import uuid
from sqlalchemy import Column, String, Text, Float, DateTime, JSON, Boolean, ForeignKey, Integer, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from app.database import Base


class Dataset(Base):
    __tablename__ = "datasets"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(256), nullable=False)
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id"), nullable=True)
    owner_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    dataset_type = Column(String(32), default="training")  # training, test, validation
    data_modality = Column(String(32), default="image")  # image, text, audio, tabular
    algorithm_type = Column(String(64), default="")  # classification, detection, segmentation
    version = Column(String(32), default="v1")
    status = Column(String(32), default="pending")  # pending, importing, ready, processing
    description = Column(Text, default="")
    sample_count = Column(Integer, default=0)
    labeled_count = Column(Integer, default=0)
    file_path = Column(String(512), default="")
    format = Column(String(32), default="")
    labels = Column(JSON, default=list)
    stats = Column(JSON, default=dict)  # class distribution, etc.
    tags = Column(JSON, default=list)
    is_public = Column(Boolean, default=False)
    collaborators = Column(JSON, default=list)  # [{user_id, permissions}]
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, onupdate=func.now())

    owner = relationship("User", backref="datasets")


class AnnotationTask(Base):
    __tablename__ = "annotation_tasks"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(256), nullable=False)
    dataset_id = Column(UUID(as_uuid=True), ForeignKey("datasets.id", ondelete="CASCADE"), nullable=False)
    owner_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    annotation_type = Column(String(32), default="rectangle")  # point, line, rectangle, polygon
    status = Column(String(32), default="pending")  # pending, labeling, review, completed
    description = Column(Text, default="")
    total_samples = Column(Integer, default=0)
    labeled_samples = Column(Integer, default=0)
    reviewed_samples = Column(Integer, default=0)
    auto_label_config = Column(JSON, default=dict)  # auto-labeling settings
    guidelines = Column(Text, default="")
    assignees = Column(JSON, default=list)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, onupdate=func.now())

    dataset = relationship("Dataset", backref="annotation_tasks")


class AnnotationResult(Base):
    __tablename__ = "annotation_results"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    task_id = Column(UUID(as_uuid=True), ForeignKey("annotation_tasks.id", ondelete="CASCADE"), nullable=False)
    sample_index = Column(Integer, default=0)
    sample_path = Column(String(512), default="")
    annotations = Column(JSON, default=list)  # [{label, bbox/polygon, confidence}]
    status = Column(String(16), default="unlabeled")  # unlabeled, labeled, reviewed
    labeled_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    reviewed_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    is_auto_labeled = Column(Boolean, default=False)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, onupdate=func.now())

    task = relationship("AnnotationTask", backref="results")


class OrchestrationApp(Base):
    __tablename__ = "orchestration_apps"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(256), nullable=False)
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id"), nullable=True)
    owner_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    workflow_id = Column(UUID(as_uuid=True), ForeignKey("workflows.id", ondelete="SET NULL"), nullable=True)
    description = Column(Text, default="")
    status = Column(String(32), default="draft")  # draft, published, offline
    version = Column(String(32), default="v1")
    config = Column(JSON, default=dict)
    tags = Column(JSON, default=list)
    is_public = Column(Boolean, default=False)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, onupdate=func.now())

    owner = relationship("User", backref="orchestration_apps")


class OrchestrationVersion(Base):
    __tablename__ = "orchestration_versions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    app_id = Column(UUID(as_uuid=True), ForeignKey("orchestration_apps.id", ondelete="CASCADE"), nullable=False)
    version = Column(String(32), default="v1")
    status = Column(String(16), default="published")
    description = Column(Text, default="")
    workflow_snapshot = Column(JSON, default=dict)
    edge_deployed = Column(Boolean, default=False)
    api_published = Column(Boolean, default=False)
    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime, server_default=func.now())

    app = relationship("OrchestrationApp", backref="versions")
    creator = relationship("User")
