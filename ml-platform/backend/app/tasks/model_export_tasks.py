"""Asynchronous model export execution."""

import hashlib
import uuid

from app.config import settings
from app.database import SessionLocal
from app.models.artifact import Artifact
from app.models.model_export import ModelExport
from app.models.model_registry import ModelVersion
from app.models.operation import DurableOperation
from app.services.model_export import ExportError, build_export_package
from app.services.operation_lifecycle import claim_operation, complete_operation, fail_operation, heartbeat_operation
from app.tasks.celery_app import celery_app


def enqueue_model_export(export_id):
    if settings.task_backend == "celery":
        return execute_model_export.delay(str(export_id))
    return execute_model_export(str(export_id))


@celery_app.task(bind=True, name="ml_platform.execute_model_export")
def execute_model_export(_self, export_id: str):
    worker_id = f"model-export:{getattr(getattr(_self, 'request', None), 'id', None) or export_id}"
    session_factory = SessionLocal
    db = session_factory()
    close_db = hasattr(session_factory, "kw")
    try:
        item = db.query(ModelExport).filter(ModelExport.id == uuid.UUID(str(export_id))).first()
        if item is None:
            return {"status": "not_found", "export_id": str(export_id)}
        if item.status == "completed" and item.package_path:
            return {"status": "completed", "export_id": str(item.id)}
        if item.operation_id is None:
            item.status = "failed"
            item.error = {"code": "MODEL_EXPORT_OPERATION_MISSING"}
            db.commit()
            return {"status": "failed", "export_id": str(item.id), "error": item.error}
        if not claim_operation(db, item.operation_id, worker_id, 300):
            return {"status": "not_claimed", "export_id": str(item.id)}
        item.status = "running"
        db.commit()
        try:
            version = db.query(ModelVersion).filter(ModelVersion.id == item.model_version_id).first()
            if version is None:
                raise ExportError("MODEL_VERSION_NOT_FOUND")
            artifact = db.query(Artifact).filter(Artifact.id == version.source_artifact_id).first()
            if artifact is not None:
                version.source_artifact_path = artifact.storage_path
            result = build_export_package(
                version,
                output_dir=settings.artifact_storage_dir,
                include_runtime=item.include_runtime,
                annotation_task_revision=item.annotation_task_revision,
            )
            heartbeat_operation(db, item.operation_id, worker_id, 300)
            export_artifact = Artifact(
                project_id=version.registered_model.project_id,
                name=result.path.name,
                type="model_export",
                storage_path=str(result.path),
                file_size=result.path.stat().st_size,
                format="zip",
                metadata_={"model_export_id": str(item.id), "manifest_sha256": hashlib.sha256(result.path.read_bytes()).hexdigest()},
            )
            db.add(export_artifact)
            db.flush()
            item.package_path = str(result.path)
            item.manifest_sha256 = export_artifact.metadata_["manifest_sha256"]
            item.status = "completed"
            complete_operation(db, item.operation_id, worker_id, export_artifact.id, f"sha256:{item.manifest_sha256}")
            return {"status": "completed", "export_id": str(item.id), "path": str(result.path)}
        except Exception as error:
            db.rollback()
            item = db.query(ModelExport).filter(ModelExport.id == uuid.UUID(str(export_id))).first()
            item.status = "failed"
            item.error = {"code": getattr(error, "code", "MODEL_EXPORT_FAILED"), "message": str(error)[:300]}
            db.commit()
            if item.operation_id is not None:
                fail_operation(db, item.operation_id, item.error["code"], item.error)
            return {"status": "failed", "export_id": str(item.id), "error": item.error}
    finally:
        if close_db:
            db.close()
