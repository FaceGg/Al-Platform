"""Acceptance services for immutable annotation return batches."""

from __future__ import annotations

import hashlib
import json
import re
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from sqlalchemy import and_, or_
from sqlalchemy.orm import Session

from app.models.access import AuditEvent
from app.models.annotator import AnnotatorAccount, AnnotatorSubjectMapping
from app.models.artifact import Artifact
from app.models.data_version import DatasetSample, DatasetSchemaColumn, DatasetVersion
from app.models.labeling import (
    AnnotationAssignment,
    AnnotationReturnBatch,
    AnnotationReturnBatchSample,
)
from app.models.operation import DurableOperation
from app.models.platform_models import GenericAnnotationTask
from app.models.project import Project
from app.services.annotation_return_snapshots import (
    AnnotationReturnSnapshotError,
    iter_return_batch_sample_batches,
    label_contract_for_return_snapshot,
    refresh_task_return_state,
    return_batch_checksum,
    return_batch_sample_count,
    scope_row_indexes,
    task_snapshot_for_revision,
)
from app.services.artifact_service import build_artifact_service
from app.services.label_schema import LabelValueError, validate_label_values
from app.services.notification_outbox import emit_annotation_return_notification


_BATCH_SIZE = 500


class AnnotationReturnError(ValueError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def _lock_query(db: Session, query):
    if db.get_bind().dialect.name == "postgresql":
        return query.with_for_update()
    return query


def _batch_or_error(db: Session, return_batch_id) -> tuple[AnnotationReturnBatch, AnnotationAssignment, GenericAnnotationTask]:
    batch = _lock_query(
        db,
        db.query(AnnotationReturnBatch).filter(AnnotationReturnBatch.id == return_batch_id),
    ).one_or_none()
    if batch is None:
        raise AnnotationReturnError("RETURN_BATCH_NOT_FOUND")
    assignment = _lock_query(
        db,
        db.query(AnnotationAssignment).filter(AnnotationAssignment.id == batch.assignment_id),
    ).one_or_none()
    if assignment is None:
        raise AnnotationReturnError("ASSIGNMENT_NOT_FOUND")
    task = _lock_query(
        db,
        db.query(GenericAnnotationTask).filter(GenericAnnotationTask.id == assignment.task_id),
    ).one_or_none()
    if task is None or task.archived_at is not None:
        # Deleted/archived tasks must behave as missing for every portal and
        # acceptance flow, including batches that were returned before deletion.
        raise AnnotationReturnError("ANNOTATION_TASK_NOT_FOUND")
    return batch, assignment, task


def _require_revision(batch: AnnotationReturnBatch, task: GenericAnnotationTask, expected_revision: int) -> None:
    if batch.task_revision != expected_revision or task.task_revision != expected_revision:
        raise AnnotationReturnError("RETURN_BATCH_REVISION_CONFLICT")


def _snapshot_and_contract(db: Session, batch: AnnotationReturnBatch, task: GenericAnnotationTask):
    try:
        snapshot = task_snapshot_for_revision(db, task, batch.task_revision)
        return snapshot, label_contract_for_return_snapshot(snapshot)
    except AnnotationReturnSnapshotError as error:
        raise AnnotationReturnError(error.code) from error


def _require_completed_frozen_batch(
    db: Session,
    batch: AnnotationReturnBatch,
    task: GenericAnnotationTask,
) -> tuple[DurableOperation, int]:
    if batch.operation_id is None:
        raise AnnotationReturnError("RETURN_BATCH_NOT_READY")
    operation = db.get(DurableOperation, batch.operation_id)
    if (
        operation is None
        or operation.resource_type != "annotation_return"
        or operation.resource_key != f"annotation-return:{batch.id}"
        or operation.task_id not in {None, task.id}
        or operation.project_id not in {None, task.project_id}
        or operation.state != "completed"
        or str(operation.result_artifact_id) != str(batch.id)
    ):
        raise AnnotationReturnError("RETURN_BATCH_NOT_READY")
    count = return_batch_sample_count(db, batch.id)
    summary = dict(operation.result_summary or {})
    try:
        validated_count = int(summary.get("validated_row_count"))
    except (TypeError, ValueError):
        raise AnnotationReturnError("RETURN_BATCH_NOT_READY") from None
    if count <= 0 or validated_count != count:
        raise AnnotationReturnError("RETURN_BATCH_NOT_READY")
    try:
        snapshot = task_snapshot_for_revision(db, task, batch.task_revision)
    except AnnotationReturnSnapshotError as error:
        raise AnnotationReturnError(error.code) from error
    if operation.checksum != return_batch_checksum(db, batch, snapshot):
        raise AnnotationReturnError("RETURN_BATCH_CHECKSUM_INVALID")
    return operation, count


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
    ).filter(
        GenericAnnotationTask.project_id == project_id,
        # Batches belonging to deleted/archived tasks must not surface in the
        # acceptance panel; their tasks are gone from every other view too.
        GenericAnnotationTask.archived_at.is_(None),
    )
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
    operations = {
        row.id: db.get(DurableOperation, row.operation_id) if row.operation_id else None
        for row in rows
    }
    # Correlate each batch with its task and annotator so acceptance reviewers
    # can tell which task and which annotator a batch belongs to.
    assignments = {
        assignment.id: assignment
        for assignment in db.query(AnnotationAssignment).filter(
            AnnotationAssignment.id.in_([row.assignment_id for row in rows])
        ).all()
    } if rows else {}
    tasks = {
        task.id: task
        for task in db.query(GenericAnnotationTask).filter(
            GenericAnnotationTask.id.in_([assignment.task_id for assignment in assignments.values()])
        ).all()
    } if assignments else {}
    annotators = {
        account.subject_id: account.username
        for account in db.query(AnnotatorAccount).filter(
            AnnotatorAccount.subject_id.in_([assignment.annotator_subject_id for assignment in assignments.values()])
        ).all()
    } if assignments else {}
    # Correlate tasks and accepted batches with their dataset artifacts so
    # reviewers can see the original file and the saved data product.
    dataset_version_ids: set = set()
    for task in tasks.values():
        if task is not None and task.dataset_version_id is not None:
            dataset_version_ids.add(task.dataset_version_id)
    # Exports create their own dataset versions (with the artifact); find the
    # latest export per batch through the frozen parse_contract reference.
    exported_by_batch: dict[str, DatasetVersion] = {}
    if rows:
        exported_versions = db.query(DatasetVersion).filter(
            DatasetVersion.parse_contract["return_batch_id"].as_string().in_(
                [str(row.id) for row in rows]
            )
        ).order_by(DatasetVersion.version.desc()).all()
        for version in exported_versions:
            key = str((version.parse_contract or {}).get("return_batch_id"))
            if key and key not in exported_by_batch:
                exported_by_batch[key] = version
                dataset_version_ids.add(version.id)
    versions = {
        version.id: version
        for version in db.query(DatasetVersion).filter(
            DatasetVersion.id.in_(dataset_version_ids)
        ).all()
    } if dataset_version_ids else {}
    artifact_ids = {
        version.original_artifact_id
        for version in versions.values()
        if version.original_artifact_id is not None
    }
    artifacts = {
        artifact.id: artifact
        for artifact in db.query(Artifact).filter(Artifact.id.in_(artifact_ids)).all()
    } if artifact_ids else {}

    def _artifact_name(version_id) -> str | None:
        version = versions.get(version_id) if version_id is not None else None
        if version is None or version.original_artifact_id is None:
            return None
        artifact = artifacts.get(version.original_artifact_id)
        return artifact.name if artifact is not None else None

    def _batch_context(row: AnnotationReturnBatch) -> dict[str, Any]:
        assignment = assignments.get(row.assignment_id)
        if assignment is None:
            return {}
        task = tasks.get(assignment.task_id)
        return {
            "task_id": str(assignment.task_id),
            "task_name": task.name if task is not None else None,
            "annotator_subject_id": str(assignment.annotator_subject_id),
            "annotator_name": annotators.get(assignment.annotator_subject_id),
            "source_dataset_name": _artifact_name(task.dataset_version_id) if task is not None else None,
        }

    return {
        "items": [
            {
                "id": str(row.id),
                "assignment_id": str(row.assignment_id),
                "task_revision": row.task_revision,
                "state": row.state,
                "operation_state": operations[row.id].state if operations[row.id] is not None else None,
                "validated_row_count": (
                    (operations[row.id].result_summary or {}).get("validated_row_count")
                    if operations[row.id] is not None else None
                ),
                "created_at": row.created_at.isoformat() if row.created_at else None,
                "accepted_dataset_version_id": str(row.accepted_dataset_version_id) if row.accepted_dataset_version_id else None,
                "saved_dataset_name": (
                    _artifact_name(exported_by_batch[str(row.id)].id)
                    if str(row.id) in exported_by_batch else None
                ),
                **_batch_context(row),
            }
            for row in rows
        ],
        "total": total,
        "next_cursor": next_cursor,
    }


def diff_return_batch(db: Session, return_batch_id, cursor: str | None = None, limit: int = 50) -> dict[str, Any]:
    batch, _assignment, task = _batch_or_error(db, return_batch_id)
    _require_completed_frozen_batch(db, batch, task)
    limit = max(1, min(int(limit), 200))
    query = db.query(AnnotationReturnBatchSample).filter(
        AnnotationReturnBatchSample.return_batch_id == batch.id,
    )
    if cursor:
        marker = query.filter(AnnotationReturnBatchSample.sample_id == cursor).one_or_none()
        if marker is None:
            raise AnnotationReturnError("INVALID_CURSOR")
        query = query.filter(AnnotationReturnBatchSample.sample_id > marker.sample_id)
    rows = query.order_by(
        AnnotationReturnBatchSample.sample_id.asc(),
        AnnotationReturnBatchSample.id.asc(),
    ).limit(limit + 1).all()
    has_next = len(rows) > limit
    rows = rows[:limit]
    source_by_sample = {
        str(row.sample_id): dict(row.values or {})
        for row in db.query(DatasetSample).filter(
            DatasetSample.dataset_version_id == task.dataset_version_id,
            DatasetSample.sample_id.in_([row.sample_id for row in rows]),
        ).all()
    }
    return {
        "items": [
            {
                "sample_id": row.sample_id,
                "row_index": row.row_index,
                "source_values": source_by_sample.get(str(row.sample_id), {}),
                "label_values": dict(row.values or {}),
            }
            for row in rows
        ],
        "total": return_batch_sample_count(db, batch.id),
        "next_cursor": rows[-1].sample_id if has_next and rows else None,
    }


def _validate_frozen_batch(db: Session, batch: AnnotationReturnBatch, task: GenericAnnotationTask) -> tuple[dict, Any, int]:
    snapshot, label_contract = _snapshot_and_contract(db, batch, task)
    count = 0
    for rows in iter_return_batch_sample_batches(db, batch.id):
        row_indexes = scope_row_indexes(
            db,
            task,
            task_revision=batch.task_revision,
            snapshot=snapshot,
            sample_ids=[str(row.sample_id) for row in rows],
        )
        for row in rows:
            sample_id = str(row.sample_id)
            if row_indexes.get(sample_id) != int(row.row_index):
                raise AnnotationReturnError("RETURN_BATCH_SCOPE_INVALID")
            values = dict(row.values or {})
            try:
                normalized = validate_label_values(label_contract, values, allow_partial=False)
            except LabelValueError as error:
                raise AnnotationReturnError(getattr(error, "code", "RETURN_LABEL_VALUE_INVALID")) from error
            if normalized != values:
                raise AnnotationReturnError("RETURN_LABEL_VALUE_INVALID")
            count += 1
    if count <= 0:
        raise AnnotationReturnError("RETURN_BATCH_NOT_READY")
    return snapshot, label_contract, count


def _ensure_no_accepted_overlap(db: Session, batch: AnnotationReturnBatch, task: GenericAnnotationTask) -> None:
    for rows in iter_return_batch_sample_batches(db, batch.id):
        sample_ids = [str(row.sample_id) for row in rows]
        query = db.query(AnnotationReturnBatchSample.sample_id).join(
            AnnotationReturnBatch,
            AnnotationReturnBatch.id == AnnotationReturnBatchSample.return_batch_id,
        ).join(
            AnnotationAssignment,
            AnnotationAssignment.id == AnnotationReturnBatch.assignment_id,
        ).filter(
            AnnotationAssignment.task_id == task.id,
            AnnotationReturnBatch.task_revision == batch.task_revision,
            AnnotationReturnBatch.state == "accepted",
            AnnotationReturnBatch.id != batch.id,
            AnnotationReturnBatchSample.sample_id.in_(sample_ids),
        )
        if _lock_query(db, query).first() is not None:
            raise AnnotationReturnError("RETURN_BATCH_SAMPLE_ALREADY_ACCEPTED")


def _source_sample_batches(db: Session, dataset_version_id, batch_size: int = _BATCH_SIZE) -> Iterator[list[DatasetSample]]:
    marker = None
    while True:
        query = db.query(DatasetSample).filter(
            DatasetSample.dataset_version_id == dataset_version_id,
        )
        if marker is not None:
            query = query.filter(or_(
                DatasetSample.row_index > marker.row_index,
                and_(DatasetSample.row_index == marker.row_index, DatasetSample.id > marker.id),
            ))
        rows = query.order_by(DatasetSample.row_index.asc(), DatasetSample.id.asc()).limit(batch_size).all()
        if not rows:
            return
        yield rows
        marker = rows[-1]


def _accepted_values_for_source_page(
    db: Session,
    *,
    task: GenericAnnotationTask,
    task_revision: int,
    accepting_batch_id,
    sample_ids: list[str],
) -> dict[str, dict[str, object]]:
    rows = db.query(AnnotationReturnBatchSample).join(
        AnnotationReturnBatch,
        AnnotationReturnBatch.id == AnnotationReturnBatchSample.return_batch_id,
    ).join(
        AnnotationAssignment,
        AnnotationAssignment.id == AnnotationReturnBatch.assignment_id,
    ).filter(
        AnnotationAssignment.task_id == task.id,
        AnnotationReturnBatch.task_revision == task_revision,
        AnnotationReturnBatchSample.sample_id.in_(sample_ids),
        or_(
            AnnotationReturnBatch.state == "accepted",
            AnnotationReturnBatch.id == accepting_batch_id,
        ),
    ).all()
    values: dict[str, dict[str, object]] = {}
    for row in rows:
        sample_id = str(row.sample_id)
        if sample_id in values:
            raise AnnotationReturnError("RETURN_BATCH_SAMPLE_ALREADY_ACCEPTED")
        values[sample_id] = dict(row.values or {})
    return values


def _schema_hash(columns: list[DatasetSchemaColumn]) -> str:
    payload = [
        {"name": column.name, "dtype": column.dtype, "nullable": column.nullable}
        for column in columns
    ]
    return "sha256:" + hashlib.sha256(json.dumps(
        payload,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")).hexdigest()


def _content_hash_and_count(
    db: Session,
    *,
    source: DatasetVersion,
    task: GenericAnnotationTask,
    accepting_batch_id,
) -> tuple[str, int]:
    digest = hashlib.sha256(b"annotation-return-dataset-v1\x00")
    count = 0
    for source_rows in _source_sample_batches(db, source.id):
        labels = _accepted_values_for_source_page(
            db,
            task=task,
            task_revision=task.task_revision,
            accepting_batch_id=accepting_batch_id,
            sample_ids=[str(row.sample_id) for row in source_rows],
        )
        for row in source_rows:
            values = dict(row.values or {})
            values.update(labels.get(str(row.sample_id), {}))
            digest.update(json.dumps(
                {"sample_id": str(row.sample_id), "row_index": int(row.row_index), "values": values},
                ensure_ascii=True,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8"))
            digest.update(b"\n")
            count += 1
    return "sha256:" + digest.hexdigest(), count


def _insert_dataset_samples(
    db: Session,
    *,
    dataset_version_id,
    source: DatasetVersion,
    task: GenericAnnotationTask,
    accepting_batch_id,
) -> int:
    count = 0
    for source_rows in _source_sample_batches(db, source.id):
        labels = _accepted_values_for_source_page(
            db,
            task=task,
            task_revision=task.task_revision,
            accepting_batch_id=accepting_batch_id,
            sample_ids=[str(row.sample_id) for row in source_rows],
        )
        db.bulk_insert_mappings(DatasetSample, [
            {
                "id": uuid.uuid4(),
                "dataset_version_id": dataset_version_id,
                "sample_id": str(row.sample_id),
                "row_index": int(row.row_index),
                "values": {**dict(row.values or {}), **labels.get(str(row.sample_id), {})},
            }
            for row in source_rows
        ])
        count += len(source_rows)
    return count


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
    try:
        batch, assignment, task = _batch_or_error(db, return_batch_id)
        _require_revision(batch, task, expected_revision)
        if batch.state == "accepted" and batch.accepted_dataset_version_id is not None:
            accepted = db.get(DatasetVersion, batch.accepted_dataset_version_id)
            if accepted is not None:
                return accepted
        if batch.state != "pending":
            raise AnnotationReturnError("RETURN_BATCH_STATE_INVALID")
        if task.status not in {"awaiting_return", "returned_pending_acceptance"}:
            raise AnnotationReturnError("TASK_STATE_INVALID")
        _require_completed_frozen_batch(db, batch, task)
        snapshot, _label_contract, frozen_count = _validate_frozen_batch(db, batch, task)
        _ensure_no_accepted_overlap(db, batch, task)
        source = db.query(DatasetVersion).filter(
            DatasetVersion.id == task.dataset_version_id,
            DatasetVersion.project_id == task.project_id,
        ).one_or_none()
        if source is None:
            raise AnnotationReturnError("DATASET_VERSION_NOT_FOUND")
        project = _lock_query(
            db,
            db.query(Project).filter(Project.id == task.project_id),
        ).one_or_none()
        if project is None:
            raise AnnotationReturnError("PROJECT_NOT_FOUND")
        source_columns = db.query(DatasetSchemaColumn).filter_by(
            dataset_version_id=source.id,
        ).order_by(DatasetSchemaColumn.position).all()
        label_columns = list((snapshot.get("label_schema") or {}).get("columns") or [])
        source_by_name = {column.name: column for column in source_columns}
        type_aliases = {
            "str": "string", "object": "string", "string": "string",
            "int": "int", "int64": "int",
            "float": "float", "float64": "float",
        }
        for column in label_columns:
            machine_key = str(column.get("machine_key") or "")
            value_type = str(column.get("value_type") or "")
            if not machine_key or value_type not in {"int", "float", "string"}:
                raise AnnotationReturnError("RETURN_LABEL_SCHEMA_INVALID")
            existing = source_by_name.get(machine_key)
            if existing is not None and type_aliases.get(existing.dtype.lower()) != value_type:
                raise AnnotationReturnError("RETURN_LABEL_COLUMN_TYPE_MISMATCH")
        appended_columns = [
            column for column in label_columns
            if str(column["machine_key"]) not in source_by_name
        ]
        final_columns = [
            DatasetSchemaColumn(
                name=column.name,
                position=column.position,
                dtype=column.dtype,
                nullable=column.nullable,
            )
            for column in source_columns
        ] + [
            DatasetSchemaColumn(
                name=str(column["machine_key"]),
                position=len(source_columns) + index,
                dtype=str(column["value_type"]),
                nullable=not bool(column.get("required", False)),
            )
            for index, column in enumerate(appended_columns)
        ]

        # Marking the batch accepted is still transactional. It lets both
        # passes include this batch together with previously accepted ranges.
        batch.state = "accepted"
        coverage = refresh_task_return_state(
            db,
            task,
            task_revision=batch.task_revision,
            snapshot=snapshot,
        )
        content_hash, source_row_count = _content_hash_and_count(
            db,
            source=source,
            task=task,
            accepting_batch_id=batch.id,
        )
        if source_row_count != int(source.row_count):
            raise AnnotationReturnError("RETURN_SOURCE_ROW_COUNT_MISMATCH")
        latest = db.query(DatasetVersion.version).filter(
            DatasetVersion.project_id == task.project_id,
        ).order_by(DatasetVersion.version.desc()).first()
        accepted = DatasetVersion(
            project_id=task.project_id,
            operator_id=actor.id,
            version=(int(latest[0]) if latest else 0) + 1,
            status="pending",
            row_count=source_row_count,
            column_count=len(final_columns),
            content_hash=content_hash,
            schema_hash=_schema_hash(final_columns),
            parse_contract={
                "source_format": "annotation_return",
                "source_dataset_version_id": str(source.id),
                "return_batch_id": str(batch.id),
                "task_id": str(task.id),
                "task_revision": int(batch.task_revision),
                "validated_row_count": frozen_count,
                "task_scope_fully_accepted": coverage.all_accepted,
            },
        )
        db.add(accepted)
        db.flush()
        db.bulk_insert_mappings(DatasetSchemaColumn, [
            {
                "id": uuid.uuid4(),
                "dataset_version_id": accepted.id,
                "name": column.name,
                "position": column.position,
                "dtype": column.dtype,
                "nullable": column.nullable,
            }
            for column in final_columns
        ])
        inserted_count = _insert_dataset_samples(
            db,
            dataset_version_id=accepted.id,
            source=source,
            task=task,
            accepting_batch_id=batch.id,
        )
        if inserted_count != source_row_count:
            raise AnnotationReturnError("RETURN_SOURCE_ROW_COUNT_MISMATCH")
        accepted.status = "ready"
        batch.accepted_dataset_version_id = accepted.id
        batch.reviewed_by = actor.id
        batch.reviewed_at = datetime.now(timezone.utc).replace(tzinfo=None)
        if coverage.all_accepted:
            task.status = "completed"
        else:
            refresh_task_return_state(
                db,
                task,
                task_revision=batch.task_revision,
                snapshot=snapshot,
            )
        db.add(AuditEvent(
            project_id=task.project_id,
            actor_id=actor.id,
            actor_username=getattr(actor, "username", str(actor.id)),
            action="annotation_return.accepted",
            resource_type="annotation_return_batch",
            resource_id=str(batch.id),
            result="success",
            request_id=uuid.uuid4(),
            changes={
                "task_revision": batch.task_revision,
                "dataset_version_id": str(accepted.id),
                "validated_row_count": frozen_count,
                "task_scope_fully_accepted": coverage.all_accepted,
            },
        ))
        _notify_return_state(db, batch, assignment, task, actor)
        db.commit()
        db.refresh(accepted)
        return accepted
    except AnnotationReturnError:
        db.rollback()
        raise
    except Exception:
        db.rollback()
        raise


def reject_return_batch(db: Session, return_batch_id, expected_revision: int, reason: str, actor) -> AnnotationReturnBatch:
    if not isinstance(reason, str) or not reason.strip():
        raise AnnotationReturnError("RETURN_REASON_REQUIRED")
    try:
        batch, assignment, task = _batch_or_error(db, return_batch_id)
        _require_revision(batch, task, expected_revision)
        if batch.state != "pending":
            raise AnnotationReturnError("RETURN_BATCH_STATE_INVALID")
        _require_completed_frozen_batch(db, batch, task)
        batch.state = "returned_for_changes"
        batch.rejection_reason = reason.strip()
        batch.reviewed_by = actor.id
        batch.reviewed_at = datetime.now(timezone.utc).replace(tzinfo=None)
        assignment.state = "edit_for_return"
        if task.status not in {"completed", "archived", "cancelled"}:
            task.status = "in_progress"
        db.add(AuditEvent(
            project_id=task.project_id,
            actor_id=actor.id,
            actor_username=getattr(actor, "username", str(actor.id)),
            action="annotation_return.returned_for_changes",
            resource_type="annotation_return_batch",
            resource_id=str(batch.id),
            result="success",
            request_id=uuid.uuid4(),
            changes={"task_revision": batch.task_revision, "reason": batch.rejection_reason},
        ))
        _notify_return_state(db, batch, assignment, task, actor)
        db.commit()
        db.refresh(batch)
        return batch
    except AnnotationReturnError:
        db.rollback()
        raise


def _accepted_version_or_error(db: Session, return_batch_id) -> tuple[AnnotationReturnBatch, GenericAnnotationTask, DatasetVersion]:
    batch, _assignment, task = _batch_or_error(db, return_batch_id)
    if batch.state != "accepted" or batch.accepted_dataset_version_id is None:
        raise AnnotationReturnError("EXPORT_BATCH_NOT_ACCEPTED")
    accepted = db.get(DatasetVersion, batch.accepted_dataset_version_id)
    if accepted is None or str(accepted.project_id) != str(task.project_id):
        raise AnnotationReturnError("ACCEPTED_DATASET_VERSION_NOT_FOUND")
    return batch, task, accepted


def _export_label_columns_or_error(db: Session, batch: AnnotationReturnBatch, task: GenericAnnotationTask) -> list[dict]:
    try:
        snapshot = task_snapshot_for_revision(db, task, batch.task_revision)
    except AnnotationReturnSnapshotError as error:
        raise AnnotationReturnError(error.code) from error
    columns = list(((snapshot or {}).get("label_schema") or {}).get("columns") or [])
    for column in columns:
        machine_key = str(column.get("machine_key") or "")
        value_type = str(column.get("value_type") or "")
        if not machine_key or value_type not in {"int", "float", "string"}:
            raise AnnotationReturnError("RETURN_LABEL_SCHEMA_INVALID")
    return columns


def _string_label_mapping(db: Session, *, column: dict, accepted_version_id) -> dict[str, int]:
    """value→int mapping for one string label column. Values keep the schema's
    enum order first, then any remaining values by first appearance in the
    accepted samples (0, 1, 2, ...)."""
    key = str(column["machine_key"])
    appeared: list[str] = []
    for rows in _source_sample_batches(db, accepted_version_id):
        for row in rows:
            value = (row.values or {}).get(key)
            if value is None:
                continue
            text = str(value)
            if text not in appeared:
                appeared.append(text)
    enum_values = [
        str(value) for value in (column.get("enum_values") or [])
        if value is not None and str(value) != ""
    ]
    ordered = [value for value in enum_values if value in appeared]
    ordered += [value for value in appeared if value not in ordered]
    return {value: index for index, value in enumerate(ordered)}


def _export_label_plan(db: Session, *, batch: AnnotationReturnBatch, task: GenericAnnotationTask, accepted: DatasetVersion) -> list[dict]:
    """Per label column: int/float columns pass through unchanged, string
    columns get a value→int mapping built from the accepted samples."""
    plan: list[dict] = []
    for column in _export_label_columns_or_error(db, batch, task):
        value_type = str(column["value_type"])
        entry: dict = {
            "machine_key": str(column["machine_key"]),
            "display_name": str(column.get("display_name") or column.get("machine_key")),
            "value_type": value_type,
        }
        if value_type == "string":
            entry["mapping"] = _string_label_mapping(db, column=column, accepted_version_id=accepted.id)
        plan.append(entry)
    return plan


def export_return_batch_preview(db: Session, return_batch_id) -> dict:
    """Preview for the save-to-data-management dialog: label column types and,
    for string columns, the proposed value→int mapping."""
    batch, task, accepted = _accepted_version_or_error(db, return_batch_id)
    return {
        "return_batch_id": str(batch.id),
        "task_id": str(task.id),
        "task_name": task.name,
        "row_count": int(accepted.row_count),
        "columns": _export_label_plan(db, batch=batch, task=task, accepted=accepted),
    }


def _unique_export_dataset_name(db: Session, project_id, name: str) -> str:
    existing = {
        row[0] for row in db.query(Artifact.name).filter(
            Artifact.project_id == project_id,
            Artifact.type == "dataset",
            Artifact.archived_at.is_(None),
        ).all()
    }
    if name not in existing:
        return name
    # Insert the counter before the file extension (name-2.csv, not name.csv-2).
    stem, dot, suffix = name.rpartition(".")
    if not dot or not stem or len(suffix) > 8 or "/" in suffix or "\\" in suffix:
        stem, suffix = name, ""
    extension = f".{suffix}" if suffix else ""
    counter = 2
    while f"{stem}-{counter}{extension}" in existing:
        counter += 1
    return f"{stem}-{counter}{extension}"


def _export_file_format(db: Session, accepted: DatasetVersion) -> str:
    """The exported file keeps the source dataset's file type (csv/xlsx/parquet,
    never user-choosable). Falls back to csv when no source artifact exists."""
    source_version_id = (accepted.parse_contract or {}).get("source_dataset_version_id")
    if source_version_id:
        try:
            source_version = db.get(DatasetVersion, uuid.UUID(str(source_version_id)))
        except (ValueError, TypeError, AttributeError):
            source_version = None
        if source_version is not None and source_version.original_artifact_id:
            source_artifact = db.get(Artifact, source_version.original_artifact_id)
            if source_artifact is not None and source_artifact.format:
                file_format = str(source_artifact.format).lower()
                if file_format in {"csv", "xlsx", "xls", "parquet"}:
                    return file_format
                raise AnnotationReturnError("EXPORT_FILE_TYPE_UNSUPPORTED")
    return "csv"


def _write_export_table_file(path: Path, file_format: str, columns: list[DatasetSchemaColumn], sample_rows: list[dict]) -> None:
    names = [column.name for column in columns]
    if file_format == "csv":
        import csv as csv_module
        with path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv_module.writer(handle)
            writer.writerow(names)
            for row in sample_rows:
                writer.writerow([row["values"].get(name) for name in names])
        return
    import pandas as pd
    frame = pd.DataFrame([row["values"] for row in sample_rows], columns=names)
    if file_format in {"xls", "xlsx"}:
        frame.to_excel(path, index=False)
    elif file_format == "parquet":
        frame.to_parquet(path, index=False)
    else:
        raise AnnotationReturnError("EXPORT_FILE_TYPE_UNSUPPORTED")


_EXPORT_LABEL_NAME_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _validate_export_renames(renames: dict | None, label_keys: set[str], source_columns) -> dict[str, str]:
    """Label column names must be English identifiers in the exported dataset;
    Chinese names have to be renamed (e.g. 结果 → outcome) before saving."""
    if not renames:
        return {}
    other_names = {column.name for column in source_columns if column.name not in label_keys}
    seen_targets: set[str] = set()
    for key, target in renames.items():
        if key not in label_keys:
            raise AnnotationReturnError("EXPORT_LABEL_NAME_INVALID")
        if not isinstance(target, str) or not _EXPORT_LABEL_NAME_PATTERN.match(target.strip()) or target.strip() != target:
            raise AnnotationReturnError("EXPORT_LABEL_NAME_INVALID")
        if target in other_names or target in seen_targets or target in label_keys - {key}:
            raise AnnotationReturnError("EXPORT_LABEL_NAME_INVALID")
        seen_targets.add(target)
    return dict(renames)


def export_return_batch_dataset(db: Session, return_batch_id, name: str, actor, renames: dict | None = None) -> tuple[Artifact, DatasetVersion, dict]:
    """Save an accepted batch into data management as a named dataset: numeric
    label columns are copied as-is, string label columns are mapped to ints.
    Chinese label column names must be renamed (renames) to English first."""
    name = (name or "").strip()
    if not name or len(name) > 256:
        raise AnnotationReturnError("EXPORT_NAME_REQUIRED")
    try:
        batch, task, accepted = _accepted_version_or_error(db, return_batch_id)
        plan = _export_label_plan(db, batch=batch, task=task, accepted=accepted)
        label_keys = {entry["machine_key"] for entry in plan}
        mapping_by_key = {
            entry["machine_key"]: entry["mapping"]
            for entry in plan if entry["value_type"] == "string"
        }
        source_columns = db.query(DatasetSchemaColumn).filter_by(
            dataset_version_id=accepted.id,
        ).order_by(DatasetSchemaColumn.position).all()
        renames = _validate_export_renames(renames, label_keys, source_columns)
        final_columns = [
            DatasetSchemaColumn(
                name=renames.get(column.name, column.name),
                position=column.position,
                # String label columns are stored as their mapped ints.
                dtype="int" if column.name in mapping_by_key else column.dtype,
                nullable=column.nullable,
            )
            for column in source_columns
        ]
        file_format = _export_file_format(db, accepted)
        # The saved dataset name keeps the source file suffix (e.g. ".csv") so
        # it looks and behaves like an uploaded dataset in data management.
        suffix = f".{file_format}"
        base_name = name if name.lower().endswith(suffix) else f"{name}{suffix}"
        artifact_name = _unique_export_dataset_name(db, task.project_id, base_name)
        digest = hashlib.sha256(b"annotation-return-export-v1\x00")
        count = 0
        sample_rows: list[dict] = []
        for rows in _source_sample_batches(db, accepted.id):
            for row in rows:
                values = dict(row.values or {})
                for key in label_keys:
                    value = values.pop(key, None)
                    if value is None:
                        continue
                    mapped_key = renames.get(key, key)
                    mapping = mapping_by_key.get(key)
                    if mapping is not None:
                        mapped = mapping.get(str(value))
                        if mapped is None:
                            raise AnnotationReturnError("EXPORT_LABEL_VALUE_UNMAPPED")
                        values[mapped_key] = mapped
                    else:
                        values[mapped_key] = value
                digest.update(json.dumps(
                    {"sample_id": str(row.sample_id), "row_index": int(row.row_index), "values": values},
                    ensure_ascii=True,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8"))
                digest.update(b"\n")
                sample_rows.append({
                    "sample_id": str(row.sample_id),
                    "row_index": int(row.row_index),
                    "values": values,
                })
                count += 1
        if count != int(accepted.row_count):
            raise AnnotationReturnError("RETURN_SOURCE_ROW_COUNT_MISMATCH")
        with tempfile.TemporaryDirectory() as directory:
            temporary = Path(directory) / f"annotation-return-export-{uuid.uuid4().hex}.{file_format}"
            _write_export_table_file(temporary, file_format, final_columns, sample_rows)
            # The exported dataset keeps the source dataset's file type and is
            # stored as a real file (storage_uri) so data management preview,
            # download and materialize all work exactly like uploaded datasets.
            artifact = build_artifact_service(db).create_from_file(
                task.project_id,
                temporary,
                artifact_name,
                "dataset",
                {
                    "source": "annotation_return_export",
                    "schema": [
                        {"name": column.name, "dtype": column.dtype, "null_count": 0}
                        for column in final_columns
                    ],
                    "row_count": count,
                    "column_count": len(final_columns),
                    "task_id": str(task.id),
                    "return_batch_id": str(batch.id),
                },
                commit=False,
            )
        latest = db.query(DatasetVersion.version).filter(
            DatasetVersion.project_id == task.project_id,
        ).order_by(DatasetVersion.version.desc()).first()
        exported = DatasetVersion(
            project_id=task.project_id,
            operator_id=actor.id,
            original_artifact_id=artifact.id,
            version=(int(latest[0]) if latest else 0) + 1,
            status="ready",
            row_count=count,
            column_count=len(final_columns),
            content_hash="sha256:" + digest.hexdigest(),
            schema_hash=_schema_hash(final_columns),
            parse_contract={
                "source_format": "annotation_return_export",
                "source_dataset_version_id": str(accepted.id),
                "source_file_format": file_format,
                "return_batch_id": str(batch.id),
                "task_id": str(task.id),
                "task_revision": int(batch.task_revision),
                "label_mappings": mapping_by_key,
                "label_renames": dict(renames),
            },
        )
        db.add(exported)
        db.flush()
        db.bulk_insert_mappings(DatasetSchemaColumn, [
            {
                "id": uuid.uuid4(),
                "dataset_version_id": exported.id,
                "name": column.name,
                "position": column.position,
                "dtype": column.dtype,
                "nullable": column.nullable,
            }
            for column in final_columns
        ])
        db.bulk_insert_mappings(DatasetSample, [
            {
                "id": uuid.uuid4(),
                "dataset_version_id": exported.id,
                "sample_id": row["sample_id"],
                "row_index": row["row_index"],
                "values": row["values"],
            }
            for row in sample_rows
        ])
        db.add(AuditEvent(
            project_id=task.project_id,
            actor_id=actor.id,
            actor_username=getattr(actor, "username", str(actor.id)),
            action="annotation_return.exported_dataset",
            resource_type="annotation_return_batch",
            resource_id=str(batch.id),
            result="success",
            request_id=uuid.uuid4(),
            changes={
                "task_revision": batch.task_revision,
                "artifact_id": str(artifact.id),
                "dataset_version_id": str(exported.id),
                "row_count": count,
                "label_mappings": mapping_by_key,
            },
        ))
        db.commit()
        db.refresh(exported)
        return artifact, exported, mapping_by_key
    except AnnotationReturnError:
        db.rollback()
        raise
    except Exception:
        db.rollback()
        raise
