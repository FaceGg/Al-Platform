"""Acceptance services for immutable annotation return batches."""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.models.annotator import AnnotatorSubjectMapping
from app.models.data_version import DatasetSample, DatasetSchemaColumn, DatasetVersion
from app.models.labeling import (
    AnnotationAssignment,
    AnnotationAssignmentSample,
    AnnotationReturnBatch,
    LabelSchema,
)
from app.models.platform_models import GenericAnnotationTask
from app.models.project import Project
from app.services.annotation_strategies import label_schema_contract_from_snapshot
from app.services.label_schema import LabelValueError, validate_label_values
from app.services.notification_outbox import emit_annotation_return_notification


class AnnotationReturnError(ValueError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def _batch_or_error(db: Session, return_batch_id) -> tuple[AnnotationReturnBatch, AnnotationAssignment, GenericAnnotationTask]:
    query = db.query(AnnotationReturnBatch).filter(AnnotationReturnBatch.id == return_batch_id)
    if db.get_bind().dialect.name == "postgresql":
        query = query.with_for_update()
    batch = query.one_or_none()
    if batch is None:
        raise AnnotationReturnError("RETURN_BATCH_NOT_FOUND")
    assignment = db.get(AnnotationAssignment, batch.assignment_id)
    if assignment is None:
        raise AnnotationReturnError("ASSIGNMENT_NOT_FOUND")
    task = db.get(GenericAnnotationTask, assignment.task_id)
    if task is None:
        raise AnnotationReturnError("ANNOTATION_TASK_NOT_FOUND")
    return batch, assignment, task


def _require_revision(batch: AnnotationReturnBatch, task: GenericAnnotationTask, expected_revision: int) -> None:
    if batch.task_revision != expected_revision or task.task_revision != expected_revision:
        raise AnnotationReturnError("RETURN_BATCH_REVISION_CONFLICT")


def require_return_batch_project_owner(db: Session, return_batch_id, actor_id) -> None:
    _batch, _assignment, task = _batch_or_error(db, return_batch_id)
    project = db.get(Project, task.project_id)
    if project is None or project.owner_id != actor_id:
        raise AnnotationReturnError("PROJECT_NOT_FOUND")


def _project_rows(db: Session, project_id, cursor: str | None, limit: int) -> tuple[list[AnnotationReturnBatch], int, str | None]:
    limit = max(1, min(int(limit), 200))
    query = db.query(AnnotationReturnBatch).join(
        AnnotationAssignment, AnnotationAssignment.id == AnnotationReturnBatch.assignment_id,
    ).join(
        GenericAnnotationTask, GenericAnnotationTask.id == AnnotationAssignment.task_id,
    ).filter(GenericAnnotationTask.project_id == project_id)
    total = query.count()
    if cursor:
        try:
            marker = query.filter(AnnotationReturnBatch.id == uuid.UUID(str(cursor))).one_or_none()
        except (TypeError, ValueError, AttributeError):
            marker = None
        if marker is None:
            raise AnnotationReturnError("INVALID_CURSOR")
        query = query.filter(AnnotationReturnBatch.id < marker.id)
    rows = query.order_by(AnnotationReturnBatch.id.desc()).limit(limit + 1).all()
    has_next = len(rows) > limit
    rows = rows[:limit]
    return rows, total, str(rows[-1].id) if has_next and rows else None


def list_return_batches(db: Session, project_id, cursor: str | None = None, limit: int = 50) -> dict[str, Any]:
    rows, total, next_cursor = _project_rows(db, project_id, cursor, limit)
    return {
        "items": [
            {
                "id": str(row.id),
                "assignment_id": str(row.assignment_id),
                "task_revision": row.task_revision,
                "state": row.state,
                "created_at": row.created_at.isoformat() if row.created_at else None,
                "accepted_dataset_version_id": str(row.accepted_dataset_version_id) if row.accepted_dataset_version_id else None,
            }
            for row in rows
        ],
        "total": total,
        "next_cursor": next_cursor,
    }


def diff_return_batch(db: Session, return_batch_id, cursor: str | None = None, limit: int = 50) -> dict[str, Any]:
    batch, assignment, task = _batch_or_error(db, return_batch_id)
    del batch
    limit = max(1, min(int(limit), 200))
    query = db.query(AnnotationAssignmentSample).filter(
        AnnotationAssignmentSample.assignment_id == assignment.id,
    )
    if cursor:
        marker = query.filter(AnnotationAssignmentSample.sample_id == cursor).one_or_none()
        if marker is None:
            raise AnnotationReturnError("INVALID_CURSOR")
        query = query.filter(AnnotationAssignmentSample.sample_id > marker.sample_id)
    rows = query.order_by(AnnotationAssignmentSample.sample_id.asc()).limit(limit + 1).all()
    has_next = len(rows) > limit
    rows = rows[:limit]
    source_by_sample = {
        row.sample_id: row.values or {}
        for row in db.query(DatasetSample).filter(
            DatasetSample.dataset_version_id == task.dataset_version_id,
            DatasetSample.sample_id.in_([row.sample_id for row in rows]),
        ).all()
    }
    return {
        "items": [
            {"sample_id": row.sample_id, "source_values": source_by_sample.get(row.sample_id, {}), "label_values": row.values or {}}
            for row in rows
        ],
        "total": db.query(AnnotationAssignmentSample).filter_by(assignment_id=assignment.id).count(),
        "next_cursor": rows[-1].sample_id if has_next and rows else None,
    }


def _dataset_hashes(columns: list[DatasetSchemaColumn], rows: list[tuple[str, int, dict[str, object]]]) -> tuple[str, str]:
    schema = [{"name": column.name, "dtype": column.dtype, "nullable": column.nullable} for column in columns]
    content = [{"sample_id": sample_id, "row_index": row_index, "values": values} for sample_id, row_index, values in rows]
    return (
        "sha256:" + hashlib.sha256(json.dumps(content, sort_keys=True, separators=(",", ":")).encode()).hexdigest(),
        "sha256:" + hashlib.sha256(json.dumps(schema, sort_keys=True, separators=(",", ":")).encode()).hexdigest(),
    )


def _recipient_user_id(db: Session, subject_id):
    mapping = db.query(AnnotatorSubjectMapping).filter(
        AnnotatorSubjectMapping.subject_id == subject_id,
    ).one_or_none()
    return mapping.platform_principal_id if mapping is not None else None


def _notify_return_state(db: Session, batch: AnnotationReturnBatch, assignment: AnnotationAssignment, task: GenericAnnotationTask, actor) -> None:
    recipient_user_id = _recipient_user_id(db, assignment.annotator_subject_id)
    if recipient_user_id is None:
        return
    event_type = "annotation_return.accepted" if batch.state == "accepted" else "annotation_return.returned_for_changes"
    emit_annotation_return_notification(
        db,
        project_id=task.project_id,
        actor_id=actor.id,
        recipient_user_id=recipient_user_id,
        return_batch_id=batch.id,
        event_type=event_type,
    )


def accept_return_batch(db: Session, return_batch_id, expected_revision: int, actor) -> DatasetVersion:
    batch, assignment, task = _batch_or_error(db, return_batch_id)
    _require_revision(batch, task, expected_revision)
    if batch.state == "accepted" and batch.accepted_dataset_version_id is not None:
        accepted = db.get(DatasetVersion, batch.accepted_dataset_version_id)
        if accepted is not None:
            return accepted
    if batch.state != "pending":
        raise AnnotationReturnError("RETURN_BATCH_STATE_INVALID")
    source = db.query(DatasetVersion).filter(
        DatasetVersion.id == task.dataset_version_id,
        DatasetVersion.project_id == task.project_id,
    ).one_or_none()
    if source is None:
        raise AnnotationReturnError("DATASET_VERSION_NOT_FOUND")
    schema = db.get(LabelSchema, task.label_schema_id)
    if schema is None:
        raise AnnotationReturnError("LABEL_SCHEMA_NOT_FOUND")
    label_contract = label_schema_contract_from_snapshot({"columns": [
        {
            "machine_key": column.machine_key,
            "value_type": column.value_type,
            "required": column.required,
            "enum_values": column.enum_values or [],
            "min_value": column.min_value,
            "max_value": column.max_value,
            "max_length": column.max_length,
        }
        for column in sorted(schema.columns, key=lambda item: item.ordinal)
    ]})
    labels = {
        row.sample_id: dict(row.values or {})
        for row in db.query(AnnotationAssignmentSample).filter_by(assignment_id=assignment.id).all()
    }
    required_ids = (assignment.sample_scope or {}).get("sample_ids", [])
    if set(labels) != set(required_ids):
        raise AnnotationReturnError("RETURN_BATCH_SCOPE_INVALID")
    for values in labels.values():
        try:
            validate_label_values(label_contract, values, allow_partial=False)
        except LabelValueError as error:
            raise AnnotationReturnError(error.code) from error
    source_columns = db.query(DatasetSchemaColumn).filter_by(dataset_version_id=source.id).order_by(DatasetSchemaColumn.position).all()
    source_rows = db.query(DatasetSample).filter_by(dataset_version_id=source.id).order_by(DatasetSample.row_index).all()
    label_columns = sorted(schema.columns, key=lambda item: item.ordinal)
    source_by_name = {column.name: column for column in source_columns}
    type_aliases = {
        "str": "string", "object": "string", "string": "string",
        "int": "int", "int64": "int",
        "float": "float", "float64": "float",
    }
    for column in label_columns:
        existing = source_by_name.get(column.machine_key)
        if existing is not None and type_aliases.get(existing.dtype.lower()) != column.value_type:
            raise AnnotationReturnError("RETURN_LABEL_COLUMN_TYPE_MISMATCH")
    appended_columns = [column for column in label_columns if column.machine_key not in source_by_name]
    combined_rows = []
    for row in source_rows:
        values = dict(row.values or {})
        if row.sample_id in labels:
            values.update(labels[row.sample_id])
        combined_rows.append((row.sample_id, row.row_index, values))
    columns = [
        DatasetSchemaColumn(name=column.name, position=column.position, dtype=column.dtype, nullable=column.nullable)
        for column in source_columns
    ] + [
        DatasetSchemaColumn(name=column.machine_key, position=len(source_columns) + index, dtype=column.value_type, nullable=not column.required)
        for index, column in enumerate(appended_columns)
    ]
    content_hash, schema_hash = _dataset_hashes(columns, combined_rows)
    latest = db.query(DatasetVersion.version).filter(DatasetVersion.project_id == task.project_id).order_by(DatasetVersion.version.desc()).first()
    accepted = DatasetVersion(
        project_id=task.project_id,
        operator_id=actor.id,
        version=(latest[0] if latest else 0) + 1,
        status="ready",
        row_count=len(combined_rows),
        column_count=len(columns),
        content_hash=content_hash,
        schema_hash=schema_hash,
        parse_contract={"source_format": "annotation_return", "source_dataset_version_id": str(source.id), "return_batch_id": str(batch.id)},
    )
    db.add(accepted)
    db.flush()
    for column in columns:
        db.add(DatasetSchemaColumn(
            dataset_version_id=accepted.id,
            name=column.name,
            position=column.position,
            dtype=column.dtype,
            nullable=column.nullable,
        ))
    for sample_id, row_index, values in combined_rows:
        db.add(DatasetSample(dataset_version_id=accepted.id, sample_id=sample_id, row_index=row_index, values=values))
    batch.state = "accepted"
    batch.accepted_dataset_version_id = accepted.id
    batch.reviewed_by = actor.id
    batch.reviewed_at = datetime.now(timezone.utc).replace(tzinfo=None)
    _notify_return_state(db, batch, assignment, task, actor)
    db.commit()
    db.refresh(accepted)
    return accepted


def reject_return_batch(db: Session, return_batch_id, expected_revision: int, reason: str, actor) -> AnnotationReturnBatch:
    if not isinstance(reason, str) or not reason.strip():
        raise AnnotationReturnError("RETURN_REASON_REQUIRED")
    batch, assignment, task = _batch_or_error(db, return_batch_id)
    _require_revision(batch, task, expected_revision)
    if batch.state != "pending":
        raise AnnotationReturnError("RETURN_BATCH_STATE_INVALID")
    batch.state = "returned_for_changes"
    batch.rejection_reason = reason.strip()
    batch.reviewed_by = actor.id
    batch.reviewed_at = datetime.now(timezone.utc).replace(tzinfo=None)
    assignment.state = "edit_for_return"
    _notify_return_state(db, batch, assignment, task, actor)
    db.commit()
    db.refresh(batch)
    return batch
