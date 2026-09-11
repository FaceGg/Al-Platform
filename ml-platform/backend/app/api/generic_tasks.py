"""Industry-neutral annotation and AutoML task entrypoints."""

from __future__ import annotations

GENERICIZATION_BRIDGE_ONLY = True

import uuid
from typing import Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status
from pydantic import BaseModel, ConfigDict, Field, field_validator
import json
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.auth import get_current_user
from app.database import get_db
from app.models.platform_models import AnnotationTaskRevisionSnapshot, GenericAnnotationTask
from app.models.access import AuditEvent
from app.models.data_version import DatasetSample, DatasetVersion
from app.models.artifact import Artifact
from app.models.labeling import LabelSchema
from app.models.project import Project
from app.models.user import User
from app.services.annotation_tasks import migrate_legacy_quality_run
from app.services.annotation_task_state import current_annotation_task_preview, current_annotation_task_snapshot, list_annotation_tasks, serialize_annotation_task
from app.services.annotation_strategies import (
    StrategyConfigError,
    _config_from_snapshot,
    label_schema_contract_from_snapshot,
    validate_strategy_config,
)
from app.services.label_schema import bind_label_schema_to_task, label_schema_snapshot

router = APIRouter(tags=["generic-tasks"])


class GenericTaskCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    project_id: uuid.UUID
    dataset_version_id: uuid.UUID
    label_schema_id: uuid.UUID
    mode: Literal["manual", "automatic"] = "manual"
    sample_scope: dict = Field(default_factory=lambda: {"kind": "all"})
    label_snapshot: dict = Field(default_factory=dict)
    visible_columns: list[str] = Field(default_factory=list)
    instructions: str = ""
    configuration: dict = Field(default_factory=dict)

    @field_validator("sample_scope")
    @classmethod
    def validate_sample_scope(cls, value: dict) -> dict:
        if set(value) - {"kind", "sample_ids", "filters"} or value.get("kind") not in {"all", "ids", "filter"}:
            raise ValueError("sample_scope must declare kind all, ids, or filter")
        if value.get("kind") == "ids" and not isinstance(value.get("sample_ids"), list):
            raise ValueError("sample_scope.ids must be a list")
        if len(json.dumps(value, ensure_ascii=True, separators=(",", ":"))) > 16384:
            raise ValueError("sample_scope exceeds 16 KiB")
        return value

    @field_validator("label_snapshot")
    @classmethod
    def validate_label_snapshot(cls, value: dict) -> dict:
        if len(json.dumps(value, ensure_ascii=True, separators=(",", ":"))) > 65536:
            raise ValueError("label_snapshot exceeds 64 KiB")
        return value


class GenericTaskConfigurationUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    task_revision: int = Field(ge=0)
    visible_columns: list[str] = Field(default_factory=list)
    instructions: str = ""
    configuration: dict = Field(default_factory=dict)


def _uuid(value, field: str) -> uuid.UUID:
    try:
        return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))
    except (TypeError, ValueError, AttributeError) as error:
        raise HTTPException(status_code=422, detail={"code": "INVALID_UUID", "field": field}) from error


def _serialize(db: Session, task: GenericAnnotationTask) -> dict:
    payload = serialize_annotation_task(task, current_annotation_task_preview(db, task), current_annotation_task_snapshot(db, task))
    payload["created_at"] = task.created_at.isoformat() if task.created_at else None
    return payload


def _require_project(db: Session, project_id: uuid.UUID, user: User) -> Project:
    project = db.query(Project).filter(Project.id == project_id).first()
    if project is None or project.owner_id != user.id:
        raise HTTPException(status_code=404, detail={"code": "PROJECT_NOT_FOUND"})
    return project


def _contract_error(request: Request, code: str, message: str, status_code: int = 400, details: dict | None = None):
    request_id = str(getattr(request.state, "request_id", "")) or None
    return HTTPException(
        status_code=status_code,
        detail={"request_id": request_id, "code": code, "message": message, "details": details or {}},
    )


@router.get("/api/annotation-tasks")
def list_generic_annotation_tasks(
    project_id: uuid.UUID | None = Query(default=None), cursor: str | None = Query(default=None), limit: int = Query(default=50, ge=1, le=200), db: Session = Depends(get_db), current_user: User = Depends(get_current_user)
):
    try:
        return list_annotation_tasks(db, project_id, current_user.id, cursor, limit)
    except ValueError as error:
        raise HTTPException(status_code=422, detail={"code": str(error)}) from error


def _request_context(request: Request, x_request_id: str | None, idempotency_key: str | None):
    request_id = getattr(request.state, "request_id", None)
    if not x_request_id or request_id is None or str(request_id) != x_request_id:
        raise _contract_error(request, "REQUEST_ID_REQUIRED", "X-Request-ID is required")
    if not idempotency_key or len(idempotency_key) > 128:
        raise _contract_error(request, "IDEMPOTENCY_KEY_REQUIRED", "Idempotency-Key is required")
    return idempotency_key


def _snapshot_with_configuration(task: GenericAnnotationTask, data: GenericTaskConfigurationUpdate) -> dict:
    previous = task.task_snapshot or {}
    snapshot = {
        "dataset_version": dict(previous.get("dataset_version") or {}),
        "sample_ids": list(previous.get("sample_ids") or []),
        "visible_columns": list(data.visible_columns),
        "label_schema": dict(previous.get("label_schema") or task.label_snapshot or {}),
        "instructions": data.instructions,
        "configuration": dict(data.configuration),
    }
    import hashlib
    canonical = json.dumps(snapshot, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    snapshot["config_hash"] = "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return snapshot


@router.post("/api/annotation-tasks", status_code=status.HTTP_201_CREATED)
def create_generic_annotation_task(
    data: GenericTaskCreate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    x_request_id: str | None = Header(default=None, alias="X-Request-ID"),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    key = _request_context(request, x_request_id, idempotency_key)
    project_id = data.project_id
    _require_project(db, project_id, current_user)
    schema = db.get(LabelSchema, data.label_schema_id)
    if schema is None or schema.project_id != project_id:
        raise _contract_error(
            request,
            "LABEL_SCHEMA_NOT_FOUND",
            "The label schema does not belong to this project.",
            status_code=404,
        )
    version = db.query(DatasetVersion).filter(DatasetVersion.id == data.dataset_version_id, DatasetVersion.project_id == project_id).one_or_none()
    if version is None:
        raise _contract_error(request, "DATASET_VERSION_NOT_FOUND", "The dataset version does not belong to this project.", status_code=404)
    if data.mode == "automatic" and data.configuration.get("model_artifact_id") is not None:
        try:
            model_artifact_id = uuid.UUID(str(data.configuration["model_artifact_id"]))
        except (TypeError, ValueError, AttributeError) as error:
            raise _contract_error(request, "MODEL_ARTIFACT_INVALID", "The model artifact id is invalid.", status_code=422) from error
        model_artifact = db.query(Artifact).filter(
            Artifact.id == model_artifact_id,
            Artifact.project_id == project_id,
            Artifact.type == "model",
        ).one_or_none()
        if model_artifact is None:
            raise _contract_error(request, "MODEL_ARTIFACT_NOT_FOUND", "The model artifact does not belong to this project.", status_code=422)
    requested_ids = list(data.sample_scope.get("sample_ids", [])) if data.sample_scope.get("kind") == "ids" else None
    samples_query = db.query(DatasetSample).filter(DatasetSample.dataset_version_id == version.id)
    if requested_ids is not None:
        samples_query = samples_query.filter(DatasetSample.sample_id.in_(requested_ids))
    samples = samples_query.order_by(DatasetSample.row_index.asc()).all()
    if requested_ids is not None and {sample.sample_id for sample in samples} != set(requested_ids):
        raise _contract_error(request, "SAMPLE_SCOPE_INVALID", "The sample scope contains unknown sample ids.", status_code=422)
    schema_snapshot = label_schema_snapshot(schema)
    if data.mode == "automatic":
        try:
            validate_strategy_config(
                _config_from_snapshot(data.configuration),
                label_schema_contract_from_snapshot(schema_snapshot),
            )
        except StrategyConfigError as error:
            raise _contract_error(
                request,
                error.code,
                str(error),
                status_code=422,
            ) from error
    visible_columns = list(data.visible_columns)
    task_snapshot = {
        "dataset_version": {"id": str(version.id), "version": version.version, "content_hash": version.content_hash, "schema_hash": version.schema_hash},
        "sample_ids": [sample.sample_id for sample in samples],
        "visible_columns": visible_columns,
        "label_schema": schema_snapshot,
        "instructions": data.instructions,
        "configuration": data.configuration,
    }
    import hashlib
    canonical = json.dumps(task_snapshot, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    task_snapshot["config_hash"] = "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    existing = db.query(GenericAnnotationTask).filter(
        GenericAnnotationTask.idempotency_key == key,
        GenericAnnotationTask.owner_id == current_user.id,
    ).first()
    if existing is not None:
        return _serialize(db, existing)
    task = GenericAnnotationTask(
        project_id=project_id,
        dataset_version_id=data.dataset_version_id,
        label_schema_id=data.label_schema_id,
        owner_id=current_user.id,
        mode=data.mode,
        status="draft",
        sample_scope=data.sample_scope,
        label_snapshot=schema_snapshot,
        task_snapshot=task_snapshot,
        idempotency_key=key,
    )
    db.add(task)
    try:
        db.flush()
        bind_label_schema_to_task(db, task_id=task.id, schema=schema)
        db.commit()
    except IntegrityError:
        db.rollback()
        existing = db.query(GenericAnnotationTask).filter(
            GenericAnnotationTask.idempotency_key == key,
            GenericAnnotationTask.owner_id == current_user.id,
        ).first()
        if existing is None:
            raise
        return _serialize(db, existing)
    db.refresh(task)
    return _serialize(db, task)


@router.put("/api/annotation-tasks/{task_id}/configuration")
def update_generic_annotation_task_configuration(
    task_id: uuid.UUID,
    data: GenericTaskConfigurationUpdate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    task = db.query(GenericAnnotationTask).filter(
        GenericAnnotationTask.id == task_id,
        GenericAnnotationTask.owner_id == current_user.id,
    ).one_or_none()
    if task is None:
        raise _contract_error(request, "TASK_NOT_FOUND", "The task was not found.", status_code=404)
    if task.task_revision != data.task_revision:
        raise _contract_error(request, "TASK_REVISION_CONFLICT", "The task revision has changed.", status_code=409)
    if task.status not in {"draft", "failed", "needs_review"}:
        raise _contract_error(request, "TASK_STATE_INVALID", "The task configuration cannot be changed in its current state.", status_code=409)
    snapshot = _snapshot_with_configuration(task, data)
    task.task_revision += 1
    db.add(AnnotationTaskRevisionSnapshot(task_id=task.id, task_revision=task.task_revision, snapshot=snapshot))
    db.add(AuditEvent(
        project_id=task.project_id,
        actor_id=current_user.id,
        actor_username=current_user.username,
        action="annotation_task.configuration_updated",
        resource_type="annotation_task",
        resource_id=str(task.id),
        result="success",
        request_id=uuid.uuid4(),
        changes={"from_revision": data.task_revision, "to_revision": task.task_revision, "config_hash": snapshot["config_hash"]},
    ))
    db.commit()
    db.refresh(task)
    payload = _serialize(db, task)
    payload["task_snapshot"] = snapshot
    return payload


@router.post("/api/automl-tasks", status_code=status.HTTP_201_CREATED)
def create_automl_task(
    data: GenericTaskCreate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    x_request_id: str | None = Header(default=None, alias="X-Request-ID"),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    payload = data.model_copy(update={"mode": "automatic"})
    return create_generic_annotation_task(payload, request, db, current_user, x_request_id, idempotency_key)


@router.post("/api/projects/{project_id}/spot-weld/runs", status_code=status.HTTP_410_GONE)
def reject_legacy_spot_weld_write(
    project_id: uuid.UUID,
    request: Request,
    data: dict | None = None,
    current_user: User = Depends(get_current_user),
    x_request_id: str | None = Header(default=None, alias="X-Request-ID"),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    """Close the industry-specific write path during generic migration."""
    _request_context(request, x_request_id, idempotency_key)
    request_id = str(getattr(request.state, "request_id", "")) or None
    raise HTTPException(
        status_code=status.HTTP_410_GONE,
        detail={
            "request_id": request_id,
            "code": "GENERIC_API_REQUIRED",
            "message": "Use /api/annotation-tasks or /api/automl-tasks.",
            "details": {},
            "legacy_route": f"/api/projects/{project_id}/spot-weld/runs",
        },
    )


@router.post("/api/annotation-tasks/{legacy_run_id}/migrate", status_code=status.HTTP_201_CREATED)
def migrate_legacy_task(
    legacy_run_id: uuid.UUID,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    x_request_id: str | None = Header(default=None, alias="X-Request-ID"),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    _request_context(request, x_request_id, idempotency_key)
    from app.models.spot_weld_quality import SpotWeldQualityRun
    run = db.query(SpotWeldQualityRun).filter(SpotWeldQualityRun.id == legacy_run_id).first()
    if run is None:
        raise HTTPException(status_code=404, detail={"code": "LEGACY_QUALITY_RUN_NOT_FOUND", "message": "Legacy run not found"})
    if run.created_by_id != current_user.id or run.project_id is None:
        raise HTTPException(status_code=404, detail={"code": "LEGACY_QUALITY_RUN_NOT_FOUND", "message": "Legacy run not found"})
    _require_project(db, run.project_id, current_user)
    task = migrate_legacy_quality_run(db, legacy_run_id)
    return _serialize(db, task)
