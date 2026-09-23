"""Durable validation and snapshot worker for annotation return batches."""

from __future__ import annotations

import threading
from types import SimpleNamespace
import uuid

from sqlalchemy import and_, or_

from app.config import settings
from app.database import SessionLocal
from app.models.labeling import (
    AnnotationAssignment,
    AnnotationAssignmentSample,
    AnnotationConfirmation,
    AnnotationReturnBatch,
    AnnotationReturnBatchSample,
    AnnotationRevision,
    AnnotationSampleCurrent,
)
from app.models.operation import DurableOperation
from app.models.platform_models import GenericAnnotationTask
from app.services.annotation_return_snapshots import (
    label_contract_for_return_snapshot,
    refresh_task_return_state,
    return_batch_checksum,
    return_batch_sample_count,
    scope_row_indexes,
    task_snapshot_for_revision,
)
from app.services.label_schema import LabelValueError, validate_label_values
from app.services.operation_lifecycle import (
    claim_operation,
    complete_operation,
    fail_operation,
    heartbeat_operation,
)
from app.tasks.celery_app import celery_app


_BATCH_SIZE = 500


class ReturnBatchValidationError(ValueError):
    def __init__(self, code: str, message: str | None = None):
        self.code = code
        super().__init__(message or code)


def enqueue_annotation_return(batch_id, operation_id):
    args = (str(batch_id), str(operation_id))
    if settings.task_backend == "celery":
        return execute_annotation_return.delay(*args)
    threading.Thread(target=execute_annotation_return.run, args=args, daemon=True).start()
    return SimpleNamespace(id=str(operation_id))


@celery_app.task(bind=True, name="ml_platform.execute_annotation_return")
def execute_annotation_return(self, batch_id: str, operation_id: str):
    del self
    worker_id = f"annotation-return:{operation_id}"
    try:
        with SessionLocal() as db:
            return _execute_with_session(db, batch_id, operation_id, worker_id)
    except Exception:
        # The durable operation remains recoverable when a process races a
        # schema deployment before it can open the batch transaction.
        return {"status": "deferred", "operation_id": operation_id}


def _assignment_sample_batches(db, assignment_id, batch_size: int = _BATCH_SIZE):
    marker = None
    while True:
        query = db.query(AnnotationAssignmentSample).filter(
            AnnotationAssignmentSample.assignment_id == assignment_id,
        )
        if marker is not None:
            query = query.filter(or_(
                AnnotationAssignmentSample.sample_id > marker.sample_id,
                and_(
                    AnnotationAssignmentSample.sample_id == marker.sample_id,
                    AnnotationAssignmentSample.id > marker.id,
                ),
            ))
        rows = query.order_by(
            AnnotationAssignmentSample.sample_id.asc(),
            AnnotationAssignmentSample.id.asc(),
        ).limit(batch_size).all()
        if not rows:
            return
        yield rows
        marker = rows[-1]


def _provenance(revision: AnnotationRevision) -> dict[str, object]:
    payload: dict[str, object] = {
        "revision_id": str(revision.id),
        "revision_no": int(revision.revision_no),
        "source": str(revision.source),
        "action": str(revision.action),
        "author_id": str(revision.author_id),
    }
    if revision.provenance_ref:
        payload["provenance_ref"] = str(revision.provenance_ref)
    return payload


def _validate_and_freeze_page(
    db,
    *,
    batch: AnnotationReturnBatch,
    task: GenericAnnotationTask,
    task_snapshot: dict,
    label_contract,
    rows: list[AnnotationAssignmentSample],
) -> None:
    sample_ids = [str(row.sample_id) for row in rows]
    existing = {
        str(row.sample_id): row
        for row in db.query(AnnotationReturnBatchSample).filter(
            AnnotationReturnBatchSample.return_batch_id == batch.id,
            AnnotationReturnBatchSample.sample_id.in_(sample_ids),
        ).all()
    }
    row_indexes = scope_row_indexes(
        db,
        task,
        task_revision=batch.task_revision,
        snapshot=task_snapshot,
        sample_ids=sample_ids,
    )
    current_rows = {
        str(row.sample_id): row
        for row in db.query(AnnotationSampleCurrent).filter(
            AnnotationSampleCurrent.task_id == task.id,
            AnnotationSampleCurrent.sample_id.in_(sample_ids),
        ).all()
    }
    revisions = {
        (str(row.sample_id), int(row.revision_no)): row
        for row in db.query(AnnotationRevision).filter(
            AnnotationRevision.task_id == task.id,
            AnnotationRevision.sample_id.in_(sample_ids),
        ).all()
    }
    confirmations = {
        row.revision_id
        for row in db.query(AnnotationConfirmation).filter(
            AnnotationConfirmation.task_id == task.id,
            AnnotationConfirmation.sample_id.in_(sample_ids),
            AnnotationConfirmation.action == "confirm",
        ).all()
    }

    for row in rows:
        sample_id = str(row.sample_id)
        values = dict(row.values or {})
        frozen = existing.get(sample_id)
        if frozen is not None:
            if int(frozen.revision_no) != int(row.revision_no) or dict(frozen.values or {}) != values:
                raise ReturnBatchValidationError("RETURN_BATCH_FROZEN_REVISION_CONFLICT")
            continue
        if sample_id not in row_indexes:
            raise ReturnBatchValidationError("RETURN_BATCH_SCOPE_INVALID")
        try:
            normalized = validate_label_values(label_contract, values, allow_partial=False)
        except LabelValueError as error:
            raise ReturnBatchValidationError(
                getattr(error, "code", "RETURN_LABEL_VALUE_INVALID"),
                str(error),
            ) from error
        if normalized != values:
            raise ReturnBatchValidationError("RETURN_LABEL_VALUE_INVALID")
        current = current_rows.get(sample_id)
        if current is None or int(current.revision_no) != int(row.revision_no):
            raise ReturnBatchValidationError("ASSIGNMENT_REVISION_CONFLICT")
        if dict(current.values or {}) != values:
            raise ReturnBatchValidationError("ASSIGNMENT_REVISION_CONFLICT")
        revision = revisions.get((sample_id, int(row.revision_no)))
        if revision is None or dict(revision.values or {}) != values:
            raise ReturnBatchValidationError("LABEL_REVISION_NOT_FOUND")
        if revision.id not in confirmations:
            raise ReturnBatchValidationError("ANNOTATION_NOT_READY")
        db.add(AnnotationReturnBatchSample(
            return_batch_id=batch.id,
            sample_id=sample_id,
            row_index=row_indexes[sample_id],
            revision_no=int(row.revision_no),
            values=values,
            provenance=_provenance(revision),
        ))


def _freeze_return_batch(
    db,
    *,
    batch: AnnotationReturnBatch,
    assignment: AnnotationAssignment,
    task: GenericAnnotationTask,
    worker_id: str,
    operation_id,
) -> tuple[dict[str, object], str]:
    if assignment.task_id != task.id or assignment.task_revision != batch.task_revision:
        raise ReturnBatchValidationError("RETURN_BATCH_REVISION_CONFLICT")
    task_snapshot = task_snapshot_for_revision(db, task, batch.task_revision)
    label_contract = label_contract_for_return_snapshot(task_snapshot)
    expected_count = int(db.query(AnnotationAssignmentSample).filter_by(
        assignment_id=assignment.id,
    ).count())
    if expected_count <= 0:
        raise ReturnBatchValidationError("ASSIGNMENT_SCOPE_INVALID")

    for rows in _assignment_sample_batches(db, assignment.id):
        _validate_and_freeze_page(
            db,
            batch=batch,
            task=task,
            task_snapshot=task_snapshot,
            label_contract=label_contract,
            rows=rows,
        )
        db.flush()
        # Persist completed pages before extending the lease. A retry can
        # safely verify and reuse immutable rows instead of recomputing them.
        heartbeat_operation(db, operation_id, worker_id, 300)

    frozen_count = return_batch_sample_count(db, batch.id)
    if frozen_count != expected_count:
        raise ReturnBatchValidationError("RETURN_BATCH_FREEZE_INCOMPLETE")
    checksum = return_batch_checksum(db, batch, task_snapshot)
    summary = {
        "validated_row_count": frozen_count,
        "label_columns": [column.machine_key for column in label_contract.columns],
        "task_revision": int(batch.task_revision),
        "scope_hash": str(batch.scope_hash),
        "source_dataset_version_id": str(task.dataset_version_id),
    }
    return summary, checksum


def _execute_with_session(db, batch_id: str, operation_id: str, worker_id: str):
    batch_uuid = uuid.UUID(batch_id)
    operation_uuid = uuid.UUID(operation_id)
    batch = db.get(AnnotationReturnBatch, batch_uuid)
    operation = db.get(DurableOperation, operation_uuid)
    if (
        batch is None
        or operation is None
        or batch.operation_id != operation.id
        or operation.resource_type != "annotation_return"
        or operation.resource_key != f"annotation-return:{batch.id}"
    ):
        if operation is not None and operation.state not in {"completed", "failed", "cancelled"}:
            fail_operation(db, operation.id, "ANNOTATION_RETURN_INVALID", {"message": "return binding not found"})
        return {"status": "invalid_request", "operation_id": operation_id}
    if operation.state in {"completed", "failed", "cancelled"}:
        return {"status": "not_claimed", "operation_id": operation_id}
    try:
        if not claim_operation(db, operation.id, worker_id, 300):
            return {"status": "not_claimed", "operation_id": operation_id}
        batch = db.get(AnnotationReturnBatch, batch_uuid)
        assignment = db.get(AnnotationAssignment, batch.assignment_id) if batch is not None else None
        task = db.get(GenericAnnotationTask, assignment.task_id) if assignment is not None else None
        if batch is None or assignment is None or task is None:
            raise ReturnBatchValidationError("ANNOTATION_RETURN_INVALID")
        if operation.task_id not in {None, task.id} or operation.project_id not in {None, task.project_id}:
            raise ReturnBatchValidationError("ANNOTATION_RETURN_INVALID")
        if batch.state != "pending":
            snapshot = task_snapshot_for_revision(db, task, batch.task_revision)
            complete_operation(
                db,
                operation.id,
                worker_id,
                batch.id,
                return_batch_checksum(db, batch, snapshot),
                result_summary={"state": batch.state, "validated_row_count": return_batch_sample_count(db, batch.id)},
            )
            return {"status": batch.state, "operation_id": operation_id, "return_batch_id": batch_id}
        summary, checksum = _freeze_return_batch(
            db,
            batch=batch,
            assignment=assignment,
            task=task,
            worker_id=worker_id,
            operation_id=operation.id,
        )
        batch = db.get(AnnotationReturnBatch, batch_uuid)
        if batch is None or batch.state != "pending":
            raise ReturnBatchValidationError("RETURN_BATCH_STATE_INVALID")
        snapshot = task_snapshot_for_revision(db, task, batch.task_revision)
        refresh_task_return_state(
            db,
            task,
            task_revision=batch.task_revision,
            snapshot=snapshot,
            include_pending_batch_id=batch.id,
        )
        complete_operation(
            db,
            operation.id,
            worker_id,
            batch.id,
            checksum,
            result_summary=summary,
        )
        return {"status": "completed", "operation_id": operation_id, "return_batch_id": batch_id}
    except Exception as error:
        db.rollback()
        try:
            fail_operation(
                db,
                operation_uuid,
                getattr(error, "code", "ANNOTATION_RETURN_FAILED"),
                {"message": str(error)[:300]},
                worker_id=worker_id,
            )
        except ValueError:
            pass
        return {"status": "failed", "operation_id": operation_id}
