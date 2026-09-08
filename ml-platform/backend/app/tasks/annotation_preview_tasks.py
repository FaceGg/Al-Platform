"""Durable preview execution for generic annotation tasks."""

import uuid

from app.database import SessionLocal
from app.models.platform_models import AnnotationTaskPreview, GenericAnnotationTask
from app.services.annotation_task_state import record_annotation_preview_progress
from app.tasks.celery_app import celery_app
from app.config import settings


def enqueue_annotation_preview(task_id, preview_id, owner_id):
    """Dispatch only when Celery is the configured runtime; local mode stays queued."""
    if settings.task_backend != "celery":
        return None
    return execute_annotation_preview.delay(str(task_id), str(preview_id), str(owner_id))


@celery_app.task(bind=True, name="ml_platform.execute_annotation_preview")
def execute_annotation_preview(self, task_id: str, preview_id: str, owner_id: str):
    task_uuid = uuid.UUID(task_id)
    preview_uuid = uuid.UUID(preview_id)
    owner_uuid = uuid.UUID(owner_id)
    with SessionLocal() as db:
        task = db.query(GenericAnnotationTask).filter_by(id=task_uuid, owner_id=owner_uuid).one_or_none()
        preview = db.query(AnnotationTaskPreview).filter_by(id=preview_uuid, task_id=task_uuid).one_or_none()
        if task is None or preview is None:
            return {"status": "not_found", "preview_id": preview_id}
        record_annotation_preview_progress(db, task_uuid, preview_uuid, owner_uuid, status="running", progress=10, summary={"sample_scope": task.task_snapshot.get("sample_ids", []), "visible_columns": task.task_snapshot.get("visible_columns", [])})
        summary = {
            "sample_count": len(task.task_snapshot.get("sample_ids", [])),
            "visible_columns": task.task_snapshot.get("visible_columns", []),
            "label_columns": [column.get("machine_key") for column in task.task_snapshot.get("label_schema", {}).get("columns", [])],
        }
        record_annotation_preview_progress(db, task_uuid, preview_uuid, owner_uuid, status="completed", progress=100, summary=summary)
        return {"status": "completed", "preview_id": preview_id, "operation_id": str(preview.operation_id)}
