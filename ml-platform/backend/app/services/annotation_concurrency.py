import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Mapping

from sqlalchemy.orm import Session

from app.models.annotator import AnnotatorAccount, ProjectAnnotatorGrant
from app.models.labeling import (
    AnnotationAssignment,
    AnnotationAssignmentSample,
    AnnotationReturnBatch,
    AnnotationRevision,
    LabelSchema,
)
from app.models.platform_models import GenericAnnotationTask
from app.models.operation import DurableOperation
from app.services.label_schema import LabelColumnContract, LabelSchemaContract, validate_label_values


class AssignmentError(ValueError):
    def __init__(self, message: str, code: str):
        super().__init__(message)
        self.code = code


class AssignmentLockedError(AssignmentError):
    def __init__(self, message="assignment is locked"):
        super().__init__(message, "ASSIGNMENT_LOCKED")


@dataclass(frozen=True)
class RevisionConflict:
    current_revision: int
    current_values: dict[str, object]
    diff_summary: dict[str, object]


@dataclass(frozen=True)
class LabelWriteResult:
    values: dict[str, object]
    revision_no: int


@dataclass(frozen=True)
class ReturnBatchRef:
    return_batch_id: uuid.UUID
    state: str
    operation_id: uuid.UUID | None = None


@dataclass(frozen=True)
class ConfirmationResult:
    assignment_id: uuid.UUID
    task_revision: int
    scope_hash: str


def _scope_ids(scope: Mapping[str, object]) -> list[str]:
    if scope.get("kind") != "ids":
        raise AssignmentError("sample scope must contain explicit ids", "SAMPLE_SCOPE_INVALID")
    ids = sorted({str(item) for item in scope.get("sample_ids", []) if str(item)})
    if not ids:
        raise AssignmentError("sample scope is empty", "SAMPLE_SCOPE_INVALID")
    return ids


def _scope_hash(ids: list[str]) -> str:
    return "sha256:" + hashlib.sha256(json.dumps(ids, separators=(",", ":")).encode()).hexdigest()


def _task_context(db: Session, task_id):
    return db.get(GenericAnnotationTask, task_id)


def _task_schema_contract(db: Session, task: GenericAnnotationTask) -> LabelSchemaContract | None:
    snapshot = (task.task_snapshot or {}).get("label_schema") or {}
    columns = snapshot.get("columns") or []
    if not columns and task.label_schema_id:
        schema = db.get(LabelSchema, task.label_schema_id)
        columns = [
            {
                "machine_key": column.machine_key,
                "value_type": column.value_type,
                "required": column.required,
                "enum_values": column.enum_values or [],
                "min_value": column.min_value,
                "max_value": column.max_value,
                "max_length": column.max_length,
            }
            for column in sorted((schema.columns if schema else []), key=lambda item: item.ordinal)
        ]
    if not columns:
        return None
    return LabelSchemaContract(
        LabelColumnContract(
            machine_key=str(column["machine_key"]),
            value_type=str(column.get("value_type", "string")),
            required=bool(column.get("required", False)),
            enum_values=tuple(column.get("enum_values") or ()),
            min_value=column.get("min_value"),
            max_value=column.get("max_value"),
            max_length=column.get("max_length"),
        )
        for column in columns
    )


def _ensure_task_access(db: Session, task: GenericAnnotationTask, actor) -> None:
    actor_id = getattr(actor, "id", actor)
    if actor_id is not None and actor_id not in {task.owner_id, getattr(task.project, "owner_id", None)}:
        raise AssignmentError("actor is not authorized for this task", "TASK_FORBIDDEN")


def _ensure_task_writable(task: GenericAnnotationTask) -> None:
    if task.status in {"paused", "cancelled", "archived", "completed"}:
        raise AssignmentLockedError("task does not accept annotation writes")


def create_assignments(
    db: Session,
    *,
    task_id,
    annotator_ids: list,
    sample_scope: Mapping[str, object],
    actor,
    due_at: datetime | None = None,
    initial_values: Mapping[str, Mapping[str, object]] | None = None,
    initial_revision: int = 0,
    idempotency_key: str | None = None,
):
    if not annotator_ids:
        raise AssignmentError("at least one annotator is required", "ANNOTATOR_REQUIRED")
    ids = _scope_ids(sample_scope)
    digest = _scope_hash(ids)
    task = _task_context(db, task_id)
    actor_id = getattr(actor, "id", actor)
    if idempotency_key is not None:
        if not isinstance(idempotency_key, str) or not idempotency_key or len(idempotency_key) > 128:
            raise AssignmentError("idempotency key is invalid", "IDEMPOTENCY_KEY_INVALID")
        existing = db.query(AnnotationAssignment).filter(
            AnnotationAssignment.task_id == task_id,
            AnnotationAssignment.created_by == actor_id,
            AnnotationAssignment.idempotency_key == idempotency_key,
        ).order_by(AnnotationAssignment.id.asc()).all()
        if existing:
            requested_subjects = {str(subject_id) for subject_id in dict.fromkeys(annotator_ids)}
            existing_subjects = {str(item.annotator_subject_id) for item in existing}
            if existing_subjects != requested_subjects or any(item.scope_hash != digest for item in existing):
                raise AssignmentError(
                    "idempotency key was already used for a different assignment request",
                    "IDEMPOTENCY_CONFLICT",
                )
            return existing
    if task is not None:
        _ensure_task_access(db, task, actor)
        _ensure_task_writable(task)
        snapshot_ids = (task.task_snapshot or {}).get("sample_ids")
        if snapshot_ids is None:
            task_scope = task.sample_scope or {}
            snapshot_ids = task_scope.get("sample_ids") if task_scope.get("kind") == "ids" else None
        if snapshot_ids is None:
            raise AssignmentError("task snapshot does not contain explicit sample ids", "SAMPLE_SCOPE_INVALID")
        frozen_ids = {str(item) for item in snapshot_ids if str(item)}
        if not set(ids).issubset(frozen_ids):
            raise AssignmentError("sample scope is outside the frozen task snapshot", "SAMPLE_SCOPE_INVALID")
        active_subjects = {
            row.subject_id
            for row in db.query(ProjectAnnotatorGrant).filter_by(project_id=task.project_id, status="active").all()
        }
        if any(subject_id not in active_subjects for subject_id in annotator_ids):
            raise AssignmentError("annotator is not authorized for this project", "ANNOTATOR_FORBIDDEN")
        active_accounts = {
            row.subject_id
            for row in db.query(AnnotatorAccount).filter(
                AnnotatorAccount.subject_id.in_(annotator_ids),
                AnnotatorAccount.status == "active",
            ).all()
        }
        if any(subject_id not in active_accounts for subject_id in annotator_ids):
            raise AssignmentError("annotator account is not active", "ANNOTATOR_FORBIDDEN")
    result = []
    for subject_id in dict.fromkeys(annotator_ids):
        assignment = AnnotationAssignment(task_id=task_id, annotator_subject_id=subject_id, sample_scope={"kind": "ids", "sample_ids": ids}, scope_hash=digest, due_at=due_at, created_by=actor_id, idempotency_key=idempotency_key, task_revision=initial_revision, last_edit_revision=initial_revision)
        db.add(assignment)
        db.flush()
        for sample_id in ids:
            db.add(AnnotationAssignmentSample(assignment_id=assignment.id, sample_id=sample_id, revision_no=initial_revision, values=dict((initial_values or {}).get(sample_id, {}))))
        result.append(assignment)
    db.commit()
    return result


def _get_sample(db, assignment_id, sample_id):
    row = db.query(AnnotationAssignmentSample).filter_by(assignment_id=assignment_id, sample_id=sample_id).one_or_none()
    if row is None:
        raise AssignmentError("sample is outside assignment scope", "SAMPLE_SCOPE_FORBIDDEN")
    return row


def save_labels(
    db: Session,
    assignment_id,
    sample_id: str,
    values: Mapping[str, object],
    base_revision: int,
    *,
    actor=None,
    commit: bool = True,
):
    assignment = db.get(AnnotationAssignment, assignment_id)
    if assignment is None:
        raise AssignmentError("assignment not found", "ASSIGNMENT_NOT_FOUND")
    if assignment.state in {"returned_pending_acceptance", "revoked"}:
        raise AssignmentLockedError()
    task = _task_context(db, assignment.task_id)
    if task is not None:
        _ensure_task_writable(task)
        if actor is not None:
            _ensure_task_access(db, task, actor)
    row = _get_sample(db, assignment_id, sample_id)
    if row.revision_no != base_revision:
        return RevisionConflict(row.revision_no, dict(row.values or {}), {"sample_id": sample_id})
    merged = dict(row.values or {})
    merged.update(dict(values))
    if task is not None:
        contract = _task_schema_contract(db, task)
        if contract is not None:
            try:
                merged = {**merged, **validate_label_values(contract, dict(values), allow_partial=True)}
            except ValueError as error:
                raise AssignmentError(str(error), getattr(error, "code", "LABEL_VALUE_INVALID")) from error
    next_revision = base_revision + 1
    # Overlapping assignments share one task/sample label state. Mirror the
    # successful write into every assignment's view so a stale editor cannot
    # silently overwrite the latest complete label set.
    siblings = db.query(AnnotationAssignmentSample).join(
        AnnotationAssignment, AnnotationAssignment.id == AnnotationAssignmentSample.assignment_id
    ).filter(
        AnnotationAssignment.task_id == assignment.task_id,
        AnnotationAssignmentSample.sample_id == sample_id,
    ).all()
    for sibling in siblings:
        sibling.values = dict(merged)
        sibling.revision_no = next_revision
        sibling_assignment = db.get(AnnotationAssignment, sibling.assignment_id)
        if sibling_assignment is not None:
            sibling_assignment.task_revision = next_revision
            sibling_assignment.last_edit_revision = next_revision
            if sibling_assignment.state == "edit_for_return":
                sibling_assignment.state = "pending"
    row = next(item for item in siblings if item.assignment_id == assignment.id)
    assignment.last_edit_revision = next_revision
    assignment.task_revision = next_revision
    if task is not None and task.label_schema_id:
        db.add(AnnotationRevision(
            task_id=task.id,
            sample_id=sample_id,
            schema_id=task.label_schema_id,
            revision_no=next_revision,
            base_revision=base_revision,
            values=dict(merged),
            author_id=actor or assignment.created_by,
            source="manual",
            action="edit",
        ))
        if task.status == "awaiting_return":
            task.status = "in_progress"
    if commit:
        db.commit()
    return LabelWriteResult(merged, row.revision_no)


def edit_for_return(db: Session, assignment_id, task_revision: int):
    assignment = db.get(AnnotationAssignment, assignment_id)
    if assignment is None:
        raise AssignmentError("assignment not found", "ASSIGNMENT_NOT_FOUND")
    task = _task_context(db, assignment.task_id)
    if task is not None:
        _ensure_task_writable(task)
    if assignment.state != "returned_pending_acceptance" or task_revision != assignment.task_revision:
        raise AssignmentLockedError()
    task = _task_context(db, assignment.task_id)
    if task is not None:
        _ensure_task_writable(task)
    assignment.state = "edit_for_return"
    db.commit()
    return assignment


def confirm_assignment(db: Session, assignment_id, task_revision: int, scope_hash: str):
    assignment = db.get(AnnotationAssignment, assignment_id)
    if assignment is None:
        raise AssignmentError("assignment not found", "ASSIGNMENT_NOT_FOUND")
    if assignment.task_revision != task_revision or assignment.scope_hash != scope_hash:
        raise AssignmentError("assignment revision or scope is stale", "ASSIGNMENT_REVISION_CONFLICT")
    task = _task_context(db, assignment.task_id)
    if task is not None:
        _ensure_task_writable(task)
        contract = _task_schema_contract(db, task)
    else:
        contract = None
    rows = db.query(AnnotationAssignmentSample).filter_by(assignment_id=assignment.id).all()
    if not rows or any(row.values is None for row in rows):
        raise AssignmentError("assignment has no samples", "ASSIGNMENT_SCOPE_INVALID")
    if contract is not None:
        for row in rows:
            try:
                validate_label_values(contract, row.values or {}, allow_partial=False)
            except ValueError as error:
                raise AssignmentError(str(error), getattr(error, "code", "LABEL_VALUE_INVALID")) from error
    if task is not None:
        _refresh_global_annotation_state(db, task, contract)
        db.commit()
    return ConfirmationResult(assignment.id, task_revision, scope_hash)


def _refresh_global_annotation_state(db: Session, task: GenericAnnotationTask, contract) -> None:
    """Derive the task-level completion state from the frozen sample scope."""
    if task.status in {"paused", "cancelled", "archived", "completed", "accepted"}:
        return
    snapshot_ids = [str(item) for item in ((task.task_snapshot or {}).get("sample_ids") or []) if str(item)]
    if not snapshot_ids:
        task.status = "in_progress"
        return
    rows = db.query(AnnotationAssignmentSample).join(
        AnnotationAssignment,
        AnnotationAssignment.id == AnnotationAssignmentSample.assignment_id,
    ).filter(
        AnnotationAssignment.task_id == task.id,
        AnnotationAssignmentSample.sample_id.in_(snapshot_ids),
    ).all()
    latest: dict[str, AnnotationAssignmentSample] = {}
    for row in rows:
        current = latest.get(row.sample_id)
        if current is None or row.revision_no > current.revision_no:
            latest[row.sample_id] = row
    complete = len(latest) == len(set(snapshot_ids))
    if complete and contract is not None:
        for sample_id in set(snapshot_ids):
            try:
                validate_label_values(contract, latest[sample_id].values or {}, allow_partial=False)
            except ValueError:
                complete = False
                break
    task.status = "awaiting_return" if complete else "in_progress"


def return_assignment(db: Session, assignment_id, task_revision: int, scope_hash: str, idempotency_key: str):
    assignment = db.get(AnnotationAssignment, assignment_id)
    if assignment is None:
        raise AssignmentError("assignment not found", "ASSIGNMENT_NOT_FOUND")
    existing = db.query(AnnotationReturnBatch).filter_by(assignment_id=assignment.id, idempotency_key=idempotency_key).one_or_none()
    if existing is not None:
        return ReturnBatchRef(existing.id, existing.state, existing.operation_id)
    task = _task_context(db, assignment.task_id)
    if task is not None:
        _ensure_task_writable(task)
    if assignment.scope_hash != scope_hash or assignment.task_revision != task_revision:
        raise AssignmentError("assignment revision or scope is stale", "ASSIGNMENT_REVISION_CONFLICT")
    if assignment.state in {"returned_pending_acceptance", "edit_for_return"}:
        raise AssignmentLockedError()
    db.query(AnnotationReturnBatch).filter(
        AnnotationReturnBatch.assignment_id == assignment.id,
        AnnotationReturnBatch.scope_hash == scope_hash,
        AnnotationReturnBatch.state == "pending",
    ).update(
        {AnnotationReturnBatch.state: "superseded"},
        synchronize_session=False,
    )
    batch = AnnotationReturnBatch(assignment_id=assignment.id, task_revision=task_revision, scope_hash=scope_hash, idempotency_key=idempotency_key, state="pending")
    db.add(batch)
    db.flush()
    operation = DurableOperation(
        resource_key=f"annotation-return:{batch.id}",
        idempotency_key=idempotency_key,
        state="queued",
        stage="queued",
    )
    db.add(operation)
    db.flush()
    batch.operation_id = operation.id
    assignment.state = "returned_pending_acceptance"
    db.commit()
    from app.tasks.annotation_return_tasks import enqueue_annotation_return

    enqueue_annotation_return(batch.id, operation.id)
    return ReturnBatchRef(batch.id, batch.state, operation.id)


def write_with_revision_guard(db: Session, task_id, sample_id: str, values, author_id, base_revision: int):
    return save_labels(db, task_id, sample_id, values, base_revision)
