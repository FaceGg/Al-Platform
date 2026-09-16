"""State transitions and preview operations for generic annotation tasks."""

import hashlib
import json
import uuid
from copy import deepcopy
from datetime import datetime, timezone
from sqlalchemy import and_, or_, true

from app.models.access import AuditEvent
from app.models.operation import DurableOperation
from app.models.platform_models import (
    AnnotationTaskExecutionResult,
    AnnotationTaskExecutionStatistic,
    AnnotationTaskPreview,
    AnnotationTaskPreviewSample,
    AnnotationTaskRevisionSnapshot,
    GenericAnnotationTask,
)
from app.schemas.annotation_tasks import TaskAction

_TRANSITIONS = {
    "draft": {TaskAction.cancel: "cancelled"},
    "preview_ready": {
        TaskAction.publish: "awaiting_annotation",
        TaskAction.execute: "executing",
        TaskAction.pause: "paused",
        TaskAction.cancel: "cancelled",
    },
    "executing": {
        TaskAction.pause: "paused",
        TaskAction.cancel: "cancelled",
    },
    "awaiting_annotation": {
        TaskAction.pause: "paused",
        TaskAction.cancel: "cancelled",
    },
    "in_progress": {
        TaskAction.pause: "paused",
        TaskAction.cancel: "cancelled",
    },
    "awaiting_return": {
        TaskAction.return_: "returned_pending_acceptance",
        TaskAction.pause: "paused",
        TaskAction.cancel: "cancelled",
    },
    "returned_pending_acceptance": {TaskAction.accept: "accepted"},
    "accepted": {TaskAction.complete: "completed", TaskAction.archive: "archived"},
    "completed": {TaskAction.archive: "archived", TaskAction.reopen: "in_progress"},
    "paused": {TaskAction.resume: "__restore__", TaskAction.cancel: "cancelled"},
    "cancelled": {TaskAction.archive: "archived"},
    "archived": {TaskAction.restore: "completed"},
    "failed": {TaskAction.cancel: "cancelled"},
    "needs_review": {TaskAction.cancel: "cancelled"},
}


def _task_or_error(db, task_id, owner_id=None):
    query = db.query(GenericAnnotationTask).filter(GenericAnnotationTask.id == task_id)
    if owner_id is not None:
        query = query.filter(GenericAnnotationTask.owner_id == owner_id)
    task = query.one_or_none()
    if task is None:
        raise ValueError("TASK_NOT_FOUND")
    return task


def _created_id_page(query, model, cursor, limit):
    """Read one stable keyset page ordered by creation time then UUID."""
    total = query.count()
    if cursor:
        try:
            marker_id = uuid.UUID(str(cursor))
        except (ValueError, AttributeError) as error:
            raise ValueError("INVALID_CURSOR") from error
        marker = query.filter(model.id == marker_id).one_or_none()
        if marker is None:
            raise ValueError("INVALID_CURSOR")
        # Compare database values rather than a Python datetime parameter.
        # SQLite stores CURRENT_TIMESTAMP at second precision while its
        # SQLAlchemy bind processor renders a zero microsecond suffix.
        marker_values = query.with_entities(
            model.created_at.label("cursor_created_at"),
            model.id.label("cursor_id"),
        ).filter(model.id == marker_id).subquery()
        query = query.join(marker_values, true())
        query = query.filter(or_(
            model.created_at < marker_values.c.cursor_created_at,
            and_(model.created_at == marker_values.c.cursor_created_at, model.id < marker_values.c.cursor_id),
        ))
    rows = query.order_by(model.created_at.desc(), model.id.desc()).limit(limit + 1).all()
    has_next = len(rows) > limit
    return rows[:limit], total, has_next


def _row_id_page(query, model, cursor, limit):
    """Read one stable keyset page ordered by source row then UUID."""
    total = query.count()
    if cursor:
        try:
            marker_id = uuid.UUID(str(cursor))
        except (ValueError, AttributeError) as error:
            raise ValueError("INVALID_CURSOR") from error
        marker = query.filter(model.id == marker_id).one_or_none()
        if marker is None:
            raise ValueError("INVALID_CURSOR")
        query = query.filter(or_(
            model.row_index > marker.row_index,
            and_(model.row_index == marker.row_index, model.id > marker.id),
        ))
    rows = query.order_by(model.row_index.asc(), model.id.asc()).limit(limit + 1).all()
    has_next = len(rows) > limit
    return rows[:limit], total, has_next


def create_annotation_preview(db, task_id, task_revision: int, config_hash: str, actor_id):
    task = _task_or_error(db, task_id, actor_id)
    if task.task_revision != task_revision:
        raise ValueError("TASK_REVISION_CONFLICT")
    existing = db.query(AnnotationTaskPreview).filter_by(task_id=task.id, task_revision=task_revision, config_hash=config_hash).one_or_none()
    if existing is not None:
        existing._created_now = False
        return existing
    previous_status = task.status
    if task.status in {"pending", "draft", "failed", "preview_ready"}:
        task.status = "previewing"
    elif task.status != "previewing":
        raise ValueError("TASK_STATE_INVALID")
    preview = AnnotationTaskPreview(task_id=task.id, task_revision=task_revision, config_hash=config_hash, created_by=actor_id, status="queued", summary={"sample_scope": task.sample_scope or {}})
    db.add(preview)
    db.flush()
    db.add(
        DurableOperation(
            id=preview.operation_id,
            project_id=task.project_id,
            task_id=task.id,
            preview_id=preview.id,
            resource_type="annotation_preview",
            resource_key=f"annotation-preview:{preview.id}",
            idempotency_key=config_hash,
            state="queued",
            stage="queued",
            progress=0,
            attempt=0,
            created_at=datetime.now(timezone.utc).replace(tzinfo=None),
            updated_at=datetime.now(timezone.utc).replace(tzinfo=None),
        )
    )
    if previous_status != task.status:
        db.add(AuditEvent(
            project_id=task.project_id,
            actor_id=actor_id,
            actor_username=getattr(getattr(task, "owner", None), "username", str(actor_id)),
            action="annotation_task.preview_requested",
            resource_type="annotation_task",
            resource_id=str(task.id),
            result="success",
            request_id=uuid.uuid4(),
            changes={"from_status": previous_status, "to_status": task.status, "task_revision": task.task_revision},
        ))
    db.commit()
    db.refresh(preview)
    preview._created_now = True
    return preview


def _task_command_fingerprint(action: TaskAction, task_revision: int, preview_id=None, reason: str | None = None) -> str:
    payload = {
        "action": action.value,
        "task_revision": int(task_revision),
        "preview_id": str(preview_id) if preview_id is not None else None,
        "reason": reason,
    }
    encoded = json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _task_command_resource_key(task_id, actor_id, action: TaskAction) -> str:
    return f"annotation-task-command:{task_id}:{actor_id}:{action.value}"


def _task_command_response(task):
    return {
        "id": str(task.id),
        "project_id": str(task.project_id),
        "dataset_version_id": str(task.dataset_version_id),
        "label_schema_id": str(task.label_schema_id),
        "mode": task.mode,
        "status": task.status,
        "task_revision": task.task_revision,
        "sample_scope": task.sample_scope or {},
        "source_legacy_id": task.source_legacy_id,
    }


def transition_annotation_task(
    db,
    task_id,
    expected_revision: int,
    action: TaskAction,
    actor_id,
    preview_id=None,
    idempotency_key: str | None = None,
    request_id=None,
    reason: str | None = None,
):
    task = _task_or_error(db, task_id, actor_id)
    command_operation = None
    command_fingerprint = None
    if idempotency_key:
        if len(idempotency_key) > 128:
            raise ValueError("IDEMPOTENCY_KEY_INVALID")
        command_fingerprint = _task_command_fingerprint(action, expected_revision, preview_id, reason)
        command_operation = db.query(DurableOperation).filter(
            DurableOperation.resource_key == _task_command_resource_key(task.id, actor_id, action),
            DurableOperation.idempotency_key == idempotency_key,
        ).one_or_none()
        if command_operation is not None:
            if command_operation.request_fingerprint != command_fingerprint:
                raise ValueError("IDEMPOTENCY_CONFLICT")
            stored = dict(command_operation.result_summary or {}).get("response")
            task._command_operation_id = command_operation.id
            task._command_replayed = True
            task._command_response_payload = stored if isinstance(stored, dict) else _task_command_response(task)
            return task
    if task.task_revision != expected_revision:
        raise ValueError("TASK_REVISION_CONFLICT")
    if action == TaskAction.reopen and idempotency_key and (reason is None or not reason.strip()):
        raise ValueError("REOPEN_REASON_REQUIRED")
    if action == TaskAction.publish and task.status != "preview_ready":
        raise ValueError("TASK_STATE_INVALID")
    if action == TaskAction.publish:
        if task.mode != "manual":
            raise ValueError("TASK_STATE_INVALID")
        current_preview = current_annotation_task_preview(db, task)
        if preview_id is not None and (current_preview is None or current_preview.id != preview_id):
            raise ValueError("PREVIEW_STALE")
        if current_preview is None or current_preview.task_revision != expected_revision or current_preview.status != "completed":
            raise ValueError("PREVIEW_STALE")
        preview_summary = dict(current_preview.summary or {})
        if preview_summary.get("configuration_complete") is False:
            raise ValueError("PREVIEW_CONFIGURATION_INCOMPLETE")
        if int(preview_summary.get("needs_review_count", 0) or 0) > 0:
            raise ValueError("PREVIEW_NEEDS_REVIEW")
    if action == TaskAction.execute:
        preview = db.query(AnnotationTaskPreview).filter_by(id=preview_id, task_id=task.id).one_or_none()
        if preview is None or preview.task_revision != expected_revision or preview.status != "completed":
            raise ValueError("PREVIEW_STALE")
        preview_summary = dict(preview.summary or {})
        if preview_summary.get("configuration_complete") is False:
            raise ValueError("PREVIEW_CONFIGURATION_INCOMPLETE")
        if int(preview_summary.get("needs_review_count", 0) or 0) > 0:
            raise ValueError("PREVIEW_NEEDS_REVIEW")
        # Execution has its own durable operation. Keep the preview revision
        # stable while the operation runs so retries resolve to the same
        # operation and workers can validate the immutable binding.
        from app.services.annotation_task_execution import request_annotation_execution
        execution = request_annotation_execution(db, task.id, preview.id, actor_id)
        previous_status = task.status
        db.add(AuditEvent(
            project_id=task.project_id,
            actor_id=actor_id,
            actor_username=getattr(getattr(task, "owner", None), "username", str(actor_id)),
            action="annotation_task.execute_requested",
            resource_type="annotation_task",
            resource_id=str(task.id),
            result="success",
            request_id=request_id or uuid.uuid4(),
            changes={
                "from_status": previous_status,
                "to_status": task.status,
                "task_revision": task.task_revision,
                "preview_id": str(preview.id),
                "operation_id": str(execution.operation_id),
                **({"idempotency_key": idempotency_key} if idempotency_key else {}),
            },
        ))
        db.commit()
        db.refresh(task)
        task._execution_operation_id = execution.operation_id
        task._execution_preview_id = preview.id
        return task
    next_status = _TRANSITIONS.get(task.status, {}).get(action)
    if next_status is None:
        raise ValueError("TASK_STATE_INVALID")
    previous_status = task.status
    if next_status == "__restore__":
        next_status = str(task.paused_from_status or "")
        if next_status not in {"preview_ready", "executing", "awaiting_annotation", "in_progress", "awaiting_return"}:
            raise ValueError("TASK_STATE_INVALID")
    if action == TaskAction.pause:
        task.paused_from_status = previous_status
    elif action == TaskAction.resume:
        task.paused_from_status = None
    task.status = next_status
    # Lifecycle changes do not alter the frozen configuration. Reopening a
    # completed task is the explicit exception: it starts a new revision whose
    # snapshot remains independent from the accepted historical revision.
    if action == TaskAction.reopen:
        snapshot = deepcopy(current_annotation_task_snapshot(db, task))
        task.task_revision += 1
        db.add(AnnotationTaskRevisionSnapshot(
            task_id=task.id,
            task_revision=task.task_revision,
            snapshot=snapshot,
        ))
    if idempotency_key:
        command_operation = DurableOperation(
            project_id=task.project_id,
            task_id=task.id,
            resource_type="annotation_task_command",
            resource_key=_task_command_resource_key(task.id, actor_id, action),
            idempotency_key=idempotency_key,
            request_fingerprint=command_fingerprint,
            state="completed",
            stage="completed",
            progress=100,
        )
        db.add(command_operation)
        db.flush()
    db.add(AuditEvent(
        project_id=task.project_id,
        actor_id=actor_id,
        actor_username=getattr(getattr(task, "owner", None), "username", str(actor_id)),
        action="annotation_task.transition",
        resource_type="annotation_task",
        resource_id=str(task.id),
        result="success",
        request_id=request_id or uuid.uuid4(),
        changes={
            "action": action.value,
            "from_status": previous_status,
            "to_status": next_status,
            "task_revision": task.task_revision,
            **({"reason": reason} if reason else {}),
            **({"idempotency_key": idempotency_key} if idempotency_key else {}),
        },
    ))
    response = _task_command_response(task)
    if command_operation is not None:
        response["operation_id"] = str(command_operation.id)
        command_operation.result_summary = {"response": response}
    db.commit()
    db.refresh(task)
    if command_operation is not None:
        task._command_operation_id = command_operation.id
        task._command_replayed = False
        task._command_response_payload = response
    return task


def serialize_annotation_preview(preview):
    if preview is None:
        return None
    return {
        "id": str(preview.id),
        "operation_id": str(preview.operation_id),
        "task_revision": preview.task_revision,
        "config_hash": preview.config_hash,
        "status": preview.status,
        "progress": preview.progress,
        "summary": preview.summary or {},
        "error": preview.error,
        "completed_at": preview.completed_at.isoformat() if preview.completed_at else None,
    }


def current_annotation_task_snapshot(db, task):
    revision = db.query(AnnotationTaskRevisionSnapshot).filter_by(
        task_id=task.id,
        task_revision=task.task_revision,
    ).one_or_none()
    return revision.snapshot if revision is not None else (task.task_snapshot or {})


def current_annotation_task_preview(db, task):
    """Return the preview that remains actionable after a task-list refresh."""
    query = db.query(AnnotationTaskPreview).filter(
        AnnotationTaskPreview.task_id == task.id,
        AnnotationTaskPreview.task_revision == task.task_revision,
    )
    ordered = query.order_by(AnnotationTaskPreview.created_at.desc(), AnnotationTaskPreview.id.desc())
    expected_hash = str(current_annotation_task_snapshot(db, task).get("config_hash") or "")
    if expected_hash:
        configured = ordered.filter(AnnotationTaskPreview.config_hash == expected_hash).first()
        if configured is not None:
            return configured
    completed = ordered.filter(AnnotationTaskPreview.status == "completed").first()
    return completed or ordered.first()


def serialize_annotation_task(task, preview=None, snapshot=None):
    payload = {
        "id": str(task.id),
        "project_id": str(task.project_id),
        "dataset_version_id": str(task.dataset_version_id),
        "label_schema_id": str(task.label_schema_id),
        "mode": task.mode,
        "status": task.status,
        "task_revision": task.task_revision,
        "sample_scope": task.sample_scope or {},
        "task_snapshot": snapshot if snapshot is not None else task.task_snapshot or {},
        "source_legacy_id": task.source_legacy_id,
        "preview": serialize_annotation_preview(preview),
    }
    operation_id = getattr(task, "_execution_operation_id", None)
    if operation_id is not None:
        payload["operation_id"] = str(operation_id)
    return payload


def list_annotation_tasks(db, project_id, owner_id, cursor=None, limit=50):
    limit = max(1, min(int(limit), 200))
    base_query = db.query(GenericAnnotationTask).filter(
        GenericAnnotationTask.owner_id == owner_id,
        GenericAnnotationTask.archived_at.is_(None),
    )
    if project_id is not None:
        base_query = base_query.filter(GenericAnnotationTask.project_id == project_id)
    items, total, has_next = _created_id_page(base_query, GenericAnnotationTask, cursor, limit)
    return {
        "items": [
            serialize_annotation_task(item, current_annotation_task_preview(db, item), current_annotation_task_snapshot(db, item))
            for item in items
        ],
        "total": total,
        "next_cursor": str(items[-1].id) if has_next and items else None,
    }


def mark_preview_completed(db, task_id, preview_id, owner_id, *, commit: bool = True):
    preview = get_annotation_preview(db, task_id, preview_id, owner_id)
    task = _task_or_error(db, task_id, owner_id)
    if preview.status != "completed":
        raise ValueError("PREVIEW_NOT_COMPLETED")
    if preview.task_revision != task.task_revision:
        raise ValueError("TASK_REVISION_CONFLICT")
    if task.status == "previewing":
        summary = dict(preview.summary or {})
        if summary.get("configuration_complete") is False or int(summary.get("needs_review_count", 0) or 0) > 0:
            task.status = "needs_review"
        else:
            task.status = "preview_ready"
        db.add(AuditEvent(
            project_id=task.project_id,
            actor_id=owner_id,
            actor_username=getattr(getattr(task, "owner", None), "username", str(owner_id)),
            action="annotation_task.preview_completed",
            resource_type="annotation_task",
            resource_id=str(task.id),
            result="success",
            request_id=uuid.uuid4(),
            changes={"from_status": "previewing", "to_status": task.status, "task_revision": task.task_revision},
        ))
        if commit:
            db.commit()
            db.refresh(task)
    return task


def list_annotation_previews(db, task_id, owner_id, cursor=None, limit=50):
    _task_or_error(db, task_id, owner_id)
    limit = max(1, min(int(limit), 200))
    query = db.query(AnnotationTaskPreview).filter(AnnotationTaskPreview.task_id == task_id)
    items, total, has_next = _created_id_page(query, AnnotationTaskPreview, cursor, limit)
    return {
        "items": [serialize_annotation_preview(item) for item in items],
        "total": total,
        "next_cursor": str(items[-1].id) if has_next and items else None,
    }


def get_annotation_preview(db, task_id, preview_id, owner_id):
    _task_or_error(db, task_id, owner_id)
    preview = db.query(AnnotationTaskPreview).filter_by(id=preview_id, task_id=task_id).one_or_none()
    if preview is None:
        raise ValueError("PREVIEW_NOT_FOUND")
    return preview


def record_annotation_preview_progress(
    db,
    task_id,
    preview_id,
    owner_id,
    *,
    status,
    progress,
    summary=None,
    error=None,
    commit: bool = True,
):
    preview = get_annotation_preview(db, task_id, preview_id, owner_id)
    progress = int(progress)
    if progress < preview.progress:
        raise ValueError("PREVIEW_PROGRESS_REGRESSION")
    if progress < 0 or progress > 100:
        raise ValueError("PREVIEW_PROGRESS_INVALID")
    preview.progress = progress
    preview.status = status
    if summary is not None:
        preview.summary = summary
    preview.error = error
    if status == "completed":
        preview.progress = 100
        preview.completed_at = datetime.now(timezone.utc).replace(tzinfo=None)
    if commit:
        db.commit()
        db.refresh(preview)
    return preview


def list_annotation_preview_samples(db, task_id, preview_id, owner_id, cursor=None, limit=50):
    get_annotation_preview(db, task_id, preview_id, owner_id)
    limit = max(1, min(int(limit), 200))
    query = db.query(AnnotationTaskPreviewSample).filter_by(preview_id=preview_id)
    items, total, has_next = _row_id_page(query, AnnotationTaskPreviewSample, cursor, limit)
    return {"items": [{"id": str(item.id), "sample_id": item.sample_id, "row_index": item.row_index, "values": item.values or {}} for item in items], "total": total, "next_cursor": str(items[-1].id) if has_next and items else None}


def _execution_operation_or_error(db, task_id, operation_id, owner_id):
    task = _task_or_error(db, task_id, owner_id)
    operation = db.query(DurableOperation).filter_by(id=operation_id).one_or_none()
    if operation is None or operation.resource_key != f"annotation-execution:{task.id}":
        raise ValueError("OPERATION_NOT_FOUND")
    try:
        revision_token, preview_token = operation.idempotency_key.split(":", 1)
        revision = int(revision_token)
        preview_id = uuid.UUID(preview_token)
    except (ValueError, TypeError):
        raise ValueError("OPERATION_NOT_FOUND")
    preview = db.query(AnnotationTaskPreview).filter_by(id=preview_id, task_id=task.id).one_or_none()
    if preview is None or preview.task_revision != revision:
        raise ValueError("OPERATION_NOT_FOUND")
    return task, operation


def list_annotation_execution_results(db, task_id, operation_id, owner_id, cursor=None, limit=50):
    _task, operation = _execution_operation_or_error(db, task_id, operation_id, owner_id)
    limit = max(1, min(int(limit), 200))
    query = db.query(AnnotationTaskExecutionResult).filter_by(task_id=task_id, operation_id=operation.id).order_by(
        AnnotationTaskExecutionResult.row_index.asc(), AnnotationTaskExecutionResult.id.asc()
    )
    total = query.count()
    if cursor:
        try:
            marker_id = uuid.UUID(cursor)
        except (ValueError, AttributeError) as error:
            raise ValueError("INVALID_CURSOR") from error
        marker = query.filter(AnnotationTaskExecutionResult.id == marker_id).one_or_none()
        if marker is None:
            raise ValueError("INVALID_CURSOR")
        query = query.filter(or_(
            AnnotationTaskExecutionResult.row_index > marker.row_index,
            and_(AnnotationTaskExecutionResult.row_index == marker.row_index, AnnotationTaskExecutionResult.id > marker.id),
        ))
    items = query.limit(limit + 1).all()
    has_next = len(items) > limit
    items = items[:limit]
    return {
        "items": [
            {"id": str(item.id), "sample_id": item.sample_id, "row_index": item.row_index, "task_revision": item.task_revision, "values": item.values or {}, "provenance": item.provenance or {}, "status": item.status}
            for item in items
        ],
        "total": total,
        "next_cursor": str(items[-1].id) if has_next and items else None,
    }


def list_annotation_execution_stats(db, task_id, operation_id, owner_id, *, kind="sample", cursor=None, limit=50):
    _task, operation = _execution_operation_or_error(db, task_id, operation_id, owner_id)
    if kind not in {"sample", "cluster", "rule", "final_label"}:
        raise ValueError("INVALID_STATS_KIND")
    limit = max(1, min(int(limit), 200))
    if kind == "sample":
        query = db.query(AnnotationTaskExecutionResult).filter_by(task_id=task_id, operation_id=operation.id).order_by(
            AnnotationTaskExecutionResult.row_index.asc(), AnnotationTaskExecutionResult.id.asc()
        )
        total = query.count()
        if cursor:
            try:
                marker_id = uuid.UUID(cursor)
            except (ValueError, AttributeError) as error:
                raise ValueError("INVALID_CURSOR") from error
            marker = query.filter(AnnotationTaskExecutionResult.id == marker_id).one_or_none()
            if marker is None:
                raise ValueError("INVALID_CURSOR")
            query = query.filter(or_(
                AnnotationTaskExecutionResult.row_index > marker.row_index,
                and_(AnnotationTaskExecutionResult.row_index == marker.row_index, AnnotationTaskExecutionResult.id > marker.id),
            ))
        page = query.limit(limit + 1).all()
        has_next = len(page) > limit
        page = page[:limit]
        items = [{"key": str(item.id), "sample_id": item.sample_id, "row_index": item.row_index, "status": item.status} for item in page]
        next_cursor = str(page[-1].id) if has_next and page else None
    else:
        query = db.query(AnnotationTaskExecutionStatistic).filter_by(
            task_id=task_id,
            operation_id=operation.id,
            kind=kind,
        )
        total = query.count()
        if cursor:
            try:
                marker_id = uuid.UUID(cursor)
            except (ValueError, AttributeError) as error:
                raise ValueError("INVALID_CURSOR") from error
            marker = query.filter(AnnotationTaskExecutionStatistic.id == marker_id).one_or_none()
            if marker is None:
                raise ValueError("INVALID_CURSOR")
            query = query.filter(or_(
                AnnotationTaskExecutionStatistic.sort_key > marker.sort_key,
                and_(
                    AnnotationTaskExecutionStatistic.sort_key == marker.sort_key,
                    AnnotationTaskExecutionStatistic.id > marker.id,
                ),
            ))
        page = query.order_by(
            AnnotationTaskExecutionStatistic.sort_key.asc(),
            AnnotationTaskExecutionStatistic.id.asc(),
        ).limit(limit + 1).all()
        has_next = len(page) > limit
        page = page[:limit]
        items = [
            {**(item.payload or {}), "count": item.count}
            for item in page
        ]
        next_cursor = str(page[-1].id) if has_next and page else None
    return {"items": items, "total": total, "next_cursor": next_cursor}


def list_annotation_operations(db, project_id, owner_id, cursor=None, limit=50):
    limit = max(1, min(int(limit), 200))
    query = db.query(DurableOperation).join(
        GenericAnnotationTask,
        GenericAnnotationTask.id == DurableOperation.task_id,
    ).filter(
        DurableOperation.project_id == project_id,
        GenericAnnotationTask.project_id == project_id,
        GenericAnnotationTask.owner_id == owner_id,
    )
    operations, total, has_next = _created_id_page(
        query,
        DurableOperation,
        cursor,
        limit,
    )
    items = [
        {
            "id": str(operation.id),
            "resource_type": operation.resource_type,
            "task_id": str(operation.task_id),
            "preview_id": str(operation.preview_id) if operation.preview_id else None,
            "state": operation.state,
            "stage": operation.stage,
            "progress": operation.progress,
            "attempt": operation.attempt,
            "error_code": operation.error_code,
            "checksum": operation.checksum,
            "result_summary": operation.result_summary or {},
            "created_at": operation.created_at.isoformat() if operation.created_at else None,
        }
        for operation in operations
    ]
    return {
        "items": items,
        "total": total,
        "next_cursor": str(operations[-1].id) if has_next and operations else None,
    }
