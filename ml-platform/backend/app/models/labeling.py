import uuid

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from sqlalchemy import event

from app.database import Base


class LabelSchema(Base):
    __tablename__ = "label_schemas"
    __table_args__ = (UniqueConstraint("project_id", "name", "version", name="uq_label_schema_project_name_version"),)

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    name = Column(String(128), nullable=False)
    version = Column(Integer, nullable=False, default=1)
    status = Column(String(16), nullable=False, default="draft")
    created_at = Column(DateTime, server_default=func.now(), nullable=False)

    columns = relationship("LabelColumn", back_populates="schema", cascade="all, delete-orphan")


class LabelColumn(Base):
    __tablename__ = "label_columns"
    __table_args__ = (UniqueConstraint("schema_id", "machine_key", name="uq_label_column_schema_key"), Index("ix_label_columns_schema_ordinal", "schema_id", "ordinal"))

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    schema_id = Column(UUID(as_uuid=True), ForeignKey("label_schemas.id", ondelete="CASCADE"), nullable=False)
    machine_key = Column(String(128), nullable=False)
    display_name = Column(String(256), nullable=False)
    ordinal = Column(Integer, nullable=False, default=0)
    value_type = Column(String(16), nullable=False)
    required = Column(Boolean, nullable=False, default=False)
    enum_values = Column(JSON, nullable=False, default=list)
    min_value = Column(JSON, nullable=True)
    max_value = Column(JSON, nullable=True)
    max_length = Column(Integer, nullable=True)

    schema = relationship("LabelSchema", back_populates="columns")


class LabelValueConstraint(Base):
    __tablename__ = "label_value_constraints"
    __table_args__ = (UniqueConstraint("column_id", "kind", name="uq_label_constraint_column_kind"),)

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    column_id = Column(UUID(as_uuid=True), ForeignKey("label_columns.id", ondelete="CASCADE"), nullable=False)
    kind = Column(String(32), nullable=False)
    config = Column(JSON, nullable=False, default=dict)


class AnnotationTaskLabel(Base):
    __tablename__ = "annotation_task_labels"
    __table_args__ = (UniqueConstraint("task_id", name="uq_annotation_task_label_task"), Index("ix_annotation_task_labels_schema", "schema_id"))

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    task_id = Column(UUID(as_uuid=True), nullable=False)
    schema_id = Column(UUID(as_uuid=True), ForeignKey("label_schemas.id"), nullable=False)
    schema_snapshot = Column(JSON, nullable=False, default=dict)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)


class AnnotationSampleCurrent(Base):
    __tablename__ = "annotation_sample_current"
    __table_args__ = (UniqueConstraint("task_id", "sample_id", name="uq_annotation_sample_current_task_sample"), Index("ix_annotation_sample_current_task", "task_id"))

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    task_id = Column(UUID(as_uuid=True), nullable=False)
    sample_id = Column(String(256), nullable=False)
    schema_id = Column(UUID(as_uuid=True), ForeignKey("label_schemas.id"), nullable=False)
    revision_no = Column(Integer, nullable=False, default=0)
    values = Column(JSON, nullable=False, default=dict)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)


class AnnotationRevision(Base):
    __tablename__ = "annotation_revisions"
    __table_args__ = (
        UniqueConstraint("task_id", "sample_id", "revision_no", name="uq_annotation_revision_number"),
        Index("ix_annotation_revisions_sample_revision", "task_id", "sample_id", "revision_no"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    task_id = Column(UUID(as_uuid=True), nullable=False)
    sample_id = Column(String(256), nullable=False)
    schema_id = Column(UUID(as_uuid=True), ForeignKey("label_schemas.id"), nullable=False)
    revision_no = Column(Integer, nullable=False)
    base_revision = Column(Integer, nullable=False)
    values = Column(JSON, nullable=False, default=dict)
    author_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    source = Column(String(32), nullable=False, default="manual")
    action = Column(String(32), nullable=False, default="edit")
    provenance_ref = Column(String(256), nullable=True)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)


class AnnotationComment(Base):
    __tablename__ = "annotation_comments"
    __table_args__ = (Index("ix_annotation_comments_task_sample", "task_id", "sample_id"),)

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    task_id = Column(UUID(as_uuid=True), nullable=False)
    sample_id = Column(String(256), nullable=False)
    revision_id = Column(UUID(as_uuid=True), ForeignKey("annotation_revisions.id"), nullable=True)
    author_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    body = Column(Text, nullable=False)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)


class AnnotationConfirmation(Base):
    __tablename__ = "annotation_confirmations"
    __table_args__ = (Index("ix_annotation_confirmations_task_sample", "task_id", "sample_id"),)

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    task_id = Column(UUID(as_uuid=True), nullable=False)
    sample_id = Column(String(256), nullable=False)
    revision_id = Column(UUID(as_uuid=True), ForeignKey("annotation_revisions.id"), nullable=False)
    confirmer_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    action = Column(String(24), nullable=False, default="confirm")
    created_at = Column(DateTime, server_default=func.now(), nullable=False)


def _reject_immutable_change(mapper, connection, target):
    raise ValueError("IMMUTABLE_LABEL_HISTORY")


def _reject_immutable_delete(mapper, connection, target):
    raise ValueError("IMMUTABLE_LABEL_HISTORY")


for _model in (LabelSchema, LabelColumn, LabelValueConstraint, AnnotationTaskLabel, AnnotationRevision, AnnotationComment, AnnotationConfirmation):
    event.listen(_model, "before_update", _reject_immutable_change)
    event.listen(_model, "before_delete", _reject_immutable_delete)
