"""Closed-loop demo API: config, per-row predict, status, reset."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Body, Depends, HTTPException
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from app.api.auth import get_current_user
from app.api.project_security import require_project_access
from app.database import get_db
from app.models.artifact import Artifact
from app.models.demo_loop import DemoLoopConfig
from app.models.model_registry import InferenceDeployment, ModelVersion, RegisteredModel
from app.models.user import User
from app.services.demo_loop import DemoLoopError, DemoLoopService

router = APIRouter(tags=["demo_loop"])


class DemoLoopConfigUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = None
    deployment_id: str | None = None
    error_classes: list[str] | None = None
    preprocess_enabled: bool | None = None
    alert_threshold_rows: int | None = None
    require_review: bool | None = None
    review_annotator_ids: list[str] | None = None
    retrain_enabled: bool | None = None
    retrain_threshold_rows: int | None = None
    retrain_dataset_artifact_id: str | None = None
    retrain_target_column: str | None = None
    retrain_max_trials: int | None = None


class DemoLoopPredictRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    record: dict


def _service(db: Session) -> DemoLoopService:
    return DemoLoopService(db)


def _require_config(db: Session, project_id, service: DemoLoopService) -> DemoLoopConfig:
    config = service.get_config(project_id)
    if config is None:
        raise HTTPException(404, {"code": "DEMO_LOOP_CONFIG_NOT_FOUND", "message": "Demo loop is not configured"})
    return config


def _config_view(db: Session, config: DemoLoopConfig) -> dict:
    deployment = None
    model: dict | None = None
    if config.deployment_id:
        row = db.query(InferenceDeployment).filter(InferenceDeployment.id == config.deployment_id).first()
        if row is not None:
            deployment = {
                "id": str(row.id),
                "name": row.name,
                "desired_state": row.desired_state,
                "observed_state": row.observed_state,
            }
            if row.model_version_id:
                version = db.query(ModelVersion).filter(ModelVersion.id == row.model_version_id).first()
                if version is not None:
                    registered = db.query(RegisteredModel).filter(
                        RegisteredModel.id == version.registered_model_id,
                    ).first()
                    model = {
                        "model_version_id": str(version.id),
                        "version_number": version.version_number,
                        "model_name": registered.name if registered else None,
                        "lifecycle_state": version.lifecycle_state,
                        "approval_status": version.approval_status,
                        "feature_schema": version.feature_schema or [],
                    }
    retrain_dataset = None
    if config.retrain_dataset_artifact_id:
        artifact = db.query(Artifact).filter(Artifact.id == config.retrain_dataset_artifact_id).first()
        if artifact is not None:
            retrain_dataset = {"id": str(artifact.id), "name": artifact.name}
    return {
        "id": str(config.id),
        "project_id": str(config.project_id),
        "name": config.name,
        "deployment_id": str(config.deployment_id) if config.deployment_id else None,
        "error_classes": config.error_classes or [],
        "preprocess_enabled": bool(config.preprocess_enabled),
        "alert_threshold_rows": config.alert_threshold_rows,
        "require_review": bool(config.require_review),
        "review_annotator_ids": config.review_annotator_ids or [],
        "retrain_enabled": bool(config.retrain_enabled),
        "retrain_threshold_rows": config.retrain_threshold_rows,
        "retrain_dataset_artifact_id": (
            str(config.retrain_dataset_artifact_id) if config.retrain_dataset_artifact_id else None
        ),
        "retrain_target_column": config.retrain_target_column,
        "retrain_max_trials": config.retrain_max_trials,
        "retrain_dataset": retrain_dataset,
        "deployment": deployment,
        "current_model": model,
        "swapped_model_version_id": (
            str(config.swapped_model_version_id) if config.swapped_model_version_id else None
        ),
    }


@router.get("/api/projects/{project_id}/demo-loop/config")
def get_demo_loop_config(
    project_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    require_project_access(db, project_id, current_user.id, "project.read")
    config = _require_config(db, project_id, _service(db))
    return _config_view(db, config)


@router.put("/api/projects/{project_id}/demo-loop/config")
def update_demo_loop_config(
    project_id: uuid.UUID,
    data: DemoLoopConfigUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    require_project_access(db, project_id, current_user.id, "resource.create")
    service = _service(db)
    try:
        # exclude_unset: partial updates must not silently reset omitted flags.
        config = service.save_config(project_id, current_user.id, data.model_dump(exclude_unset=True))
    except DemoLoopError as error:
        status_code = 404 if "NOT_FOUND" in error.code else 422
        raise HTTPException(status_code, {"code": error.code, "message": str(error)})
    return _config_view(db, config)


@router.post("/api/projects/{project_id}/demo-loop/predict")
def demo_loop_predict(
    project_id: uuid.UUID,
    data: DemoLoopPredictRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    require_project_access(db, project_id, current_user.id, "resource.create")
    service = _service(db)
    config = _require_config(db, project_id, service)
    try:
        result = service.predict(config, data.record, current_user.id)
    except DemoLoopError as error:
        status_code = 404 if "NOT_FOUND" in error.code or "MISSING" in error.code else 422
        raise HTTPException(status_code, {"code": error.code, "message": str(error)})
    return result


@router.get("/api/projects/{project_id}/demo-loop/status")
def demo_loop_status(
    project_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    require_project_access(db, project_id, current_user.id, "project.read")
    service = _service(db)
    config = _require_config(db, project_id, service)
    service.refresh_retrain_status(config, current_user.id)
    return service.build_status(config)


@router.post("/api/projects/{project_id}/demo-loop/reset")
def demo_loop_reset(
    project_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    require_project_access(db, project_id, current_user.id, "resource.create")
    service = _service(db)
    config = _require_config(db, project_id, service)
    service.reset(config, current_user.id)
    return service.build_status(config)
