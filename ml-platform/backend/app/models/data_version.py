import uuid

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, JSON, String, Text, event, func, Index
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


@event.listens_for(DatasetVersion, "before_update")
def _prevent_dataset_version_update(_mapper, _connection, target):
    raise ValueError("DatasetVersion is immutable")


def _immutable_event(_mapper, _connection, target):
    raise ValueError(f"{target.__class__.__name__} is immutable")

for _model in (DatasetVersion, DatasetSchemaColumn, DatasetSample, DatasetImport):
    event.listen(_model, "before_update", _immutable_event)
    event.listen(_model, "before_delete", _immutable_event)
