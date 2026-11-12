"""Closed-loop demo API: config, per-row predict, status, reset."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Body, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
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
    feature_engineering_mode: str | None = None
    feature_operator_id: str | None = None
    feature_script: str | None = None
    alert_threshold_rows: int | None = None
    require_review: bool | None = None
    review_annotator_ids: list[str] | None = None
    retrain_enabled: bool | None = None
    retrain_threshold_rows: int | None = None
    retrain_dataset_artifact_id: str | None = None
    retrain_dataset_artifact_ids: list[str] | None = None
    retrain_target_column: str | None = None
    retrain_max_trials: int | None = None
    retrain_ensemble_enabled: bool | None = None
    retrain_ensemble_top_k: int | None = Field(default=None, ge=2, le=5)
    retrain_algorithm_ids: list[str] | None = None
    retrain_input_columns: list[str] | None = None
    retrain_mode: str | None = Field(default=None, max_length=16)
    retrain_agent_recipe_id: str | None = Field(default=None, max_length=64)
    # 无监督漂移治理（技术方案 §3.6）：PSI 触发重拟合预警（默认关=存量零变化）
    psi_enabled: bool | None = None
    psi_threshold: float | None = Field(default=None, gt=0.0, le=1.0)
    collect_correct_enabled: bool | None = None
    correct_sample_ratio: str | None = None
    field_descriptions: dict | None = None


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
                        # 模型的 label 列（AutoML 注册时写入），闭环重训目标列默认值；
                        # 扁平 output_schema（目标列名在 name 键）的注册路径兼容
                        "target_columns": (
                            (version.output_schema or {}).get("target_columns")
                            or ([str((version.output_schema or {}).get("name"))]
                                if (version.output_schema or {}).get("name") else [])
                        ),
                    }
    retrain_dataset = None
    dataset_ids = list(getattr(config, "retrain_dataset_artifact_ids", None) or [])
    if not dataset_ids and config.retrain_dataset_artifact_id:
        dataset_ids = [config.retrain_dataset_artifact_id]
    if dataset_ids:
        artifact = db.query(Artifact).filter(
            Artifact.id == uuid.UUID(str(dataset_ids[0])),
        ).first()
        if artifact is not None:
            retrain_dataset = {"id": str(artifact.id), "name": artifact.name}
    return {
        "id": str(config.id),
        "project_id": str(config.project_id),
        "name": config.name,
        "deployment_id": str(config.deployment_id) if config.deployment_id else None,
        "error_classes": config.error_classes or [],
        "preprocess_enabled": bool(config.preprocess_enabled),
        "feature_engineering_mode": getattr(config, "feature_engineering_mode", None) or "legacy",
        "feature_operator_id": getattr(config, "feature_operator_id", None),
        "feature_script": getattr(config, "feature_script", None),
        "alert_threshold_rows": config.alert_threshold_rows,
        "require_review": bool(config.require_review),
        "review_annotator_ids": config.review_annotator_ids or [],
        "retrain_enabled": bool(config.retrain_enabled),
        "retrain_threshold_rows": config.retrain_threshold_rows,
        "retrain_dataset_artifact_id": (
            str(config.retrain_dataset_artifact_id) if config.retrain_dataset_artifact_id else None
        ),
        "retrain_dataset_artifact_ids": [str(item) for item in dataset_ids],
        "retrain_target_column": config.retrain_target_column,
        "retrain_max_trials": config.retrain_max_trials,
        "retrain_ensemble_enabled": bool(getattr(config, "retrain_ensemble_enabled", False)),
        "retrain_ensemble_top_k": int(getattr(config, "retrain_ensemble_top_k", 3) or 3),
        "retrain_algorithm_ids": [str(item) for item in (getattr(config, "retrain_algorithm_ids", None) or [])],
        "retrain_input_columns": [str(item) for item in (getattr(config, "retrain_input_columns", None) or [])],
        "retrain_mode": (getattr(config, "retrain_mode", None) or "engine"),
        "retrain_agent_recipe_id": (
            str(config.retrain_agent_recipe_id) if getattr(config, "retrain_agent_recipe_id", None) else None
        ),
        "retrain_agent_run_id": (
            str(config.retrain_agent_run_id) if getattr(config, "retrain_agent_run_id", None) else None
        ),
        "retrain_cool_until": (
            config.retrain_cool_until.isoformat() if getattr(config, "retrain_cool_until", None) else None
        ),
        "retrain_trained_baseline_count": int(
            getattr(config, "retrain_trained_baseline_count", 0) or 0
        ),
        "collect_correct_enabled": bool(config.collect_correct_enabled),
        "correct_sample_ratio": config.correct_sample_ratio or "1:1",
        "psi_enabled": bool(getattr(config, "psi_enabled", False)),
        "psi_threshold": float(getattr(config, "psi_threshold", 0.25) or 0.25),
        "field_descriptions": config.field_descriptions or {},
        "error_artifact_id": (
            str(config.error_artifact_id) if config.error_artifact_id else None
        ),
        "retrain_dataset": retrain_dataset,
        "deployment": deployment,
        "current_model": model,
        "swapped_model_version_id": (
            str(config.swapped_model_version_id) if config.swapped_model_version_id else None
        ),
        "error_count": int(config.error_count or 0),
        "alert_count": int(config.alert_count or 0),
        "total_count": int(getattr(config, "total_count", 0) or 0),
        "retrain_status": config.retrain_status,
        "created_at": config.created_at.isoformat() if config.created_at else None,
        "updated_at": config.updated_at.isoformat() if config.updated_at else None,
    }


def _require_loop(db: Session, project_id, loop_id: uuid.UUID, service: DemoLoopService) -> DemoLoopConfig:
    config = service.get_config_by_id(project_id, loop_id)
    if config is None:
        raise HTTPException(404, {"code": "DEMO_LOOP_CONFIG_NOT_FOUND", "message": "Demo loop not found"})
    return config


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


# ------------------------------------------------------- loop task list (CRUD)

@router.get("/api/projects/{project_id}/demo-loop/loops")
def list_demo_loops(
    project_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    require_project_access(db, project_id, current_user.id, "project.read")
    service = _service(db)
    return {"items": [_config_view(db, config) for config in service.list_configs(project_id)]}


@router.post("/api/projects/{project_id}/demo-loop/loops", status_code=201)
def create_demo_loop(
    project_id: uuid.UUID,
    data: DemoLoopConfigUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    require_project_access(db, project_id, current_user.id, "resource.create")
    service = _service(db)
    try:
        config = service.create_config(project_id, current_user.id, data.model_dump(exclude_unset=True))
    except DemoLoopError as error:
        status_code = 404 if "NOT_FOUND" in error.code else 422
        raise HTTPException(status_code, {"code": error.code, "message": str(error)})
    return _config_view(db, config)


@router.get("/api/projects/{project_id}/demo-loop/loops/{loop_id}")
def get_demo_loop(
    project_id: uuid.UUID,
    loop_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    require_project_access(db, project_id, current_user.id, "project.read")
    service = _service(db)
    config = _require_loop(db, project_id, loop_id, service)
    return _config_view(db, config)


@router.put("/api/projects/{project_id}/demo-loop/loops/{loop_id}")
def update_demo_loop(    project_id: uuid.UUID,
    loop_id: uuid.UUID,
    data: DemoLoopConfigUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    require_project_access(db, project_id, current_user.id, "resource.create")
    service = _service(db)
    config = _require_loop(db, project_id, loop_id, service)
    try:
        config = service.update_config(config, project_id, data.model_dump(exclude_unset=True))
    except DemoLoopError as error:
        status_code = 404 if "NOT_FOUND" in error.code else 422
        raise HTTPException(status_code, {"code": error.code, "message": str(error)})
    return _config_view(db, config)


@router.delete("/api/projects/{project_id}/demo-loop/loops/{loop_id}")
def delete_demo_loop(
    project_id: uuid.UUID,
    loop_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    require_project_access(db, project_id, current_user.id, "resource.create")
    service = _service(db)
    config = _require_loop(db, project_id, loop_id, service)
    service.delete_config(config)
    return {"status": "deleted", "id": str(loop_id)}


@router.post("/api/projects/{project_id}/demo-loop/loops/{loop_id}/predict")
def demo_loop_predict_scoped(
    project_id: uuid.UUID,
    loop_id: uuid.UUID,
    data: DemoLoopPredictRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    require_project_access(db, project_id, current_user.id, "resource.create")
    service = _service(db)
    config = _require_loop(db, project_id, loop_id, service)
    try:
        result = service.predict(config, data.record, current_user.id)
    except DemoLoopError as error:
        status_code = 404 if "NOT_FOUND" in error.code or "MISSING" in error.code else 422
        raise HTTPException(status_code, {"code": error.code, "message": str(error)})
    return result


@router.get("/api/projects/{project_id}/demo-loop/loops/{loop_id}/status")
def demo_loop_status_scoped(
    project_id: uuid.UUID,
    loop_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    require_project_access(db, project_id, current_user.id, "project.read")
    service = _service(db)
    config = _require_loop(db, project_id, loop_id, service)
    service.refresh_retrain_status(config, current_user.id)
    return service.build_status(config)


@router.post("/api/projects/{project_id}/demo-loop/loops/{loop_id}/reset")
def demo_loop_reset_scoped(
    project_id: uuid.UUID,
    loop_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    require_project_access(db, project_id, current_user.id, "resource.create")
    service = _service(db)
    config = _require_loop(db, project_id, loop_id, service)
    service.reset(config, current_user.id)
    return service.build_status(config)


class ReflowFeedbackRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_id: str = Field(min_length=1, max_length=64)
    row_index: int = Field(ge=0)
    mark: str = Field(pattern="^(confirmed_fault|false_alarm|none)$")


def _reflow_rows_payload(db: Session, config, limit: int) -> dict:
    """回流行列表（报警确认反馈的数据源）：报错数据集行 + 已标记状态。"""
    import pandas as pd

    from app.services.artifact_service import build_artifact_service

    if not config.error_artifact_id:
        return {"rows": [], "artifact_id": None, "total": 0}
    artifact = db.query(Artifact).filter(Artifact.id == config.error_artifact_id).first()
    if artifact is None:
        return {"rows": [], "artifact_id": None, "total": 0}
    marks = (config.feedback_marks or {}).get(str(artifact.id), {})
    service = build_artifact_service(db)
    with service.materialize(artifact.id, config.project_id, expected_type="dataset") as path:
        frame = pd.read_csv(path)
    total = int(len(frame))
    tail = frame.tail(limit)
    start = total - len(tail)
    rows = []
    for offset, (index, row) in enumerate(tail.iterrows()):
        rows.append({
            "row_index": int(start + offset),
            "record": {str(key): (None if pd.isna(value) else value) for key, value in row.items()
                       if str(key) not in {"anomaly_score", "feedback"}},
            "anomaly_score": None if pd.isna(row.get("anomaly_score")) else float(row.get("anomaly_score")),
            "feedback": str((marks or {}).get(str(start + offset)) or row.get("feedback") or ""),
        })
    return {"rows": rows, "artifact_id": str(artifact.id), "total": total}


@router.get("/api/projects/{project_id}/demo-loop/loops/{loop_id}/reflow-rows")
def list_reflow_rows(
    project_id: uuid.UUID,
    loop_id: uuid.UUID,
    limit: int = 50,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """回流行列表（技术方案 §3.6 弱监督反馈的数据源）：报错数据集尾部行 + 标记状态。"""
    require_project_access(db, project_id, current_user.id, "project.read")
    service = _service(db)
    config = _require_loop(db, project_id, loop_id, service)
    return _reflow_rows_payload(db, config, max(1, min(int(limit or 50), 200)))


@router.post("/api/projects/{project_id}/demo-loop/loops/{loop_id}/reflow-rows/feedback")
def mark_reflow_row(
    project_id: uuid.UUID,
    loop_id: uuid.UUID,
    data: ReflowFeedbackRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """行级报警确认（弱监督核心机制，§3.6）：确认故障→验证集、误报→排除集。

    标记存 ``feedback_marks``（{"artifact_id": {"row_index": mark}}）——不回写
    工件文件；重拟合消费端物化时打 feedback 列（append-only 行号稳定）。
    """
    require_project_access(db, project_id, current_user.id, "resource.create")
    service = _service(db)
    config = _require_loop(db, project_id, loop_id, service)
    artifact_uuid = uuid.UUID(data.artifact_id)
    artifact = db.query(Artifact).filter(
        Artifact.id == artifact_uuid,
        Artifact.project_id == project_id,
    ).first()
    if artifact is None:
        raise HTTPException(404, {"code": "DEMO_LOOP_ARTIFACT_NOT_FOUND", "message": "回流数据集不存在"})
    marks = dict(config.feedback_marks or {})
    artifact_marks = dict(marks.get(str(artifact.id)) or {})
    if data.mark == "none":
        artifact_marks.pop(str(data.row_index), None)
    else:
        artifact_marks[str(data.row_index)] = data.mark
    if artifact_marks:
        marks[str(artifact.id)] = artifact_marks
    else:
        marks.pop(str(artifact.id), None)
    config.feedback_marks = marks
    service._emit(
        config, "reflow_feedback",
        f"回流行 #{data.row_index} 标记为 {data.mark}",
        severity="info",
        payload={"artifact_id": str(artifact.id), "row_index": data.row_index, "mark": data.mark},
    )
    db.commit()
    return {"feedback_marks": marks, "mark": data.mark}
