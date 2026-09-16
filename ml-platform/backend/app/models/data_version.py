import uuid

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, JSON, String, Text, event, func, Index, inspect
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.database import Base


class DatasetVersion(Base):
    __tablename__ = "dataset_versions"
    __table_args__ = (Index("uq_dataset_versions_project_version", "project_id", "version", unique=True),)

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    operator_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    version = Column(Integer, nullable=False, default=1)
    status = Column(String(24), nullable=False, default="ready")
    row_count = Column(Integer, nullable=False, default=0)
    column_count = Column(Integer, nullable=False, default=0)
    content_hash = Column(String(128), nullable=False)
    schema_hash = Column(String(128), nullable=False)
    parse_contract = Column(JSON, nullable=False, default=dict)
    original_artifact_id = Column(UUID(as_uuid=True), ForeignKey("artifacts.id"), nullable=True)
    normalized_artifact_id = Column(UUID(as_uuid=True), ForeignKey("artifacts.id"), nullable=True)
    archived_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)

    schema_columns = relationship("DatasetSchemaColumn", back_populates="dataset_version", cascade="all, delete-orphan")
    samples = relationship("DatasetSample", back_populates="dataset_version", cascade="all, delete-orphan")


class DatasetSchemaColumn(Base):
    __tablename__ = "dataset_schema_columns"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    dataset_version_id = Column(UUID(as_uuid=True), ForeignKey("dataset_versions.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(256), nullable=False)
    position = Column(Integer, nullable=False)
    dtype = Column(String(64), nullable=False)
    nullable = Column(Boolean, nullable=False, default=True)

    dataset_version = relationship("DatasetVersion", back_populates="schema_columns")


class DatasetSample(Base):
    __tablename__ = "dataset_samples"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    dataset_version_id = Column(UUID(as_uuid=True), ForeignKey("dataset_versions.id", ondelete="CASCADE"), nullable=False, index=True)
    sample_id = Column(String(256), nullable=False)
    row_index = Column(Integer, nullable=False)
    values = Column(JSON, nullable=False)

    dataset_version = relationship("DatasetVersion", back_populates="samples")


class DatasetImport(Base):
    __tablename__ = "dataset_imports"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    dataset_version_id = Column(UUID(as_uuid=True), ForeignKey("dataset_versions.id", ondelete="CASCADE"), nullable=False, index=True)
    source_format = Column(String(32), nullable=False)
    parse_contract = Column(JSON, nullable=False, default=dict)
    content_hash = Column(String(128), nullable=False)
    schema_hash = Column(String(128), nullable=False)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)


class DatasetImportProcess(Base):
    """Mutable import workflow state; immutable data versions are created only on confirmation."""

    __tablename__ = "dataset_import_processes"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    operator_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    operation_id = Column(UUID(as_uuid=True), ForeignKey("durable_operations.id"), nullable=False, unique=True)
    confirmation_operation_id = Column(UUID(as_uuid=True), ForeignKey("durable_operations.id"), nullable=True, unique=True)
    dataset_version_id = Column(UUID(as_uuid=True), ForeignKey("dataset_versions.id"), nullable=True, unique=True)
    status = Column(String(24), nullable=False, default="queued", index=True)
    source_name = Column(String(512), nullable=False)
    source_format = Column(String(32), nullable=False)
    parse_options = Column(JSON, nullable=False, default=dict)
    parse_contract = Column(JSON, nullable=True)
    inferred_schema = Column(JSON, nullable=True)
    content_hash = Column(String(128), nullable=True)
    schema_hash = Column(String(128), nullable=True)
    original_artifact_id = Column(UUID(as_uuid=True), ForeignKey("artifacts.id"), nullable=False)
    normalized_artifact_id = Column(UUID(as_uuid=True), ForeignKey("artifacts.id"), nullable=True)
    error = Column(JSON, nullable=True)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)


@event.listens_for(DatasetVersion, "before_update")
def _prevent_dataset_version_update(_mapper, _connection, target):
    history = inspect(target).attrs.status.history
    if history.has_changes() and history.deleted == ["pending"] and history.added == ["ready"]:
        return
    raise ValueError("DatasetVersion is immutable")


def _immutable_event(_mapper, _connection, target):
    if isinstance(target, DatasetVersion):
        history = inspect(target).attrs.status.history
        if history.has_changes() and history.deleted == ["pending"] and history.added == ["ready"]:
            return
    raise ValueError(f"{target.__class__.__name__} is immutable")

for _model in (DatasetVersion, DatasetSchemaColumn, DatasetSample, DatasetImport):
    event.listen(_model, "before_update", _immutable_event)
    event.listen(_model, "before_delete", _immutable_event)
