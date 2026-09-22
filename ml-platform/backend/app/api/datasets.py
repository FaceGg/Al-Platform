import os
import io
import logging
import mimetypes
from typing import List, Optional
from uuid import UUID
import uuid
import json
from pathlib import Path
from pathlib import PurePosixPath
from urllib.parse import quote
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Header, HTTPException, UploadFile, File, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session, joinedload

from app.database import get_db
from app.models.project import Project
from app.models.artifact import Artifact
from app.models.user import User
from app.api.auth import get_current_user
from app.services.artifact_service import ArtifactAccessError, build_artifact_service
from app.storage.base import StorageError
from app.api.project_security import audit_service, require_project_access, resolve_project_access, project_uuid
from app.services.audit import AuditIntent
from app.schemas.dataset_import import ConfirmSchemaRequest, ParseOptions
from app.services.data_import import (
    DataImportError,
    create_dataset_import_process,
    freeze_dataset_version,
    process_dataset_import,
    read_dataset_upload,
    _sniff_source_format,
)
from app.models.data_version import DatasetImportProcess, DatasetVersion
from app.models.operation import DurableOperation
from app.models.platform_models import AnnotationTask, GenericAnnotationTask

router = APIRouter(prefix="/api", tags=["datasets"])
logger = logging.getLogger(__name__)
PROJECT_WRITE_ACTIONS = {
    "POST /api/projects/{project_id}/datasets/upload": "dataset.upload",
    "POST /api/projects/{project_id}/datasets/batch": "dataset.batch_upload",
    "POST /api/projects/{project_id}/datasets/batch-upload": "dataset.batch_upload",
    "POST /api/projects/{project_id}/datasets/import-zip": "dataset.import_zip",
}

UPLOAD_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)
MAX_IMPORT_UPLOAD_BYTES = 1_000_000_000


async def _stage_upload(file: UploadFile, destination: Path, *, max_bytes: int = MAX_IMPORT_UPLOAD_BYTES) -> int:
    total = 0
    try:
        with destination.open("xb") as target:
            while True:
                chunk = await file.read(min(1024 * 1024, max_bytes - total + 1))
                if not chunk:
                    break
                total += len(chunk)
                if total > max_bytes:
                    raise DataImportError("DATA_LIMIT_FILE_BYTES")
                target.write(chunk)
    except Exception:
        destination.unlink(missing_ok=True)
        raise
    return total


def _stage_upload_sync(file: UploadFile, destination: Path, *, max_bytes: int = MAX_IMPORT_UPLOAD_BYTES) -> int:
    total = 0
    try:
        with destination.open("xb") as target:
            while True:
                chunk = file.file.read(min(1024 * 1024, max_bytes - total + 1))
                if not chunk:
                    break
                total += len(chunk)
                if total > max_bytes:
                    raise DataImportError("DATA_LIMIT_FILE_BYTES")
                target.write(chunk)
    except Exception:
        destination.unlink(missing_ok=True)
        raise
    return total


def _freeze_staged_upload(db: Session, project_id, operator: User, staging_path: Path, source_name: str):
    table = read_dataset_upload(staging_path, None, ParseOptions())
    table.project_id = project_id
    table.source_name = source_name
    return freeze_dataset_version(db, table, operator.id)


def _unique_dataset_name(db: Session, project_id, name: str) -> str:
    """Dataset files must stay uniquely named within a project; append -2, -3, ...
    before the extension when the requested name is already taken."""
    existing = {
        row[0]
        for row in db.query(Artifact.name).filter(
            Artifact.project_id == project_id,
            Artifact.type == "dataset",
            Artifact.archived_at.is_(None),
        ).all()
    }
    if name not in existing:
        return name
    stem = Path(name).stem or name
    suffix = Path(name).suffix
    counter = 2
    while f"{stem}-{counter}{suffix}" in existing:
        counter += 1
    return f"{stem}-{counter}{suffix}"


def _dataset_import_payload(process: DatasetImportProcess) -> dict:
    return {
        "id": str(process.id),
        "dataset_import_id": str(process.id),
        "operation_id": str(process.operation_id),
        "dataset_version_id": str(process.dataset_version_id) if process.dataset_version_id else None,
        "status": process.status,
        "inferred_schema": process.inferred_schema or [],
        "content_hash": process.content_hash,
        "schema_hash": process.schema_hash,
        "error": process.error,
    }


@router.post("/projects/{project_id}/dataset-imports", status_code=202)
async def import_dataset_version(
    project_id: str, request: Request, file: UploadFile = File(...),
    source_format: str | None = Query(default=None),
    parse_options: str | None = Query(default=None),
    db: Session = Depends(get_db), current_user: User = Depends(get_current_user),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    project_id_value = project_uuid(project_id)
    access = require_project_access(db, project_id_value, current_user.id, "resource.create")
    options = ParseOptions()
    if parse_options:
        try:
            options = ParseOptions.model_validate(json.loads(parse_options))
        except Exception as error:
            raise HTTPException(400, "Invalid parse_options") from error
    safe_name = _unique_dataset_name(db, project_id_value, Path(file.filename or "uploaded_file").name)
    detected_format = source_format
    staging_path = Path(UPLOAD_DIR) / f"{uuid.uuid4()}_{safe_name}"
    try:
        with audit_service(db).project_action(
            db, request=request, actor=current_user, access=access,
            permission="resource.create",
            intent=AuditIntent(project_id=project_id_value, action="dataset.import", resource_type="dataset_version", changes={"filename": safe_name}),
            allowed_changes={"filename"},
        ):
            await _stage_upload(file, staging_path, max_bytes=options.max_file_bytes)
            if source_format is not None:
                declared_format = source_format.lower().lstrip(".")
                declared_format = "excel" if declared_format in {"xlsx", "xls"} else declared_format
                detected_format = _sniff_source_format(staging_path)
                if declared_format != detected_format:
                    raise HTTPException(
                        400,
                        {
                            "code": "DATA_FORMAT_MISMATCH",
                            "message": (
                                f"declared format {declared_format!r} does not match "
                                f"detected format {detected_format!r}"
                            ),
                        },
                    )
            process = create_dataset_import_process(
                db,
                project_id=project_id_value,
                operator_id=current_user.id,
                source_path=staging_path,
                source_name=safe_name,
                source_format=detected_format,
                options=options,
                idempotency_key=(str(idempotency_key) if idempotency_key else f"legacy-{uuid.uuid4()}"),
            )
            from app.tasks.dataset_import_tasks import enqueue_dataset_import

            enqueue_dataset_import(process.id)
            return _dataset_import_payload(process)
    finally:
        staging_path.unlink(missing_ok=True)


@router.get("/dataset-imports/{import_id}")
def get_dataset_import(
    import_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    process = db.get(DatasetImportProcess, import_id)
    if process is None:
        raise HTTPException(404, {"code": "DATA_IMPORT_NOT_FOUND", "message": "Dataset import not found"})
    require_project_access(db, process.project_id, current_user.id, "project.read")
    return _dataset_import_payload(process)


@router.post("/dataset-imports/{import_id}/confirm-schema", status_code=202)
def confirm_dataset_import_schema(
    import_id: UUID,
    data: ConfirmSchemaRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    if not idempotency_key:
        raise HTTPException(400, {"code": "IDEMPOTENCY_KEY_REQUIRED", "message": "Idempotency-Key is required"})
    process = db.get(DatasetImportProcess, import_id)
    if process is None:
        raise HTTPException(404, {"code": "DATA_IMPORT_NOT_FOUND", "message": "Dataset import not found"})
    access = require_project_access(db, process.project_id, current_user.id, "resource.create")
    if process.status != "pending_schema":
        raise HTTPException(409, {"code": "DATA_IMPORT_NOT_PENDING", "message": "Dataset import is not awaiting schema confirmation"})
    operation = DurableOperation(
        resource_key=f"dataset-import-confirm:{process.id}",
        idempotency_key=str(idempotency_key),
        state="queued",
        stage="queued",
    )
    db.add(operation)
    db.flush()
    process.confirmation_operation_id = operation.id
    process.status = "confirming"
    process.parse_contract = {
        **(process.parse_contract or {}),
        "confirmation": {
            "schema": data.schema_definition,
            "sample_id_column": data.sample_id_column,
        },
    }
    db.commit()
    from app.tasks.dataset_import_tasks import enqueue_dataset_import_confirmation

    enqueue_dataset_import_confirmation(process.id)
    return {
        "id": str(process.id),
        "dataset_import_id": str(process.id),
        "operation_id": str(operation.id),
        "status": process.status,
    }


@router.get("/dataset-versions/{version_id}")
def get_dataset_version(
    version_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user),
):
    try:
        version_uuid = UUID(version_id)
    except (TypeError, ValueError, AttributeError) as error:
        raise HTTPException(404, "Dataset version not found") from error
    version = db.query(DatasetVersion).filter(DatasetVersion.id == version_uuid).first()
    if version is None or version.archived_at is not None:
        raise HTTPException(404, "Dataset version not found")
    require_project_access(db, version.project_id, current_user.id, "project.read")
    return {"id": str(version.id), "project_id": str(version.project_id), "version": version.version, "status": version.status, "row_count": version.row_count, "column_count": version.column_count, "content_hash": version.content_hash, "schema_hash": version.schema_hash, "parse_contract": version.parse_contract, "columns": [{"name": item.name, "dtype": item.dtype, "nullable": item.nullable, "position": item.position} for item in version.schema_columns]}


@router.get("/projects/{project_id}/dataset-versions")
def list_project_dataset_versions(
    project_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    project = require_project_access(db, project_id, current_user.id, "project.read").project
    # Backfill workflow-export artifacts created before workflow outputs were
    # registered as immutable dataset versions.
    workflow_artifacts = (
        db.query(Artifact)
        .filter(
            Artifact.project_id == project.id,
            Artifact.type == "dataset",
            Artifact.archived_at.is_(None),
        )
        .all()
    )
    existing_artifact_ids = {
        item[0] for item in db.query(DatasetVersion.original_artifact_id)
        .filter(DatasetVersion.project_id == project.id)
        .all()
        if item[0] is not None
    }
    backfill_service = build_artifact_service(db)
    for artifact in workflow_artifacts:
        if (
            artifact.id not in existing_artifact_ids
            and (artifact.metadata_ or {}).get("source") == "workflow_export"
        ):
            try:
                backfill_service.create_dataset_version_from_artifact(
                    artifact,
                    operator_id=project.owner_id,
                )
            except StorageError:
                logger.warning(
                    "Skipping workflow dataset version backfill for unavailable artifact",
                    extra={"artifact_id": str(artifact.id), "project_id": str(project.id)},
                )
    db.commit()
    # Keep the wizard's choices identical to 数据管理: only an active,
    # non-normalized dataset artifact may back an annotation version.
    active_source_ids = {
        item[0]
        for item in db.query(Artifact.id)
        .filter(
            Artifact.project_id == project.id,
            Artifact.type == "dataset",
            Artifact.archived_at.is_(None),
        )
        .all()
        if item[0] is not None
    }
    active_source_ids = {
        artifact_id
        for artifact_id in active_source_ids
        if (db.get(Artifact, artifact_id).metadata_ or {}).get("source") != "normalized"
    }
    versions_query = (
        db.query(DatasetVersion)
        .filter(
            DatasetVersion.project_id == project.id,
            DatasetVersion.archived_at.is_(None),
            DatasetVersion.original_artifact_id.in_(active_source_ids) if active_source_ids else False,
        )
    )
    versions = versions_query.order_by(DatasetVersion.version.desc(), DatasetVersion.created_at.desc()).all()
    return {
        "items": [
            {
                "id": str(version.id),
                "project_id": str(version.project_id),
                "source_name": (
                    db.query(Artifact.name)
                    .filter(Artifact.id == version.original_artifact_id)
                    .scalar()
                    if version.original_artifact_id else None
                ),
                "version": version.version,
                "status": version.status,
                "row_count": version.row_count,
                "column_count": version.column_count,
                "columns": [
                    {
                        "name": column.name,
                        "dtype": column.dtype,
                        "nullable": column.nullable,
                        "position": column.position,
                    }
                    for column in sorted(version.schema_columns, key=lambda item: item.position)
                ],
            }
            for version in versions
        ],
        "total": len(versions),
    }


def _store_uploaded_dataset(
    db: Session, project_id, file: UploadFile, *, commit: bool = True,
) -> Artifact:
    safe_name = _unique_dataset_name(db, project_id, Path(file.filename or "uploaded_file").name)
    staging_path = Path(UPLOAD_DIR) / f"{uuid.uuid4()}_{safe_name}"
    staging_path.write_bytes(file.file.read())
    try:
        return _create_dataset_artifact(
            build_artifact_service(db), project_id, staging_path, safe_name, commit=commit,
        )
    finally:
        staging_path.unlink(missing_ok=True)


def _create_dataset_artifact(
    service, project_id, source: Path, name: str, *, commit: bool = True,
) -> Artifact:
    if source.suffix.lower() in {".csv", ".xls", ".xlsx"}:
        return service.create_dataset(project_id, source, name, commit=commit)
    return service.create_from_file(
        project_id,
        source,
        name,
        "dataset",
        metadata={"source": "upload"},
        commit=commit,
    )


def _cleanup_storage(db: Session, storage_uris: list[str], original_error: Exception | None = None) -> None:
    storage = build_artifact_service(db).storage
    failures = []
    for uri in storage_uris:
        try:
            storage.delete(uri)
        except Exception as error:
            failures.append(f"{uri}: {error}")
    if failures:
        raise DataImportError("DATA_CLEANUP_FAILED", "; ".join(failures)) from original_error


def _read_dataset(path: Path):
    import pandas as pd

    if path.suffix.lower() in {".xls", ".xlsx"}:
        return pd.read_excel(path)
    last_error = None
    for encoding in ("utf-8-sig", "utf-8", "gb18030", "gbk"):
        try:
            return pd.read_csv(path, encoding=encoding)
        except UnicodeDecodeError as error:
            last_error = error
    raise last_error


def _json_value(value):
    import math
    import numpy as np
    import pandas as pd
    from datetime import date, datetime

    if value is None or value is pd.NaT:
        return None
    if isinstance(value, (pd.Timestamp, datetime, date)):
        return value.isoformat()
    if isinstance(value, np.generic):
        return _json_value(value.item())
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    return value


def _json_records(frame):
    return [_json_value(record) for record in frame.to_dict(orient="records")]


def _serialize_dataset(
    artifact: Artifact,
    *,
    project_name: str | None = None,
    dataset_version: DatasetVersion | None = None,
) -> dict:
    metadata = artifact.metadata_ or {}
    parse_contract = (dataset_version.parse_contract or {}) if dataset_version else {}
    row_count = dataset_version.row_count if dataset_version else metadata.get("row_count", 0)
    column_count = dataset_version.column_count if dataset_version else metadata.get("column_count")
    if column_count is None:
        column_count = len(metadata.get("schema") or [])
    created_at = dataset_version.created_at if dataset_version else artifact.created_at
    if created_at is not None:
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc)
        created_at = created_at.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    return {
        "id": str(artifact.id),
        "artifact_id": str(artifact.id),
        "project_id": str(artifact.project_id),
        "project_name": project_name if project_name is not None else (
            artifact.project.name if artifact.project else None
        ),
        "name": artifact.name,
        "filename": artifact.name,
        "type": artifact.type,
        "format": artifact.format,
        "file_size": artifact.file_size,
        "size_bytes": artifact.file_size,
        "row_count": row_count,
        "column_count": column_count,
        "schema": metadata.get("schema", []),
        "created_at": created_at,
    }


@router.get("/datasets")
def list_owned_datasets(
    project_id: Optional[str] = Query(default=None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    query = (
        db.query(Artifact)
        .options(joinedload(Artifact.project))
        .join(Project, Artifact.project_id == Project.id)
        .filter(
            Artifact.type == "dataset",
            Artifact.archived_at.is_(None),
            Project.owner_id == current_user.id,
        )
    )
    if project_id:
        query = query.filter(Artifact.project_id == UUID(project_id))
    artifacts = query.order_by(Artifact.created_at.desc()).all()
    artifacts = [artifact for artifact in artifacts if (artifact.metadata_ or {}).get("source") != "normalized"]
    versions = {
        version.original_artifact_id: version
        for version in db.query(DatasetVersion)
        .filter(DatasetVersion.original_artifact_id.in_([artifact.id for artifact in artifacts]))
        .order_by(DatasetVersion.created_at.desc())
        .all()
    }
    return {"items": [_serialize_dataset(artifact, dataset_version=versions.get(artifact.id)) for artifact in artifacts], "total": len(artifacts)}


@router.get("/projects/{project_id}/datasets")
def list_project_datasets(
    project_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    project = require_project_access(
        db, project_id, current_user.id, "project.read",
    ).project

    artifacts = db.query(Artifact).filter(
        Artifact.project_id == project.id,
        Artifact.type == "dataset",
        Artifact.archived_at.is_(None),
    ).order_by(Artifact.created_at.desc()).all()
    artifacts = [artifact for artifact in artifacts if (artifact.metadata_ or {}).get("source") != "normalized"]
    versions = {
        version.original_artifact_id: version
        for version in db.query(DatasetVersion)
        .filter(DatasetVersion.original_artifact_id.in_([artifact.id for artifact in artifacts]))
        .order_by(DatasetVersion.created_at.desc())
        .all()
    }
    items = [_serialize_dataset(artifact, project_name=project.name, dataset_version=versions.get(artifact.id)) for artifact in artifacts]
    return {"items": items, "total": len(items)}


@router.post("/projects/{project_id}/datasets/upload")
def upload_dataset(
    project_id: str,
    request: Request,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    project_id_value = project_uuid(project_id)
    access = resolve_project_access(db, project_id_value, current_user.id)
    storage_uris = []
    try:
        with audit_service(db).project_action(
            db, request=request, actor=current_user, access=access,
            permission="resource.create",
            intent=AuditIntent(
                project_id=project_id_value, action="dataset.upload",
                resource_type="dataset", changes={"filename": Path(file.filename or "").name},
            ),
            allowed_changes={"filename"},
        ):
            safe_name = _unique_dataset_name(db, project_id_value, Path(file.filename or "uploaded_file").name)
            staging_path = Path(UPLOAD_DIR) / f"{uuid.uuid4()}_{safe_name}"
            try:
                _stage_upload_sync(file, staging_path)
                version = _freeze_staged_upload(db, project_id_value, current_user, staging_path, safe_name)
            except DataImportError as error:
                raise HTTPException(400, {"code": error.code, "message": str(error)}) from error
            finally:
                staging_path.unlink(missing_ok=True)
            artifact = db.get(Artifact, version.original_artifact_id)
    except Exception as error:
        _cleanup_storage(db, storage_uris, error)
        raise
    metadata = artifact.metadata_ or {}
    schema = [{"name": column.name, "dtype": column.dtype, "null_count": 0} for column in version.schema_columns]
    return {
        "id": str(artifact.id), "artifact_id": str(artifact.id),
        "name": artifact.name,
        "row_count": version.row_count,
        "schema": schema,
        "sha256": version.content_hash,
    }


@router.post("/projects/{project_id}/datasets/batch")
def batch_import(
    project_id: str,
    files: List[UploadFile] = File(...),
    request: Request = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    project_id_value = project_uuid(project_id)
    access = resolve_project_access(db, project_id_value, current_user.id)

    results = []
    success_count = 0
    failed_count = 0

    storage_uris = []
    try:
        with audit_service(db).project_action(
            db, request=request, actor=current_user, access=access,
            permission="resource.create",
            intent=AuditIntent(
                project_id=project_id_value, action="dataset.batch_upload",
                resource_type="dataset", changes={"file_count": len(files)},
            ),
            allowed_changes={"file_count"},
        ):
            for file in files:
                try:
                    safe_name = _unique_dataset_name(db, project_id_value, Path(file.filename or "uploaded_file").name)
                    staging_path = Path(UPLOAD_DIR) / f"{uuid.uuid4()}_{safe_name}"
                    try:
                        _stage_upload_sync(file, staging_path)
                        version = _freeze_staged_upload(
                            db, project_id_value, current_user, staging_path, safe_name,
                        )
                    finally:
                        staging_path.unlink(missing_ok=True)
                    artifact = db.get(Artifact, version.original_artifact_id)

                    results.append({
                        "id": str(artifact.id), "name": artifact.name,
                        "format": artifact.format, "rows": version.row_count,
                        "schema": [
                            {"name": column.name, "dtype": column.dtype}
                            for column in version.schema_columns
                        ],
                        "sha256": version.content_hash,
                    })
                    success_count += 1
                except Exception as error:
                    failed_count += 1
                    results.append({"name": file.filename, "error": str(error)})
    except Exception as error:
        _cleanup_storage(db, storage_uris, error)
        raise
    return {
        "total": len(files),
        "success": success_count,
        "failed": failed_count,
        "items": results,
    }


@router.get("/projects/{project_id}/datasets/export")
def export_dataset(
    project_id: str,
    format: str = Query(default="csv"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    project = require_project_access(
        db, project_id, current_user.id, "project.read",
    ).project

    artifacts = db.query(Artifact).filter(
        Artifact.project_id == UUID(project_id),
        Artifact.archived_at.is_(None),
    ).all()
    if not artifacts:
        raise HTTPException(404, "No datasets found in project")

    import pandas as pd
    artifact_service = build_artifact_service(db)
    all_dfs = []
    for artifact in artifacts:
        try:
            with artifact_service.materialize(
                artifact.id, artifact.project_id, expected_type="dataset",
            ) as path:
                all_dfs.append(_read_dataset(path))
        except (ArtifactAccessError, OSError, ValueError):
            continue

    if not all_dfs:
        raise HTTPException(404, "No readable datasets found")

    combined = pd.concat(all_dfs, ignore_index=True)

    output = io.BytesIO()
    media_type = ""
    filename = ""
    if format == "json":
        combined.to_json(output, orient="records")
        media_type = "application/json"
        filename = "export.json"
    elif format == "excel":
        combined.to_excel(output, index=False, engine="openpyxl")
        media_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        filename = "export.xlsx"
    elif format == "parquet":
        combined.to_parquet(output, index=False)
        media_type = "application/octet-stream"
        filename = "export.parquet"
    else:
        combined.to_csv(output, index=False)
        media_type = "text/csv"
        filename = "export.csv"

    output.seek(0)
    return StreamingResponse(
        output,
        media_type=media_type,
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@router.get("/datasets/{dataset_id}/export")
def export_single_dataset(
    dataset_id: str,
    format: str = Query(default="csv"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    artifact = db.query(Artifact).filter(
        Artifact.id == UUID(dataset_id),
        Artifact.type == "dataset",
    ).first()
    if not artifact:
        raise HTTPException(404, "Dataset not found")
    require_project_access(db, artifact.project_id, current_user.id, "project.read")

    try:
        with build_artifact_service(db).materialize(
            artifact.id, artifact.project_id, expected_type="dataset",
        ) as path:
            df = _read_dataset(path)
    except ArtifactAccessError as e:
        raise HTTPException(404, str(e)) from e
    except Exception as e:
        raise HTTPException(400, f"Failed to read file: {e}")

    output = io.BytesIO()
    media_type = ""
    filename = f"{artifact.name or 'dataset'}"
    if format == "json":
        df.to_json(output, orient="records")
        media_type = "application/json"
        filename += ".json"
    elif format == "excel":
        df.to_excel(output, index=False, engine="openpyxl")
        media_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        filename += ".xlsx"
    elif format == "parquet":
        df.to_parquet(output, index=False)
        media_type = "application/octet-stream"
        filename += ".parquet"
    else:
        df.to_csv(output, index=False)
        media_type = "text/csv"
        filename += ".csv"

    output.seek(0)
    return StreamingResponse(
        output,
        media_type=media_type,
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@router.get("/datasets/{dataset_id}/download")
def download_dataset_artifact(
    dataset_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    artifact = db.query(Artifact).filter(
        Artifact.id == UUID(dataset_id),
        Artifact.type == "dataset",
    ).first()
    if not artifact:
        raise HTTPException(404, "Dataset not found")
    require_project_access(db, artifact.project_id, current_user.id, "project.read")

    try:
        with build_artifact_service(db).materialize(
            artifact.id, artifact.project_id, expected_type="dataset",
        ) as path:
            payload = path.read_bytes()
    except ArtifactAccessError as error:
        raise HTTPException(404, str(error)) from error

    filename = Path(artifact.name or "dataset.csv").name
    media_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
    return StreamingResponse(
        io.BytesIO(payload),
        media_type=media_type,
        headers={
            "Content-Disposition": f"attachment; filename*=utf-8''{quote(filename)}",
        },
    )


@router.delete("/datasets/{dataset_id}", status_code=204)
def delete_dataset(
    dataset_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    artifact = db.query(Artifact).join(Project).filter(
        Artifact.id == UUID(dataset_id),
        Artifact.type == "dataset",
        Project.owner_id == current_user.id,
    ).first()
    if not artifact:
        raise HTTPException(404, "Dataset not found")
    referenced_versions = db.query(DatasetVersion).filter(
        (DatasetVersion.original_artifact_id == artifact.id)
        | (DatasetVersion.normalized_artifact_id == artifact.id)
    ).all()
    version_ids = [version.id for version in referenced_versions]
    legacy_task = db.query(AnnotationTask).filter(AnnotationTask.dataset_id == artifact.id).first()
    generic_task = (
        db.query(GenericAnnotationTask)
        .filter(GenericAnnotationTask.dataset_version_id.in_(version_ids))
        .first()
        if version_ids else None
    )
    if legacy_task is not None or generic_task is not None:
        task = generic_task or legacy_task
        raise HTTPException(
            status_code=409,
            detail={
                "code": "DATASET_IN_USE",
                "message": "Dataset is in use by an annotation task and cannot be deleted",
                "task_id": str(task.id),
                "task_status": task.status,
            },
        )
    artifact.archived_at = datetime.now(timezone.utc).replace(tzinfo=None)
    db.commit()


@router.post("/datasets/{dataset_id}/restore", status_code=200)
def restore_dataset(
    dataset_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    artifact = db.query(Artifact).join(Project).filter(
        Artifact.id == UUID(dataset_id),
        Artifact.type == "dataset",
        Artifact.archived_at.is_(None),
        Project.owner_id == current_user.id,
    ).first()
    if not artifact:
        raise HTTPException(404, "Dataset not found")
    artifact.archived_at = None
    db.commit()
    return {"id": str(artifact.id), "archived_at": None}



@router.post("/projects/{project_id}/datasets/batch-upload")
async def batch_upload_dataset(
    project_id: str,
    request: Request,
    files: List[UploadFile] = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Batch upload multiple files or a folder to a project."""
    project_id_value = project_uuid(project_id)
    access = resolve_project_access(db, project_id_value, current_user.id)
    artifacts = []
    storage_uris = []
    artifact_service = build_artifact_service(db)
    try:
        with audit_service(db).project_action(
            db, request=request, actor=current_user, access=access,
            permission="resource.create",
            intent=AuditIntent(
                project_id=project_id_value, action="dataset.batch_upload",
                resource_type="dataset", changes={"file_count": len(files)},
            ),
            allowed_changes={"file_count"},
        ):
            for file in files:
                safe_name = _unique_dataset_name(db, project_id_value, Path(file.filename or "uploaded_file").name)
                staging_path = Path(UPLOAD_DIR) / f"{uuid.uuid4()}_{safe_name}"
                ext = staging_path.suffix.lower()
                fmt_map = {".csv": "csv", ".xlsx": "xlsx", ".xls": "xls", ".txt": "txt",
                           ".json": "json", ".png": "png", ".jpg": "jpg"}
                try:
                    await _stage_upload(file, staging_path)
                    if ext in {".csv", ".xlsx", ".xls", ".json", ".xml", ".parquet"}:
                        version = _freeze_staged_upload(db, project_id_value, current_user, staging_path, safe_name)
                        artifact = db.get(Artifact, version.original_artifact_id)
                    else:
                        artifact = _create_dataset_artifact(
                            artifact_service, project_id_value, staging_path, safe_name, commit=False,
                        )
                        storage_uris.append(artifact.storage_uri)
                finally:
                    staging_path.unlink(missing_ok=True)
                artifacts.append({
                    "artifact_id": str(artifact.id), "name": artifact.name,
                    "size": artifact.file_size, "format": fmt_map.get(ext, ""),
                })
    except Exception as error:
        _cleanup_storage(db, storage_uris, error)
        raise
    return {"message": f"Uploaded {len(artifacts)} files", "files": artifacts}


@router.post("/projects/{project_id}/datasets/import-zip")
async def import_zip_dataset(
    project_id: str,
    request: Request,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Import a ZIP-compressed dataset. Extracts and processes all files inside."""
    import zipfile, tempfile
    project_id_value = project_uuid(project_id)
    access = resolve_project_access(db, project_id_value, current_user.id)
    artifacts = []
    storage_uris = []
    artifact_service = build_artifact_service(db)
    try:
        with audit_service(db).project_action(
            db, request=request, actor=current_user, access=access,
            permission="resource.create",
            intent=AuditIntent(
                project_id=project_id_value, action="dataset.import_zip",
                resource_type="dataset", changes={"filename": Path(file.filename or "").name},
            ),
            allowed_changes={"filename"},
        ):
            with tempfile.TemporaryDirectory() as tmpdir:
                safe_zip_name = Path(file.filename or "dataset.zip").name
                zip_path = Path(tmpdir) / safe_zip_name
                await _stage_upload(file, zip_path)
                with zipfile.ZipFile(zip_path, "r") as archive:
                    members = [info for info in archive.infolist() if not info.is_dir()]
                    options = ParseOptions()
                    expanded_total = 0
                    for info in members:
                        member = info.filename
                        normalized_member = member.replace("\\", "/")
                        path = PurePosixPath(normalized_member)
                        if (
                            not normalized_member
                            or normalized_member.startswith("/")
                            or ":" in path.parts[0]
                            or any(part in {"", ".", ".."} for part in path.parts)
                        ):
                            raise HTTPException(400, {"code": "DATA_PARSE_UNSAFE_PATH", "message": "Unsafe ZIP member path"})
                        if info.file_size > options.max_file_bytes:
                            raise HTTPException(400, {"code": "DATA_LIMIT_FILE_BYTES", "message": "ZIP member exceeds file size limit"})
                        expanded_total += info.file_size
                        if expanded_total > options.max_decompressed_bytes:
                            raise HTTPException(400, {"code": "DATA_LIMIT_DECOMPRESSED_BYTES", "message": "ZIP expanded size exceeds limit"})
                    expanded_total = 0
                    for info in members:
                        fname = _unique_dataset_name(db, project_id_value, Path(info.filename.replace("\\", "/")).name)
                        staging_path = Path(tmpdir) / f"{uuid.uuid4()}_{fname}"
                        member_bytes = 0
                        with archive.open(info, "r") as source, staging_path.open("xb") as target:
                            while True:
                                chunk = source.read(1024 * 1024)
                                if not chunk:
                                    break
                                member_bytes += len(chunk)
                                expanded_total += len(chunk)
                                if member_bytes > options.max_file_bytes:
                                    raise DataImportError("DATA_LIMIT_FILE_BYTES")
                                if expanded_total > options.max_decompressed_bytes:
                                    raise DataImportError("DATA_LIMIT_DECOMPRESSED_BYTES")
                                target.write(chunk)
                        ext = Path(fname).suffix.lower()
                        if ext in {".csv", ".xlsx", ".xls", ".json", ".xml", ".parquet"}:
                            version = _freeze_staged_upload(db, project_id_value, current_user, staging_path, fname)
                            artifact = db.get(Artifact, version.original_artifact_id)
                        else:
                            artifact = _create_dataset_artifact(
                                artifact_service, project_id_value, staging_path, fname, commit=False,
                            )
                            storage_uris.append(artifact.storage_uri)
                        artifacts.append({
                            "artifact_id": str(artifact.id), "name": artifact.name,
                            "size": artifact.file_size,
                        })
    except DataImportError as error:
        _cleanup_storage(db, storage_uris, error)
        raise HTTPException(400, {"code": error.code, "message": str(error)}) from error
    except HTTPException as error:
        _cleanup_storage(db, storage_uris, error)
        raise
    except Exception as error:
        _cleanup_storage(db, storage_uris, error)
        raise
    return {"message": f"Imported {len(artifacts)} files from ZIP", "files": artifacts}
@router.get("/datasets/{dataset_id}/preview")
def preview_dataset(
    dataset_id: str,
    limit: int = Query(10, ge=0, description="Preview row count; 0 returns all rows"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    artifact = db.query(Artifact).filter(
        Artifact.id == UUID(dataset_id),
        Artifact.type == "dataset",
    ).first()
    if not artifact:
        raise HTTPException(404, "Dataset not found")
    require_project_access(db, artifact.project_id, current_user.id, "project.read")

    try:
        with build_artifact_service(db).materialize(
            artifact.id, artifact.project_id, expected_type="dataset",
        ) as path:
            df = _read_dataset(path)
        frame = df if limit == 0 else df.head(limit)
        return {
            "columns": list(df.columns),
            "preview": _json_records(frame),
            "total_rows": len(df),
            "dtypes": {str(k): str(v) for k, v in df.dtypes.items()},
        }
    except ArtifactAccessError as e:
        raise HTTPException(404, str(e)) from e
    except Exception as e:
        raise HTTPException(400, f"Failed to read file: {e}")

