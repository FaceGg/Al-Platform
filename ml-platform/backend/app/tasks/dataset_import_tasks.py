"""Durable asynchronous dataset import and schema confirmation workers."""

import threading
import uuid

from app.config import settings
from app.database import SessionLocal
from app.services.data_import import execute_dataset_import_confirmation, process_dataset_import
try:
    from app.tasks.celery_app import celery_app
except (ImportError, SyntaxError):
    # Keep this worker importable while an unrelated optional task module is
    # being developed; the normal application path uses the shared app.
    from celery import Celery

    celery_app = Celery("ml_platform_dataset_import")


def _run_in_thread(function, process_id):
    def run():
        db = SessionLocal()
        try:
            function(db, uuid.UUID(str(process_id)), worker_id=f"local:{process_id}")
        finally:
            db.close()

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    return f"local:{thread.ident or process_id}"


def enqueue_dataset_import(process_id):
    if settings.task_backend == "celery":
        return execute_dataset_import.delay(str(process_id))
    return _run_in_thread(process_dataset_import, process_id)


def enqueue_dataset_import_confirmation(process_id):
    if settings.task_backend == "celery":
        return execute_dataset_import_confirmation_task.delay(str(process_id))
    return _run_in_thread(execute_dataset_import_confirmation, process_id)


@celery_app.task(bind=True, name="ml_platform.execute_dataset_import")
def execute_dataset_import(_self, process_id: str):
    db = SessionLocal()
    try:
        process = process_dataset_import(
            db,
            uuid.UUID(str(process_id)),
            worker_id=f"celery:{getattr(getattr(_self, 'request', None), 'id', None) or process_id}",
        )
        return {"status": process.status, "dataset_import_id": str(process.id)}
    finally:
        db.close()


@celery_app.task(bind=True, name="ml_platform.execute_dataset_import_confirmation")
def execute_dataset_import_confirmation_task(_self, process_id: str):
    db = SessionLocal()
    try:
        process = execute_dataset_import_confirmation(
            db,
            uuid.UUID(str(process_id)),
            worker_id=f"celery-confirm:{getattr(getattr(_self, 'request', None), 'id', None) or process_id}",
        )
        return {"status": process.status, "dataset_import_id": str(process.id)}
    finally:
        db.close()
