import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Callable, Iterable, Mapping

from sqlalchemy import and_, or_
from sqlalchemy.orm import Session

from app.models.annotator import AnnotatorAccount, ProjectAnnotatorGrant
from app.models.data_version import DatasetSample, DatasetSchemaColumn
from app.models.labeling import (
    AnnotationAssignment,
    AnnotationAssignmentSample,
    AnnotationConfirmation,
    AnnotationReturnBatch,
    AnnotationRevision,
    AnnotationSampleCurrent,
    LabelSchema,
)
from app.models.platform_models import GenericAnnotationTask
from app.models.operation import DurableOperation
from app.models.access import AuditEvent
from app.services.label_schema import (
    LabelColumnContract,
    LabelSchemaContract,
    source_column_label_type,
    validate_label_values,
)
from app.services.annotation_scope import iter_scope_batches, missing_scope_sample_ids, scope_digest
from app.services.annotation_task_state import current_annotation_task_snapshot


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


@dataclass(frozen=True)
class _ResolvedAssignmentScope:
    payload: dict[str, object]
    scope_hash: str
    sample_count: int
    batches: Callable[[], Iterable[list[str]]]


def _scope_ids(scope: Mapping[str, object]) -> list[str]:
    if scope.get("kind") != "ids":
        raise AssignmentError("sample scope must contain explicit ids", "SAMPLE_SCOPE_INVALID")
    ids = sorted({str(item) for item in scope.get("sample_ids", []) if str(item)})
    if not ids:
        raise AssignmentError("sample scope is empty", "SAMPLE_SCOPE_INVALID")
    return ids


def _scope_hash(ids: list[str]) -> str:
    return "sha256:" + hashlib.sha256(json.dumps(ids, separators=(",", ":")).encode()).hexdigest()


def _resolve_assignment_scope(db: Session, task: GenericAnnotationTask | None, scope: Mapping[str, object]) -> _ResolvedAssignmentScope:
    kind = scope.get("kind")
    if kind == "ids":
        ids = _scope_ids(scope)

        def batches():
            for start in range(0, len(ids), 500):
                yield ids[start:start + 500]

        return _ResolvedAssignmentScope(
            payload={"kind": "ids", "sample_ids": ids, "sample_count": len(ids)},
            scope_hash=_scope_hash(ids),
            sample_count=len(ids),
            batches=batches,
        )
    if kind not in {"task_scope", "frozen_task_scope", "all"} or task is None:
        raise AssignmentError("sample scope must contain explicit ids or the frozen task scope", "SAMPLE_SCOPE_INVALID")
    snapshot = current_annotation_task_snapshot(db, task)

    def scope_batches():
        for batch in iter_scope_batches(
            db,
            task,
            task_revision=task.task_revision,
            snapshot=snapshot,
        ):
            yield [sample_id for sample_id, _ in batch]

    scope_metadata = snapshot.get("scope") if isinstance(snapshot, Mapping) else None
    if isinstance(scope_metadata, Mapping) and scope_metadata.get("scope_hash"):
        sample_count = int(scope_metadata.get("sample_count", 0))
        digest = str(scope_metadata["scope_hash"])
    else:
        sample_count, digest = scope_digest(
            (sample_id, row_index)
            for batch in iter_scope_batches(
                db,
                task,
                task_revision=task.task_revision,
                snapshot=snapshot,
            )
            for sample_id, row_index in batch
        )
    if sample_count <= 0:
        raise AssignmentError("task scope is empty", "SAMPLE_SCOPE_INVALID")
    return _ResolvedAssignmentScope(
        payload={
            "kind": "frozen_task_scope",
            "sample_count": sample_count,
            "scope_hash": digest,
            "task_revision": task.task_revision,
        },
        scope_hash=digest,
        sample_count=sample_count,
        batches=scope_batches,
    )


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


def _manual_source_label_keys(
    db: Session,
    task: GenericAnnotationTask,
    contract: LabelSchemaContract | None,
) -> tuple[str, ...]:
    """Identify frozen source columns that initialize same-named manual labels."""
    if task.mode != "manual" or contract is None:
        return ()
    source_by_name = {
        str(column.name): column
        for column in db.query(DatasetSchemaColumn).filter(
            DatasetSchemaColumn.dataset_version_id == task.dataset_version_id,
        ).all()
    }
    source_label_keys = []
    for label_column in contract.columns:
        source_column = source_by_name.get(label_column.machine_key)
        if source_column is None:
            continue
        source_type = source_column_label_type(source_column.dtype)
        if source_type is None:
            raise AssignmentError(
                "source-backed label column has an unsupported source type",
                "LABEL_SOURCE_COLUMN_TYPE_UNSUPPORTED",
            )
        if source_type != label_column.value_type.lower():
            raise AssignmentError(
                "source-backed label column does not match its source type",
                "LABEL_SOURCE_COLUMN_TYPE_MISMATCH",
            )
        source_label_keys.append(label_column.machine_key)
    return tuple(source_label_keys)


def _source_label_values_for_batch(
    db: Session,
    task: GenericAnnotationTask,
    sample_ids: list[str],
    source_label_keys: tuple[str, ...],
) -> dict[str, dict[str, object]]:
    if not source_label_keys:
        return {}
    source_rows = db.query(DatasetSample).filter(
        DatasetSample.dataset_version_id == task.dataset_version_id,
        DatasetSample.sample_id.in_(sample_ids),
    ).all()
    rows_by_sample_id = {str(row.sample_id): row for row in source_rows}
    missing = sorted(set(sample_ids) - set(rows_by_sample_id))
    if missing:
        raise AssignmentError(
            "frozen task scope contains samples missing from its source dataset version",
            "SOURCE_SAMPLE_NOT_FOUND",
        )
    return {
        sample_id: {
            key: dict(rows_by_sample_id[sample_id].values or {}).get(key)
            for key in source_label_keys
        }
        for sample_id in sample_ids
    }


def _ensure_task_access(db: Session, task: GenericAnnotationTask, actor) -> None:
    actor_id = getattr(actor, "id", actor)
    if actor_id is not None and actor_id not in {task.owner_id, getattr(task.project, "owner_id", None)}:
        raise AssignmentError("actor is not authorized for this task", "TASK_FORBIDDEN")


def _ensure_task_writable(task: GenericAnnotationTask) -> None:
    if task.status in {"paused", "cancelled", "archived", "completed"}:
        raise AssignmentLockedError("task does not accept annotation writes")


def _task_state_invalid(task: GenericAnnotationTask, operation: str) -> None:
    _ensure_task_writable(task)
    raise AssignmentError(
        f"task does not allow {operation} in its current state",
        "TASK_STATE_INVALID",
    )


def _ensure_task_allows_assignment(task: GenericAnnotationTask) -> None:
    if task.status not in {"preview_ready", "awaiting_annotation", "in_progress"}:
        _task_state_invalid(task, "assignment changes")


def _ensure_task_allows_label_write(
    task: GenericAnnotationTask,
    assignment: AnnotationAssignment,
) -> None:
    if task.status in {"awaiting_annotation", "in_progress", "awaiting_return"}:
        return
    if task.status == "returned_pending_acceptance" and assignment.state == "edit_for_return":
        return
    _task_state_invalid(task, "label writes")


def _ensure_task_allows_confirmation(task: GenericAnnotationTask) -> None:
    if task.status not in {"awaiting_annotation", "in_progress"}:
        _task_state_invalid(task, "completion confirmation")


def _ensure_task_allows_return_edit(task: GenericAnnotationTask) -> None:
    if task.status != "returned_pending_acceptance":
        _task_state_invalid(task, "return editing")


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
    task = _task_context(db, task_id)
    resolved_scope = _resolve_assignment_scope(db, task, sample_scope)
    digest = resolved_scope.scope_hash
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
        _ensure_task_allows_assignment(task)
        if sample_scope.get("kind") == "ids":
            snapshot = current_annotation_task_snapshot(db, task)
            missing_scope_ids = missing_scope_sample_ids(
                db,
                task,
                task_revision=task.task_revision,
                snapshot=snapshot,
                sample_ids=[sample_id for batch in resolved_scope.batches() for sample_id in batch],
            )
            if missing_scope_ids:
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
    task_contract = _task_schema_contract(db, task) if task is not None else None
    source_label_keys = _manual_source_label_keys(db, task, task_contract) if task is not None else ()
    configuration_revision = task.task_revision if task is not None else initial_revision
    assignments = [
        AnnotationAssignment(
            task_id=task_id,
            annotator_subject_id=subject_id,
            sample_scope=resolved_scope.payload,
            scope_hash=digest,
            due_at=due_at,
            created_by=actor_id,
            idempotency_key=idempotency_key,
            task_revision=configuration_revision,
            last_edit_revision=initial_revision,
        )
        for subject_id in dict.fromkeys(annotator_ids)
    ]
    for assignment in assignments:
        db.add(assignment)
    db.flush()

    for sample_batch in resolved_scope.batches():
        current_values = {}
        if task is not None:
            current_values = {
                row.sample_id: row
                for row in db.query(AnnotationSampleCurrent).filter(
                    AnnotationSampleCurrent.task_id == task.id,
                    AnnotationSampleCurrent.sample_id.in_(sample_batch),
                ).limit(len(sample_batch)).all()
            }
            if task.mode == "automatic":
                missing = sorted(set(sample_batch) - set(current_values))
                if missing:
                    raise AssignmentError(
                        "automatic labels have not been published for the assignment scope",
                        "AUTOMATIC_LABELS_NOT_PUBLISHED",
                    )
        source_values = _source_label_values_for_batch(
            db,
            task,
            [sample_id for sample_id in sample_batch if sample_id not in current_values],
            source_label_keys,
        ) if task is not None and source_label_keys else {}
        for sample_id in sample_batch:
            current = current_values.get(sample_id)
            values = dict(current.values or {}) if current is not None else dict((initial_values or {}).get(sample_id, {}))
            revision_no = current.revision_no if current is not None else initial_revision
            if task is not None and current is None:
                if task_contract is not None and values:
                    try:
                        values = validate_label_values(task_contract, values, allow_partial=True)
                    except ValueError as error:
                        raise AssignmentError(
                            str(error),
                            getattr(error, "code", "LABEL_VALUE_INVALID"),
                        ) from error
                values.update(source_values.get(sample_id, {}))
            if task is not None and current is None and values and task.label_schema_id:
                current = AnnotationSampleCurrent(
                    task_id=task.id,
                    sample_id=sample_id,
                    schema_id=task.label_schema_id,
                    revision_no=revision_no,
                    values=dict(values),
                )
                db.add(current)
                db.add(AnnotationRevision(
                    task_id=task.id,
                    sample_id=sample_id,
                    schema_id=task.label_schema_id,
                    revision_no=revision_no,
                    base_revision=max(0, revision_no - 1),
                    values=dict(values),
                    author_id=actor_id,
                    source="automatic" if task.mode == "automatic" else "manual",
                    action="initialize",
                ))
            for assignment in assignments:
                db.add(AnnotationAssignmentSample(
                    assignment_id=assignment.id,
                    sample_id=sample_id,
                    revision_no=revision_no,
                    values=values,
                ))
    db.commit()
    return assignments


def transition_assignment(
    db: Session,
    assignment_id,
    *,
    action: str,
    task_revision: int,
    actor,
    idempotency_key: str | None = None,
    request_id=None,
):
    return _transition_assignment(
        db,
        assignment_id,
        action=action,
        task_revision=task_revision,
        actor=actor,
        idempotency_key=idempotency_key,
        request_id=request_id,
    )


def _assignment_command_fingerprint(action: str, task_revision: int) -> str:
    payload = json.dumps(
        {"action": action, "task_revision": int(task_revision)},
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _transition_assignment(
    db: Session,
    assignment_id,
    *,
    action: str,
    task_revision: int,
    actor,
    idempotency_key: str | None = None,
    request_id=None,
):
    assignment = db.get(AnnotationAssignment, assignment_id)
    if assignment is None:
        raise AssignmentError("assignment not found", "ASSIGNMENT_NOT_FOUND")
    task = _task_context(db, assignment.task_id)
    if task is not None:
        _ensure_task_access(db, task, actor)
    command_operation = None
    command_fingerprint = None
    actor_id = getattr(actor, "id", actor)
    if idempotency_key:
        if len(idempotency_key) > 128:
            raise AssignmentError("idempotency key is invalid", "IDEMPOTENCY_KEY_INVALID")
        command_fingerprint = _assignment_command_fingerprint(action, task_revision)
        command_operation = db.query(DurableOperation).filter(
            DurableOperation.resource_key == f"annotation-assignment-command:{assignment.id}:{actor_id}:{action}",
            DurableOperation.idempotency_key == idempotency_key,
        ).one_or_none()
        if command_operation is not None:
            if command_operation.request_fingerprint != command_fingerprint:
                raise AssignmentError("idempotency key was already used for a different request", "IDEMPOTENCY_CONFLICT")
            stored = dict(command_operation.result_summary or {}).get("response")
            assignment._command_operation_id = command_operation.id
            assignment._command_response_payload = stored if isinstance(stored, dict) else None
            return assignment
    if task is not None and task.status in {"paused", "cancelled", "archived", "completed"}:
        raise AssignmentLockedError("task does not accept assignment changes")
    if task is not None:
        if task.task_revision != task_revision:
            raise AssignmentError("assignment revision is stale", "ASSIGNMENT_REVISION_CONFLICT")
        # Older rows may have carried a label revision here. The task revision
        # is exclusively the frozen configuration revision.
        assignment.task_revision = task.task_revision
    elif assignment.task_revision != task_revision:
        raise AssignmentError("assignment revision is stale", "ASSIGNMENT_REVISION_CONFLICT")
    transitions = {
        "pause": {"pending": "paused", "edit_for_return": "paused"},
        "resume": {"paused": "__restore__"},
        "revoke": {"pending": "revoked", "paused": "revoked", "edit_for_return": "revoked"},
    }
    next_state = transitions.get(action, {}).get(assignment.state)
    if next_state is None:
        raise AssignmentError("assignment state transition is invalid", "ASSIGNMENT_STATE_INVALID")
    previous_state = assignment.state
    if action == "pause":
        assignment.paused_from_state = previous_state
    elif action == "resume":
        next_state = assignment.paused_from_state or "pending"
        if next_state not in {"pending", "edit_for_return"}:
            raise AssignmentError("assignment state transition is invalid", "ASSIGNMENT_STATE_INVALID")
        assignment.paused_from_state = None
    elif action == "revoke":
        assignment.paused_from_state = None
    assignment.state = next_state
    if idempotency_key:
        command_operation = DurableOperation(
            project_id=task.project_id if task is not None else None,
            task_id=task.id if task is not None else None,
            resource_type="annotation_assignment_command",
            resource_key=f"annotation-assignment-command:{assignment.id}:{actor_id}:{action}",
            idempotency_key=idempotency_key,
            request_fingerprint=command_fingerprint,
            state="completed",
            stage="completed",
            progress=100,
        )
        db.add(command_operation)
        db.flush()
    if task is not None:
        db.add(AuditEvent(
            project_id=task.project_id,
            actor_id=actor_id,
            actor_username=getattr(actor, "username", str(actor_id)),
            action=f"annotation_assignment.{action}",
            resource_type="annotation_assignment",
            resource_id=str(assignment.id),
            result="success",
            request_id=request_id or uuid.uuid4(),
            changes={
                "from_state": previous_state,
                "to_state": next_state,
                "task_revision": task_revision,
                **({"idempotency_key": idempotency_key} if idempotency_key else {}),
            },
        ))
    response = {
        "id": str(assignment.id),
        "task_id": str(assignment.task_id),
        "annotator_subject_id": str(assignment.annotator_subject_id),
        "sample_scope": assignment.sample_scope or {},
        "scope_hash": assignment.scope_hash,
        "state": assignment.state,
        "task_revision": assignment.task_revision,
        "due_at": assignment.due_at.isoformat() if assignment.due_at else None,
    }
    if command_operation is not None:
        response["operation_id"] = str(command_operation.id)
        command_operation.result_summary = {"response": response}
    db.commit()
    db.refresh(assignment)
    if command_operation is not None:
        assignment._command_operation_id = command_operation.id
        assignment._command_response_payload = response
    return assignment


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
    access_actor=None,
    commit: bool = True,
):
    assignment = db.get(AnnotationAssignment, assignment_id)
    if assignment is None:
        raise AssignmentError("assignment not found", "ASSIGNMENT_NOT_FOUND")
    if assignment.state in {"paused", "returned_pending_acceptance", "revoked"}:
        raise AssignmentLockedError()
    task = _task_context(db, assignment.task_id)
    if task is not None:
        _ensure_task_allows_label_write(task, assignment)
        if access_actor is not None:
            _ensure_task_access(db, task, access_actor)
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
    current = None
    if task is not None and task.label_schema_id:
        current = db.query(AnnotationSampleCurrent).filter_by(
            task_id=task.id,
            sample_id=sample_id,
        ).one_or_none()
        if current is not None:
            if current.schema_id != task.label_schema_id:
                raise AssignmentError("current label state uses another schema", "LABEL_SCHEMA_MISMATCH")
            if current.revision_no != base_revision:
                return RevisionConflict(current.revision_no, dict(current.values or {}), {"sample_id": sample_id})
            updated = db.query(AnnotationSampleCurrent).filter(
                AnnotationSampleCurrent.id == current.id,
                AnnotationSampleCurrent.revision_no == base_revision,
            ).update({
                AnnotationSampleCurrent.values: dict(merged),
                AnnotationSampleCurrent.revision_no: next_revision,
            }, synchronize_session=False)
            if updated != 1:
                db.rollback()
                latest = db.query(AnnotationSampleCurrent).filter_by(task_id=task.id, sample_id=sample_id).one_or_none()
                if latest is not None:
                    return RevisionConflict(latest.revision_no, dict(latest.values or {}), {"sample_id": sample_id})
                raise AssignmentError("current label state was not found", "LABEL_SAMPLE_NOT_FOUND")
        else:
            db.add(AnnotationSampleCurrent(
                task_id=task.id,
                sample_id=sample_id,
                schema_id=task.label_schema_id,
                revision_no=next_revision,
                values=dict(merged),
            ))
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
            sibling_assignment.last_edit_revision = next_revision
            if task is None:
                sibling_assignment.task_revision = next_revision
            if sibling_assignment.state in {"edit_for_return", "returned_pending_acceptance"}:
                sibling_assignment.state = "pending"
    row = next(item for item in siblings if item.assignment_id == assignment.id)
    assignment.last_edit_revision = next_revision
    if task is None:
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
        if task.status in {"awaiting_return", "returned_pending_acceptance"}:
            task.status = "in_progress"
        stale_batches = db.query(AnnotationReturnBatch).join(
            AnnotationAssignment,
            AnnotationAssignment.id == AnnotationReturnBatch.assignment_id,
        ).join(
            AnnotationAssignmentSample,
            AnnotationAssignmentSample.assignment_id == AnnotationAssignment.id,
        ).filter(
            AnnotationAssignment.task_id == task.id,
            AnnotationAssignmentSample.sample_id == sample_id,
            AnnotationReturnBatch.state.in_(("pending", "returned_for_changes")),
        ).all()
        for stale_batch in stale_batches:
            stale_batch.state = "superseded"
    if commit:
        db.commit()
    return LabelWriteResult(merged, row.revision_no)


def edit_for_return(db: Session, assignment_id, task_revision: int):
    assignment = db.get(AnnotationAssignment, assignment_id)
    if assignment is None:
        raise AssignmentError("assignment not found", "ASSIGNMENT_NOT_FOUND")
    task = _task_context(db, assignment.task_id)
    if task is not None:
        _ensure_task_allows_return_edit(task)
    if task is not None:
        if task.task_revision != task_revision:
            raise AssignmentError("assignment revision is stale", "ASSIGNMENT_REVISION_CONFLICT")
        assignment.task_revision = task.task_revision
    elif task_revision != assignment.task_revision:
        raise AssignmentError("assignment revision is stale", "ASSIGNMENT_REVISION_CONFLICT")
    if assignment.state != "returned_pending_acceptance":
        raise AssignmentLockedError()
    assignment.state = "edit_for_return"
    db.commit()
    return assignment


def _assignment_sample_batches(db: Session, assignment_id, batch_size: int = 500):
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


def _revision_confirmation(db: Session, task_id, sample_id: str, revision_no: int):
    revision = db.query(AnnotationRevision).filter_by(
        task_id=task_id,
        sample_id=sample_id,
        revision_no=revision_no,
    ).one_or_none()
    if revision is None:
        return None, None
    confirmation = db.query(AnnotationConfirmation).filter(
        AnnotationConfirmation.task_id == task_id,
        AnnotationConfirmation.sample_id == sample_id,
        AnnotationConfirmation.revision_id == revision.id,
        AnnotationConfirmation.action == "confirm",
    ).order_by(AnnotationConfirmation.created_at.desc()).first()
    return revision, confirmation


def _validate_assignment_for_return(db: Session, assignment: AnnotationAssignment, task: GenericAnnotationTask | None):
    if task is None:
        return {"validated_row_count": sum(1 for _ in _assignment_sample_batches(db, assignment.id))}
    contract = _task_schema_contract(db, task)
    row_count = 0
    for rows in _assignment_sample_batches(db, assignment.id):
        for row in rows:
            row_count += 1
            if contract is not None:
                try:
                    validate_label_values(contract, row.values or {}, allow_partial=False)
                except ValueError as error:
                    code = getattr(error, "code", "LABEL_VALUE_INVALID")
                    if code == "LABEL_REQUIRED_MISSING":
                        code = "ANNOTATION_NOT_READY"
                    raise AssignmentError(str(error), code) from error
            current = db.query(AnnotationSampleCurrent).filter_by(
                task_id=task.id,
                sample_id=row.sample_id,
            ).one_or_none()
            revision_no = current.revision_no if current is not None else row.revision_no
            if current is None or current.revision_no != row.revision_no:
                raise AssignmentError(
                    "assignment labels are stale",
                    "ASSIGNMENT_REVISION_CONFLICT",
                )
            _revision, confirmation = _revision_confirmation(
                db, task.id, row.sample_id, revision_no,
            )
            if confirmation is None:
                raise AssignmentError(
                    "all samples must be confirmed before return",
                    "ANNOTATION_NOT_READY",
                )
    if row_count == 0:
        raise AssignmentError("assignment has no samples", "ASSIGNMENT_SCOPE_INVALID")
    return {"validated_row_count": row_count}


def confirm_assignment(
    db: Session,
    assignment_id,
    task_revision: int,
    scope_hash: str,
    actor=None,
    access_actor=None,
):
    assignment = db.get(AnnotationAssignment, assignment_id)
    if assignment is None:
        raise AssignmentError("assignment not found", "ASSIGNMENT_NOT_FOUND")
    if assignment.state in {"paused", "revoked", "returned_pending_acceptance"}:
        raise AssignmentLockedError()
    if assignment.scope_hash != scope_hash:
        raise AssignmentError("assignment revision or scope is stale", "ASSIGNMENT_REVISION_CONFLICT")
    task = _task_context(db, assignment.task_id)
    if task is not None:
        _ensure_task_allows_confirmation(task)
        if access_actor is not None:
            _ensure_task_access(db, task, access_actor)
        if task.task_revision != task_revision:
            raise AssignmentError("assignment revision or scope is stale", "ASSIGNMENT_REVISION_CONFLICT")
        assignment.task_revision = task.task_revision
        contract = _task_schema_contract(db, task)
    else:
        if assignment.task_revision != task_revision:
            raise AssignmentError("assignment revision or scope is stale", "ASSIGNMENT_REVISION_CONFLICT")
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
        confirmer_id = getattr(actor, "id", actor) or assignment.created_by
        for row in rows:
            current = db.query(AnnotationSampleCurrent).filter_by(
                task_id=task.id,
                sample_id=row.sample_id,
            ).one_or_none()
            revision_no = current.revision_no if current is not None else row.revision_no
            revision, _existing = _revision_confirmation(db, task.id, row.sample_id, revision_no)
            if revision is None:
                raise AssignmentError("label revision not found", "LABEL_REVISION_NOT_FOUND")
            if _existing is None:
                db.add(AnnotationConfirmation(
                    task_id=task.id,
                    sample_id=row.sample_id,
                    revision_id=revision.id,
                    confirmer_id=confirmer_id,
                    action="confirm",
                ))
        _refresh_global_annotation_state(db, task, contract)
        db.commit()
    return ConfirmationResult(assignment.id, task_revision, scope_hash)


def _refresh_global_annotation_state(db: Session, task: GenericAnnotationTask, contract) -> None:
    """Derive the task-level completion state from the frozen sample scope."""
    if task.status in {"paused", "cancelled", "archived", "completed", "accepted"}:
        return
    snapshot = current_annotation_task_snapshot(db, task)
    complete = True
    seen_scope_rows = False
    for scope_batch in iter_scope_batches(
        db,
        task,
        task_revision=task.task_revision,
        snapshot=snapshot,
    ):
        seen_scope_rows = True
        sample_ids = [sample_id for sample_id, _ in scope_batch]
        current_rows = db.query(AnnotationSampleCurrent).filter(
            AnnotationSampleCurrent.task_id == task.id,
            AnnotationSampleCurrent.sample_id.in_(sample_ids),
        ).limit(len(sample_ids)).all()
        current = {str(row.sample_id): row for row in current_rows}
        if len(current) != len(sample_ids):
            complete = False
            break
        if contract is not None:
            for sample_id in sample_ids:
                try:
                    validate_label_values(contract, current[sample_id].values or {}, allow_partial=False)
                except ValueError:
                    complete = False
                    break
                _revision, confirmation = _revision_confirmation(
                    db, task.id, sample_id, current[sample_id].revision_no,
                )
                if confirmation is None:
                    complete = False
                    break
        if not complete:
            break
    if not seen_scope_rows:
        complete = False
    task.status = "awaiting_return" if complete else "in_progress"


def _has_failed_pending_batch(db: Session, assignment: AnnotationAssignment) -> bool:
    """判断 assignment 是否存在冻结操作已失败的 pending 回传批次。"""
    rows = db.query(AnnotationReturnBatch).filter(
        AnnotationReturnBatch.assignment_id == assignment.id,
        AnnotationReturnBatch.state == "pending",
    ).all()
    for row in rows:
        if row.operation_id is None:
            return True
        operation = db.get(DurableOperation, row.operation_id)
        if operation is not None and operation.state == "failed":
            return True
    return False


def return_assignment(db: Session, assignment_id, task_revision: int, scope_hash: str, idempotency_key: str):
    assignment = db.get(AnnotationAssignment, assignment_id)
    if assignment is None:
        raise AssignmentError("assignment not found", "ASSIGNMENT_NOT_FOUND")
    existing = db.query(AnnotationReturnBatch).filter_by(assignment_id=assignment.id, idempotency_key=idempotency_key).one_or_none()
    if existing is not None:
        return ReturnBatchRef(existing.id, existing.state, existing.operation_id)
    if assignment.state in {"paused", "revoked", "returned_pending_acceptance", "edit_for_return"}:
        if assignment.state != "returned_pending_acceptance" or not _has_failed_pending_batch(db, assignment):
            raise AssignmentLockedError()
        # 自愈：冻结操作失败后批次停留在 pending 且 assignment 被锁在
        # returned_pending_acceptance，审核端验收/退回同样被 NOT_READY 挡住，
        # 形成死锁。这里放行重新回传，旧批次会在下方被标记为 superseded。
    task = _task_context(db, assignment.task_id)
    if task is not None:
        _ensure_task_writable(task)
        if task.task_revision != task_revision:
            raise AssignmentError("assignment revision or scope is stale", "ASSIGNMENT_REVISION_CONFLICT")
        assignment.task_revision = task.task_revision
        if task.status != "awaiting_return":
            raise AssignmentError(
                "labels changed after confirmation; confirm the task again before return",
                "ANNOTATION_NOT_READY",
            )
    elif assignment.task_revision != task_revision:
        raise AssignmentError("assignment revision or scope is stale", "ASSIGNMENT_REVISION_CONFLICT")
    if assignment.scope_hash != scope_hash:
        raise AssignmentError("assignment revision or scope is stale", "ASSIGNMENT_REVISION_CONFLICT")
    _validate_assignment_for_return(db, assignment, task)
    if task is not None:
        pending_batches = db.query(AnnotationReturnBatch).join(
            AnnotationAssignment,
            AnnotationAssignment.id == AnnotationReturnBatch.assignment_id,
        ).filter(
            AnnotationAssignment.task_id == task.id,
            AnnotationReturnBatch.scope_hash == scope_hash,
            AnnotationReturnBatch.state.in_(("pending", "returned_for_changes")),
        ).all()
    else:
        pending_batches = db.query(AnnotationReturnBatch).filter(
            AnnotationReturnBatch.assignment_id == assignment.id,
            AnnotationReturnBatch.scope_hash == scope_hash,
            AnnotationReturnBatch.state.in_(("pending", "returned_for_changes")),
        ).all()
    for pending in pending_batches:
        pending.state = "superseded"
    batch = AnnotationReturnBatch(
        assignment_id=assignment.id,
        task_revision=task.task_revision if task is not None else task_revision,
        scope_hash=scope_hash,
        idempotency_key=idempotency_key,
        state="pending",
    )
    db.add(batch)
    db.flush()
    operation = DurableOperation(
        project_id=task.project_id if task is not None else None,
        task_id=task.id if task is not None else None,
        resource_type="annotation_return",
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
