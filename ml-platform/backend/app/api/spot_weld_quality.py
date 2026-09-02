"""Project-scoped APIs for report-compatible spot-weld quality perception."""

from __future__ import annotations

import io
import logging
import uuid
from collections import Counter
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func
from sqlalchemy.orm import Session, load_only

from app.api.auth import get_current_user
from app.api.project_security import audit_service, require_project_access
from app.config import settings
from app.database import get_db
from app.models.model_library import ModelLibrary
from app.models.model_registry import ModelVersion, RegisteredModel
from app.models.spot_weld_quality import (
    SpotWeldLabelRevision,
    SpotWeldLabelSnapshot,
    SpotWeldQualityRuleSet,
    SpotWeldQualityRun,
    SpotWeldQualitySample,
)
from app.models.user import User
from app.services.artifact_service import ArtifactAccessError, build_artifact_service
from app.services.audit import AuditIntent
from app.services.project_access import ProjectAccessService
from app.services.spot_weld_features import QualityPipelineError, build_feature_frame
from app.services.spot_weld_quality import (
    _annotation_progress,
    build_annotation_export,
    create_demo_quality_dataset,
    create_quality_run_record,
    load_registered_annotation_model,
    load_registered_quality_model,
    normalize_quality_search_config,
    normalize_annotation_label,
    normalize_report_rule_config,
    QUALITY_LABEL_MODES,
    resolve_dataset_frame,
    save_labeled_dataset,
    train_label_snapshot,
    update_quality_run_rules,
    validate_report_frame,
    resolve_quality_run_configuration,
    resolve_manual_run_configuration,
    run_clustering,
    run_registered_model_annotation,
    annotation_feature_frame,
    normalize_annotation_process_rules,
    normalize_annotation_label_dtype,
    registered_annotation_feature_importance,
)


router = APIRouter(prefix="/api/projects/{project_id}/spot-weld", tags=["spot-weld-quality"])
all_runs_router = APIRouter(prefix="/api/spot-weld", tags=["spot-weld-quality"])
logger = logging.getLogger(__name__)
VALID_LABELS = frozenset({
    "normal", "strong_splatter", "weak_splatter", "power_fluctuation", "spot_too_small",
    "spot_too_large", "energy_anomaly", "current_jump", "anomaly_cluster",
})
QUALITY_OUTPUT_ARTIFACT_TYPES = {
    "model": "model",
    "schema": "quality_schema",
    "report": "quality_report",
    "model_comparison_chart": "quality_report_chart",
    "cluster_pca_chart": "quality_report_chart",
    "feature_importance_chart": "quality_report_chart",
    "warning_distribution_chart": "quality_report_chart",
    "waveform_comparison_chart": "quality_report_chart",
}


class DatasetQualityRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dataset_artifact_id: uuid.UUID
    field_mapping: dict[str, str] = Field(default_factory=dict)
    algorithm_ids: list[str] = Field(default_factory=list)
    search_method: str = "bayesian"
    max_trials: int = Field(default=20, ge=5, le=200)
    time_budget: int = Field(default=600, ge=60, le=9999)
    target_column: str | None = None
    target_column_created: bool = False
    target_column_dtype: str | None = None
    label_dtype: str | None = None
    selected_model_id: uuid.UUID | None = None
    weak_supervision: bool = False
    cluster_labels: dict[str, str] = Field(default_factory=dict)
    # Rules contain nested token arrays; semantic validation is performed by
    # normalize_annotation_process_rules after the request contract parses.
    process_rules: list[dict[str, Any]] = Field(default_factory=list)
    input_columns: list[str] | None = None
    cross_validation_enabled: bool = True
    cross_validation_folds: int | None = 3
    label_mode: Literal["automatic", "manual"] = "automatic"
    workflow_kind: Literal["quality_modeling", "data_annotation"] = "quality_modeling"
    rule_config: dict[str, float | int] = Field(default_factory=dict)


class LabelRequest(BaseModel):
    label: str
    note: str = ""


class ReviewRequest(BaseModel):
    decision: str
    comment: str = ""


class SnapshotRequest(BaseModel):
    name: str = "approved-labels"
    label_source: Literal["approved", "automatic"] = "approved"


class SaveLabeledDatasetRequest(BaseModel):
    label_source: Literal["current", "automatic"] = "current"


class UpdateRulesRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rule_config: dict[str, float | int]


class DemoDatasetRequest(BaseModel):
    row_count: int = Field(default=60, ge=12, le=5000)


class ClusterPreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dataset_artifact_id: uuid.UUID
    selected_model_id: uuid.UUID


def _quality_error(error: QualityPipelineError, status: int = 400):
    raise HTTPException(status, detail=error.to_dict())


def get_quality_artifact_service(request: Request, db: Session):
    factory = getattr(request.app.state, "quality_artifact_service_factory", None)
    return factory(db) if factory is not None else build_artifact_service(db)


def get_quality_dispatcher(request: Request):
    configured = getattr(request.app.state, "quality_dispatcher", None)
    if configured is not None:
        return configured
    app_settings = getattr(request.app.state, "settings", settings)
    if app_settings.task_backend == "celery":
        from app.tasks.spot_weld_quality_tasks import CeleryQualityDispatcher

        configured = CeleryQualityDispatcher()
    else:
        from app.tasks.spot_weld_quality_tasks import LocalQualityDispatcher

        configured = LocalQualityDispatcher()
    request.app.state.quality_dispatcher = configured
    return configured


def _run_or_404(db: Session, project_id: uuid.UUID, run_id: str) -> SpotWeldQualityRun:
    try:
        identifier = uuid.UUID(str(run_id))
    except ValueError:
        raise HTTPException(404, detail={"code": "QUALITY_RUN_NOT_FOUND"})
    run = db.query(SpotWeldQualityRun).filter(
        SpotWeldQualityRun.id == identifier,
        SpotWeldQualityRun.project_id == project_id,
    ).first()
    if run is None:
        raise HTTPException(404, detail={"code": "QUALITY_RUN_NOT_FOUND"})
    return run


def _sample_or_404(db: Session, run: SpotWeldQualityRun, sample_id: str) -> SpotWeldQualitySample:
    try:
        identifier = uuid.UUID(str(sample_id))
    except ValueError:
        raise HTTPException(404, detail={"code": "QUALITY_SAMPLE_NOT_FOUND"})
    sample = db.query(SpotWeldQualitySample).filter(
        SpotWeldQualitySample.id == identifier,
        SpotWeldQualitySample.run_id == run.id,
    ).first()
    if sample is None:
        raise HTTPException(404, detail={"code": "QUALITY_SAMPLE_NOT_FOUND"})
    return sample


def _snapshot_or_404(
    db: Session,
    project_id: uuid.UUID,
    run: SpotWeldQualityRun,
    snapshot_id: str,
) -> SpotWeldLabelSnapshot:
    try:
        identifier = uuid.UUID(str(snapshot_id))
    except (TypeError, ValueError):
        raise HTTPException(404, detail={"code": "QUALITY_LABEL_SNAPSHOT_NOT_FOUND"})
    snapshot = db.query(SpotWeldLabelSnapshot).filter(
        SpotWeldLabelSnapshot.id == identifier,
        SpotWeldLabelSnapshot.project_id == project_id,
        SpotWeldLabelSnapshot.run_id == run.id,
    ).first()
    if snapshot is None:
        raise HTTPException(404, detail={"code": "QUALITY_LABEL_SNAPSHOT_NOT_FOUND"})
    return snapshot


def _serialize_run(
    run: SpotWeldQualityRun,
    *,
    include_results: bool = True,
    annotated_count_override: int | None = None,
) -> dict:
    input_fingerprint = run.input_fingerprint or {}
    label_mode = input_fingerprint.get("label_mode", "automatic")
    statistics = run.statistics or {}
    stored_progress = statistics.get("annotation_progress") or {}
    total_count = int(
        stored_progress.get("total_count")
        or statistics.get("row_count")
        or input_fingerprint.get("row_count")
        or len(run.samples)
        or 0
    )
    if annotated_count_override is not None:
        annotated_count = int(annotated_count_override)
    elif stored_progress and total_count:
        annotated_count = int(stored_progress.get("annotated_count") or 0)
    elif label_mode == "manual":
        annotated_count = sum(1 for sample in run.samples if sample.current_label)
    else:
        annotated_count = sum(1 for sample in run.samples if sample.automatic_label)
    percent = round((annotated_count / total_count) * 100, 2) if total_count else 0.0
    display_status = run.status
    if label_mode == "manual" and display_status not in {"failed", "cancelled"}:
        display_status = "completed" if total_count and annotated_count >= total_count else "running"
    payload = {
        "id": str(run.id),
        "project_id": str(run.project_id),
        "project_name": run.project.name if run.project is not None else None,
        "created_by_id": str(run.created_by_id) if run.created_by_id else None,
        "created_by_name": run.created_by.username if run.created_by is not None else None,
        "dataset_artifact_id": str(run.dataset_artifact_id),
        "status": display_status,
        "task_id": run.task_id,
        "worker_id": run.worker_id,
        "sample_count": total_count or len(run.samples),
        "feature_version": (run.statistics or {}).get("feature_version", "report_v1"),
        "rule_set_version": run.rule_set_version,
        "selected_algorithm_ids": list(input_fingerprint.get("algorithm_ids") or []),
        "search": {
            "contract": input_fingerprint.get("search_contract"),
            "method": input_fingerprint.get("search_method"),
            "max_trials": input_fingerprint.get("max_trials"),
            "time_budget": input_fingerprint.get("time_budget"),
        },
        "target_column": input_fingerprint.get("target_column"),
        "target_column_created": bool(input_fingerprint.get("target_column_created", False)),
        "target_column_dtype": input_fingerprint.get("target_column_dtype"),
        "target_schema": statistics.get("target_schema") or input_fingerprint.get("target_schema"),
        "selected_model_id": input_fingerprint.get("selected_model_id"),
        "weak_supervision": bool(input_fingerprint.get("weak_supervision", False)),
        "cluster_labels": dict(input_fingerprint.get("cluster_labels") or {}),
        "process_rules": list(input_fingerprint.get("process_rules") or []),
        "input_columns": list(input_fingerprint.get("input_columns") or []),
        "evaluation": dict(
            input_fingerprint.get("evaluation")
            or statistics.get("evaluation")
            or {}
        ),
        "label_mode": label_mode,
        "rule_config": dict(input_fingerprint.get("rule_config") or {}),
        "annotation_progress": {
            "annotated_count": annotated_count,
            "total_count": total_count,
            "percent": percent,
        },
        "modeling_progress": dict(statistics.get("modeling_progress") or {}),
        "statistics": statistics,
        "error_code": run.error_code,
        "error_details": run.error_details or {},
        "created_at": run.created_at.isoformat() if run.created_at else None,
        "updated_at": run.updated_at.isoformat() if run.updated_at else None,
    }
    if include_results:
        payload.update({
            "field_mapping": run.field_mapping or {},
            "feature_schema": run.feature_schema or [],
            "input_schema": statistics.get("input_schema") or input_fingerprint.get("input_schema") or [],
            "automl_results": run.automl_results or [],
            "clustering_results": run.clustering_results or {},
            "output_artifacts": run.output_artifacts or {},
        })
    return payload


def _manual_annotation_counts(db: Session, runs: list[SpotWeldQualityRun]) -> dict[uuid.UUID, int]:
    manual_run_ids = [
        run.id
        for run in runs
        if (run.input_fingerprint or {}).get("label_mode", "automatic") == "manual"
    ]
    if not manual_run_ids:
        return {}
    counts = {run_id: 0 for run_id in manual_run_ids}
    counts.update({
        run_id: int(count)
        for run_id, count in db.query(
            SpotWeldQualitySample.run_id,
            func.count(SpotWeldQualitySample.id),
        ).filter(
            SpotWeldQualitySample.run_id.in_(manual_run_ids),
            SpotWeldQualitySample.current_label.isnot(None),
        ).group_by(SpotWeldQualitySample.run_id).all()
    })
    return counts


def _serialize_sample(sample: SpotWeldQualitySample, *, include_waveforms: bool = False) -> dict:
    payload = {
        "id": str(sample.id),
        "display_id": sample.display_id,
        "source_row_index": sample.source_row_index,
        "automatic_label": sample.automatic_label,
        "current_label": sample.current_label,
        "current_note": sample.current_note,
        "review_status": sample.review_status,
        "warning_level": sample.warning_level,
        "defect_probability": sample.defect_probability,
        "cluster_id": sample.cluster_id,
        "rule_hits": sample.rule_hits or [],
        "table_values": sample.table_values or {},
    }
    if include_waveforms:
        payload["feature_values"] = sample.feature_values or {}
        payload["waveforms"] = sample.waveforms or {}
    return payload


def _serialize_quality_model(
    model: ModelLibrary,
    *,
    registered_model: RegisteredModel | None = None,
    model_version: ModelVersion | None = None,
) -> dict:
    output_schema = model_version.output_schema if model_version else {}
    return {
        "id": str(model.id),
        "name": registered_model.name if registered_model else model.name,
        "version": f"v{model_version.version_number}" if model_version else model.version,
        "status": model.status,
        "framework": model_version.framework if model_version else model.framework,
        "backbone": model.backbone,
        "metrics": model.metrics or {},
        "params": model.params or {},
        "model_artifact_id": str(model.model_artifact_id) if model.model_artifact_id else None,
        "format": model.format,
        "tags": model.tags or [],
        "registered_model_id": str(registered_model.id) if registered_model else None,
        "model_version_id": str(model_version.id) if model_version else None,
        "approval_status": model_version.approval_status if model_version else None,
        "feature_schema": model_version.feature_schema if model_version else [],
        "label_dtype": output_schema.get("dtype") if isinstance(output_schema, dict) else None,
        "target_column": output_schema.get("name") if isinstance(output_schema, dict) else None,
        "target_column_dtype": output_schema.get("dtype") if isinstance(output_schema, dict) else None,
        "created_at": model.created_at.isoformat() if model.created_at else None,
    }


@router.post("/validate")
def validate_dataset(
    project_id: uuid.UUID,
    data: DatasetQualityRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    require_project_access(db, project_id, current_user.id, "resource.create")
    try:
        normalize_quality_search_config(
            data.algorithm_ids,
            data.search_method,
            data.max_trials,
            data.time_budget,
        )
        if data.label_mode not in QUALITY_LABEL_MODES:
            raise QualityPipelineError("QUALITY_LABEL_MODE_INVALID")
        if data.workflow_kind == "quality_modeling":
            normalize_report_rule_config(data.rule_config)
        _, frame = resolve_dataset_frame(
            db,
            get_quality_artifact_service(request, db),
            project_id,
            data.dataset_artifact_id,
        )
        if data.workflow_kind == "quality_modeling" and (not isinstance(data.target_column, str) or not data.target_column.strip()):
            raise QualityPipelineError("QUALITY_TARGET_COLUMN_REQUIRED")
        if data.workflow_kind == "data_annotation" and data.label_mode == "manual" and (not isinstance(data.target_column, str) or not data.target_column.strip()):
            raise QualityPipelineError("QUALITY_TARGET_COLUMN_REQUIRED")
        if data.workflow_kind == "data_annotation":
            automatic_annotation = data.label_mode == "automatic"
            configuration = resolve_manual_run_configuration(
                frame,
                target_column=None if automatic_annotation else data.target_column,
                target_column_created=False if automatic_annotation else data.target_column_created,
                target_column_dtype=(data.label_dtype or data.target_column_dtype) if automatic_annotation else data.target_column_dtype,
                input_columns=None if automatic_annotation else data.input_columns,
            )
            if data.label_mode == "automatic" and data.selected_model_id is not None and data.weak_supervision:
                label_dtype = normalize_annotation_label_dtype(
                    data.label_dtype or data.target_column_dtype or configuration["target_schema"]["dtype"],
                )
                artifact_service = get_quality_artifact_service(request, db)
                _, bundle = load_registered_annotation_model(
                    db, project_id=project_id, model_id=data.selected_model_id, artifact_service=artifact_service,
                )
                feature_frame = annotation_feature_frame(frame, bundle)
                normalize_annotation_process_rules(
                    data.process_rules,
                    columns=[str(column) for column in frame.columns],
                    label_dtype=label_dtype,
                )
        else:
            resolve_quality_run_configuration(
                frame,
                field_mapping=data.field_mapping,
                target_column=data.target_column,
                target_column_created=data.target_column_created,
                target_column_dtype=data.target_column_dtype,
                input_columns=data.input_columns,
                cross_validation_enabled=data.cross_validation_enabled,
                cross_validation_folds=data.cross_validation_folds,
            )
        if data.workflow_kind == "data_annotation" and data.label_mode == "automatic" and data.selected_model_id is None:
            raise QualityPipelineError("QUALITY_MODEL_REQUIRED")
    except QualityPipelineError as error:
        _quality_error(error)
    if data.workflow_kind == "data_annotation":
        return {
            "row_count": int(len(frame)),
            "valid_rows": int(len(frame)),
            "invalid_rows": 0,
            "feature_schema": [],
            "errors": [],
        }
    return validate_report_frame(frame, data.field_mapping)


@router.post("/runs", status_code=202)
def create_run(
    project_id: uuid.UUID,
    data: DatasetQualityRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    access = require_project_access(db, project_id, current_user.id, "resource.create")
    try:
        search_config = normalize_quality_search_config(
            data.algorithm_ids,
            data.search_method,
            data.max_trials,
            data.time_budget,
        )
        if data.label_mode not in QUALITY_LABEL_MODES:
            raise QualityPipelineError("QUALITY_LABEL_MODE_INVALID")
        normalized_rule_config = (
            {} if data.workflow_kind == "data_annotation"
            else normalize_report_rule_config(data.rule_config)
        )
        artifact_service = get_quality_artifact_service(request, db)
        _, frame = resolve_dataset_frame(
            db,
            artifact_service,
            project_id,
            data.dataset_artifact_id,
        )
        if data.workflow_kind == "quality_modeling" and (not isinstance(data.target_column, str) or not data.target_column.strip()):
            raise QualityPipelineError("QUALITY_TARGET_COLUMN_REQUIRED")
        if data.workflow_kind == "data_annotation" and data.label_mode == "manual" and (not isinstance(data.target_column, str) or not data.target_column.strip()):
            raise QualityPipelineError("QUALITY_TARGET_COLUMN_REQUIRED")
        if data.workflow_kind == "data_annotation":
            automatic_annotation = data.label_mode == "automatic"
            run_configuration = resolve_manual_run_configuration(
                frame,
                target_column=None if automatic_annotation else data.target_column,
                target_column_created=False if automatic_annotation else data.target_column_created,
                target_column_dtype=(data.label_dtype or data.target_column_dtype) if automatic_annotation else data.target_column_dtype,
                input_columns=None if automatic_annotation else data.input_columns,
            )
            normalized_process_rules = []
            if data.label_mode == "automatic" and data.weak_supervision:
                if data.selected_model_id is None:
                    raise QualityPipelineError("QUALITY_MODEL_REQUIRED")
                _, bundle = load_registered_annotation_model(
                    db, project_id=project_id, model_id=data.selected_model_id, artifact_service=artifact_service,
                )
                feature_frame = annotation_feature_frame(frame, bundle)
                label_dtype = normalize_annotation_label_dtype(
                    data.label_dtype or data.target_column_dtype or run_configuration["target_schema"]["dtype"],
                )
                normalized_process_rules = normalize_annotation_process_rules(
                    data.process_rules,
                    columns=[str(column) for column in frame.columns],
                    label_dtype=label_dtype,
                )
                run_configuration["target_column_dtype"] = label_dtype
                run_configuration["target_schema"] = {
                    **run_configuration["target_schema"],
                    "dtype": label_dtype,
                    "classes": list(dict.fromkeys(rule["label"] for rule in normalized_process_rules)),
                }
                run_configuration["target_schema"]["class_count"] = len(run_configuration["target_schema"]["classes"])
        else:
            run_configuration, _ = resolve_quality_run_configuration(
                frame,
                field_mapping=data.field_mapping,
                target_column=data.target_column,
                target_column_created=data.target_column_created,
                target_column_dtype=data.target_column_dtype,
                input_columns=data.input_columns,
                cross_validation_enabled=data.cross_validation_enabled,
                cross_validation_folds=data.cross_validation_folds,
            )
        if data.workflow_kind == "data_annotation" and data.label_mode == "automatic" and data.selected_model_id is None:
            raise QualityPipelineError("QUALITY_MODEL_REQUIRED")
        with audit_service(db).project_action(
            db,
            request=request,
            actor=current_user,
            access=access,
            permission="resource.create",
            intent=AuditIntent(
                project_id=project_id,
                action="spot_weld_quality.run.create",
                resource_type="spot_weld_quality_run",
                changes={
                    "dataset_artifact_id": str(data.dataset_artifact_id),
                    "feature_version": "report_v1",
                    "algorithm_ids": search_config["algorithm_ids"],
                    "search_method": search_config["search_method"],
                    "max_trials": search_config["max_trials"],
                    "time_budget": search_config["time_budget"],
                    "target_column": run_configuration["target_column"],
                    "target_column_created": run_configuration["target_column_created"],
                    "target_column_dtype": run_configuration["target_column_dtype"],
                    "selected_model_id": str(data.selected_model_id) if data.selected_model_id else None,
                    "weak_supervision": data.weak_supervision,
                    "cluster_labels": data.cluster_labels,
                    "process_rules": normalized_process_rules if data.workflow_kind == "data_annotation" else data.process_rules,
                    "input_columns": run_configuration["input_columns"],
                    "evaluation": run_configuration["evaluation"],
                    "label_mode": data.label_mode,
                    "workflow_kind": data.workflow_kind,
                    "rule_config": normalized_rule_config,
                },
            ),
            allowed_changes={
                "dataset_artifact_id", "feature_version", "algorithm_ids", "search_method",
                "max_trials", "time_budget", "target_column", "target_column_created", "target_column_dtype",
                "selected_model_id", "weak_supervision",
                "cluster_labels", "process_rules",
                "input_columns", "evaluation", "label_mode", "workflow_kind", "rule_config",
            },
        ):
            run = create_quality_run_record(
                db,
                project_id=project_id,
                user_id=current_user.id,
                dataset_artifact_id=data.dataset_artifact_id,
                field_mapping=data.field_mapping,
                algorithm_ids=search_config["algorithm_ids"],
                search_method=search_config["search_method"],
                max_trials=search_config["max_trials"],
                time_budget=search_config["time_budget"],
                target_column=data.target_column,
                target_column_created=data.target_column_created,
                target_column_dtype=data.target_column_dtype,
                selected_model_id=data.selected_model_id,
                weak_supervision=data.weak_supervision,
                cluster_labels=data.cluster_labels,
                process_rules=normalized_process_rules if data.workflow_kind == "data_annotation" else data.process_rules,
                input_columns=data.input_columns,
                cross_validation_enabled=data.cross_validation_enabled,
                cross_validation_folds=data.cross_validation_folds,
                label_mode=data.label_mode,
                workflow_kind=data.workflow_kind,
                rule_config=normalized_rule_config,
                artifact_service=artifact_service,
            )
    except QualityPipelineError as error:
        _quality_error(error)
    _dispatch_quality_run(db, run, request, current_user, access)
    return _serialize_run(run)


def _dispatch_quality_run(
    db: Session,
    run: SpotWeldQualityRun,
    request: Request,
    actor: User,
    access,
) -> None:
    try:
        task_id = get_quality_dispatcher(request).enqueue(str(run.id))
    except Exception as error:
        with audit_service(db).project_action(
            db,
            request=request,
            actor=actor,
            access=access,
            permission="resource.create",
            intent=AuditIntent(
                project_id=run.project_id,
                action="spot_weld_quality.run.dispatch_failed",
                resource_type="spot_weld_quality_run",
                resource_id=str(run.id),
                changes={"status": "failed", "error_code": "QUALITY_RUN_DISPATCH_FAILED"},
            ),
            allowed_changes={"status", "error_code"},
        ):
            run.status = "failed"
            run.error_code = "QUALITY_RUN_DISPATCH_FAILED"
            run.error_details = {"code": "QUALITY_RUN_DISPATCH_FAILED"}
        raise HTTPException(
            503,
            detail={
                "code": "QUALITY_RUN_DISPATCH_FAILED",
                "message": "Quality task could not be queued",
            },
        ) from error

    with audit_service(db).project_action(
        db,
        request=request,
        actor=actor,
        access=access,
        permission="resource.create",
        intent=AuditIntent(
            project_id=run.project_id,
            action="spot_weld_quality.run.dispatch",
            resource_type="spot_weld_quality_run",
            resource_id=str(run.id),
            changes={"status": "queued", "task_id": task_id},
        ),
        allowed_changes={"status", "task_id"},
    ):
        run.task_id = task_id
    start = getattr(get_quality_dispatcher(request), "start", None)
    if callable(start):
        start(task_id)


@router.post("/demo-dataset", status_code=201)
def create_demo_dataset(
    project_id: uuid.UUID,
    data: DemoDatasetRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    access = require_project_access(db, project_id, current_user.id, "resource.create")
    try:
        with audit_service(db).project_action(
            db,
            request=request,
            actor=current_user,
            access=access,
            permission="resource.create",
            intent=AuditIntent(
                project_id=project_id,
                action="spot_weld_quality.demo_dataset.create",
                resource_type="dataset",
                changes={"row_count": data.row_count},
            ),
            allowed_changes={"row_count"},
        ):
            artifact = create_demo_quality_dataset(
                db,
                project_id=project_id,
                row_count=data.row_count,
                artifact_service=get_quality_artifact_service(request, db),
            )
    except QualityPipelineError as error:
        _quality_error(error)
    metadata = artifact.metadata_ or {}
    return {
        "id": str(artifact.id),
        "artifact_id": str(artifact.id),
        "name": artifact.name,
        "row_count": metadata.get("row_count", data.row_count),
        "sha256": metadata.get("sha256", ""),
    }


@router.get("/runs")
def list_runs(
    project_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    require_project_access(db, project_id, current_user.id, "project.read")
    runs = db.query(SpotWeldQualityRun).filter(
        SpotWeldQualityRun.project_id == project_id,
    ).order_by(SpotWeldQualityRun.created_at.desc(), SpotWeldQualityRun.id.desc()).all()
    manual_counts = _manual_annotation_counts(db, runs)
    return {
        "items": [
            _serialize_run(
                run,
                include_results=False,
                annotated_count_override=manual_counts.get(run.id),
            )
            for run in runs
        ],
        "total": len(runs),
    }


@all_runs_router.get("/runs")
def list_accessible_runs(
    project_id: uuid.UUID | None = Query(default=None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if project_id is not None:
        require_project_access(db, project_id, current_user.id, "project.read")
        project_ids = [project_id]
    else:
        project_ids = [
            project.id
            for project in ProjectAccessService().accessible_project_query(db, current_user.id).all()
        ]
    runs = db.query(SpotWeldQualityRun).filter(
        SpotWeldQualityRun.project_id.in_(project_ids),
    ).order_by(SpotWeldQualityRun.created_at.desc(), SpotWeldQualityRun.id.desc()).all()
    manual_counts = _manual_annotation_counts(db, runs)
    return {
        "items": [
            _serialize_run(
                run,
                include_results=False,
                annotated_count_override=manual_counts.get(run.id),
            )
            for run in runs
        ],
        "total": len(runs),
    }


@router.get("/models")
def list_quality_models(
    project_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List registered platform model versions available for annotation."""
    require_project_access(db, project_id, current_user.id, "project.read")
    rows = db.query(ModelLibrary, ModelVersion, RegisteredModel).join(
        ModelVersion,
        ModelVersion.source_model_library_id == ModelLibrary.id,
    ).join(
        RegisteredModel,
        RegisteredModel.id == ModelVersion.registered_model_id,
    ).filter(
        ModelLibrary.project_id == project_id,
        RegisteredModel.project_id == project_id,
        ModelLibrary.status.in_(("completed", "registered")),
        ModelLibrary.model_artifact_id.isnot(None),
        ModelVersion.source_kind == "platform_joblib",
    ).order_by(ModelVersion.created_at.desc(), ModelVersion.id.desc()).all()
    items = [
        _serialize_quality_model(
            model,
            registered_model=registered_model,
            model_version=model_version,
        )
        for model, model_version, registered_model in rows
    ]
    return {"items": items, "total": len(items)}


@router.get("/datasets/{artifact_id}/columns")
def list_quality_dataset_columns(
    project_id: uuid.UUID,
    artifact_id: str,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    require_project_access(db, project_id, current_user.id, "project.read")
    try:
        artifact_id_value = uuid.UUID(str(artifact_id))
        artifact_service = get_quality_artifact_service(request, db)
        _, frame = resolve_dataset_frame(db, artifact_service, project_id, artifact_id_value)
    except (ValueError, QualityPipelineError, ArtifactAccessError):
        raise HTTPException(404, detail={"code": "QUALITY_DATASET_NOT_FOUND"})
    columns = [
        {"name": str(column), "dtype": str(frame[column].dtype)}
        for column in frame.columns
    ]
    return {
        "columns": columns,
        "row_count": int(len(frame)),
        "target_candidates": [item["name"] for item in columns],
    }


@router.post("/cluster-preview")
def preview_quality_clusters(
    project_id: uuid.UUID,
    data: ClusterPreviewRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    require_project_access(db, project_id, current_user.id, "resource.create")
    artifact_service = get_quality_artifact_service(request, db)
    try:
        _, frame = resolve_dataset_frame(
            db,
            artifact_service,
            project_id,
            data.dataset_artifact_id,
        )
        model_library, bundle = load_registered_annotation_model(
            db,
            project_id=project_id,
            model_id=data.selected_model_id,
            artifact_service=artifact_service,
        )
        features = annotation_feature_frame(frame, bundle)
        schema = list(features.columns)
        importance = registered_annotation_feature_importance(bundle, schema)
        clustering = run_clustering(
            features.to_numpy(dtype=float),
            feature_names=schema,
            feature_importance=importance,
        )
    except QualityPipelineError as error:
        _quality_error(error)
    counts = Counter(clustering.cluster_ids)
    normal_cluster = max(sorted(counts), key=lambda cluster_id: counts[cluster_id])
    total_count = sum(counts.values())
    cluster_summaries = [
        {
            "cluster_id": cluster_id,
            "role": "normal" if cluster_id == normal_cluster else "anomaly",
            "count": counts[cluster_id],
            "percentage": round((counts[cluster_id] / total_count) * 100, 1) if total_count else 0.0,
        }
        for cluster_id in sorted(counts)
    ]
    return {
        "model_id": str(model_library.id),
        "feature_count": len(schema),
        "best_k": clustering.best_k,
        "silhouette_scores": {str(key): value for key, value in clustering.silhouette_scores.items()},
        "cluster_counts": {str(key): counts[key] for key in sorted(counts)},
        "cluster_summaries": cluster_summaries,
        "cluster_ids": clustering.cluster_ids,
        "pca_coordinates": clustering.pca_coordinates.tolist(),
        "weights": clustering.weights,
    }


@router.get("/runs/{run_id}")
def get_run(
    project_id: uuid.UUID,
    run_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    require_project_access(db, project_id, current_user.id, "project.read")
    run = _run_or_404(db, project_id, run_id)
    manual_counts = _manual_annotation_counts(db, [run])
    return _serialize_run(
        run,
        annotated_count_override=manual_counts.get(run.id),
    )


@router.put("/runs/{run_id}/rules")
def update_run_rules(
    project_id: uuid.UUID,
    run_id: str,
    data: UpdateRulesRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    access = require_project_access(db, project_id, current_user.id, "resource.create")
    run = _run_or_404(db, project_id, run_id)
    try:
        normalized = normalize_report_rule_config(data.rule_config)
        with audit_service(db).project_action(
            db,
            request=request,
            actor=current_user,
            access=access,
            permission="resource.create",
            intent=AuditIntent(
                project_id=project_id,
                action="spot_weld_quality.run.rules.update",
                resource_type="spot_weld_quality_run",
                resource_id=str(run.id),
                changes={"rule_config": normalized},
            ),
            allowed_changes={"rule_config"},
        ):
            update_quality_run_rules(db, run, normalized)
    except QualityPipelineError as error:
        _quality_error(error, status=409 if error.code in {"QUALITY_RUN_ACTIVE", "QUALITY_RUN_NOT_RECALCULABLE"} else 400)
    return _serialize_run(run)


@router.delete("/runs/{run_id}")
def delete_run(
    project_id: uuid.UUID,
    run_id: str,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    access = require_project_access(db, project_id, current_user.id, "resource.delete")
    run = _run_or_404(db, project_id, run_id)
    if run.task_id and run.status not in {"completed", "failed", "cancelled"}:
        cancel = getattr(get_quality_dispatcher(request), "cancel", None)
        if callable(cancel):
            try:
                cancel(run.task_id)
            except Exception:
                logger.warning("Failed to cancel annotation task %s before deletion", run.task_id, exc_info=True)
    with audit_service(db).project_action(
        db,
        request=request,
        actor=current_user,
        access=access,
        permission="resource.delete",
        intent=AuditIntent(
            project_id=project_id,
            action="spot_weld_quality.run.delete",
            resource_type="spot_weld_quality_run",
            resource_id=str(run.id),
        ),
        allowed_changes=set(),
    ):
        # Delete dependent rows explicitly so SQLite and production databases
        # have the same behavior even when foreign-key cascades are disabled.
        db.query(SpotWeldLabelSnapshot).filter(SpotWeldLabelSnapshot.run_id == run.id).delete(synchronize_session=False)
        db.query(SpotWeldLabelRevision).filter(SpotWeldLabelRevision.run_id == run.id).delete(synchronize_session=False)
        db.query(SpotWeldQualitySample).filter(SpotWeldQualitySample.run_id == run.id).delete(synchronize_session=False)
        db.query(SpotWeldQualityRuleSet).filter(SpotWeldQualityRuleSet.run_id == run.id).delete(synchronize_session=False)
        db.delete(run)
    return {"deleted": 1, "run_id": str(run.id)}


@router.get("/runs/{run_id}/annotations/export")
def export_annotations(
    project_id: uuid.UUID,
    run_id: str,
    request: Request,
    format: str = Query(default="xlsx"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    require_project_access(db, project_id, current_user.id, "project.read")
    run = _run_or_404(db, project_id, run_id)
    try:
        content = build_annotation_export(
            run,
            db,
            format,
            artifact_service=get_quality_artifact_service(request, db),
        )
    except QualityPipelineError as error:
        _quality_error(error)
    media_type = {
        "csv": "text/csv",
        "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    }[format]
    return StreamingResponse(
        io.BytesIO(content),
        media_type=media_type,
        headers={
            "Content-Disposition": f'attachment; filename="spot-weld-annotations-{run.id}.{format}"',
        },
    )


@router.post("/runs/{run_id}/save-labeled-dataset", status_code=201)
def save_labeled_dataset_artifact(
    project_id: uuid.UUID,
    run_id: str,
    data: SaveLabeledDatasetRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Save confirmed labels as a new project dataset with a trailing ``label`` column."""
    access = require_project_access(db, project_id, current_user.id, "quality.label")
    run = _run_or_404(db, project_id, run_id)
    try:
        with audit_service(db).project_action(
            db,
            request=request,
            actor=current_user,
            access=access,
            permission="quality.label",
            intent=AuditIntent(
                project_id=project_id,
                action="spot_weld_quality.labeled_dataset.save",
                resource_type="dataset",
                changes={
                    "run_id": str(run.id),
                    "source_dataset_artifact_id": str(run.dataset_artifact_id),
                    "label_source": data.label_source,
                },
            ),
            allowed_changes={"run_id", "source_dataset_artifact_id", "label_source"},
        ):
            artifact = save_labeled_dataset(
                db,
                run,
                artifact_service=get_quality_artifact_service(request, db),
                label_source=data.label_source,
            )
    except QualityPipelineError as error:
        _quality_error(error, status=409)
    metadata = artifact.metadata_ or {}
    return {
        "id": str(artifact.id),
        "artifact_id": str(artifact.id),
        "project_id": str(artifact.project_id),
        "name": artifact.name,
        "filename": artifact.name,
        "format": artifact.format,
        "row_count": metadata.get("row_count", 0),
        "schema": metadata.get("schema", []),
        "source_dataset_artifact_id": str(run.dataset_artifact_id),
        "quality_run_id": str(run.id),
    }


@router.get("/runs/{run_id}/samples")
def list_samples(
    project_id: uuid.UUID,
    run_id: str,
    review_status: str | None = Query(default=None),
    warning_level: str | None = Query(default=None),
    label: str | None = Query(default=None),
    q: str | None = Query(default=None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    require_project_access(db, project_id, current_user.id, "project.read")
    run = _run_or_404(db, project_id, run_id)
    query = db.query(SpotWeldQualitySample).filter(SpotWeldQualitySample.run_id == run.id)
    if review_status:
        query = query.filter(SpotWeldQualitySample.review_status == review_status)
    if warning_level:
        query = query.filter(SpotWeldQualitySample.warning_level == warning_level)
    if label:
        query = query.filter(SpotWeldQualitySample.current_label == label)
    if q:
        query = query.filter(SpotWeldQualitySample.display_id.contains(q))
    samples = query.options(load_only(
        SpotWeldQualitySample.id,
        SpotWeldQualitySample.display_id,
        SpotWeldQualitySample.source_row_index,
        SpotWeldQualitySample.automatic_label,
        SpotWeldQualitySample.current_label,
        SpotWeldQualitySample.review_status,
        SpotWeldQualitySample.warning_level,
        SpotWeldQualitySample.defect_probability,
        SpotWeldQualitySample.cluster_id,
    )).order_by(SpotWeldQualitySample.source_row_index).all()
    return {
        "items": [
            {
                "id": str(sample.id),
                "display_id": sample.display_id,
                "source_row_index": sample.source_row_index,
                "automatic_label": sample.automatic_label,
                "current_label": sample.current_label,
                "review_status": sample.review_status,
                "warning_level": sample.warning_level,
                "defect_probability": sample.defect_probability,
                "cluster_id": sample.cluster_id,
            }
            for sample in samples
        ],
        "total": len(samples),
    }


@router.get("/runs/{run_id}/samples/{sample_id}")
def get_sample(
    project_id: uuid.UUID,
    run_id: str,
    sample_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    require_project_access(db, project_id, current_user.id, "project.read")
    return _serialize_sample(_sample_or_404(db, _run_or_404(db, project_id, run_id), sample_id), include_waveforms=True)


def _allowed_labels_for_run(run: SpotWeldQualityRun) -> frozenset[str]:
    input_fingerprint = run.input_fingerprint or {}
    if input_fingerprint.get("label_mode", "automatic") != "manual":
        return VALID_LABELS
    target_schema = (
        (run.statistics or {}).get("target_schema")
        or input_fingerprint.get("target_schema")
        or {}
    )
    classes = target_schema.get("classes") if isinstance(target_schema, dict) else None
    allowed = frozenset(str(value) for value in (classes or []) if str(value).strip())
    return allowed or VALID_LABELS


def _manual_target_schema(run: SpotWeldQualityRun) -> dict:
    input_fingerprint = run.input_fingerprint or {}
    statistics = run.statistics or {}
    target_schema = statistics.get("target_schema") or input_fingerprint.get("target_schema") or {}
    return dict(target_schema) if isinstance(target_schema, dict) else {}


@router.post("/runs/{run_id}/samples/{sample_id}/labels", status_code=201)
def submit_label(
    project_id: uuid.UUID,
    run_id: str,
    sample_id: str,
    data: LabelRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    access = require_project_access(db, project_id, current_user.id, "quality.label")
    run = _run_or_404(db, project_id, run_id)
    target_schema = _manual_target_schema(run)
    label_mode = (run.input_fingerprint or {}).get("label_mode", "automatic")
    try:
        normalized_label = normalize_annotation_label(data.label, target_schema) if label_mode == "manual" else str(data.label).strip()
    except QualityPipelineError as error:
        raise HTTPException(422, detail={"code": error.code}) from error
    allowed_labels = _allowed_labels_for_run(run)
    if label_mode != "manual" and normalized_label not in allowed_labels:
        raise HTTPException(422, detail={"code": "QUALITY_LABEL_INVALID"})
    if label_mode == "manual":
        classes = [str(value) for value in target_schema.get("classes") or []]
        if normalized_label not in classes:
            classes.append(normalized_label)
            target_schema = {
                **target_schema,
                "classes": classes,
                "class_count": len(classes),
            }
    sample = _sample_or_404(db, run, sample_id)
    revision = SpotWeldLabelRevision(
        project_id=project_id, run_id=run.id, sample_id=sample.id, author_id=current_user.id,
        label=normalized_label, note=data.note, action="submitted", parent_revision_id=sample.current_revision_id,
    )
    with audit_service(db).project_action(
        db, request=request, actor=current_user, access=access, permission="quality.label",
        intent=AuditIntent(project_id=project_id, action="spot_weld_quality.label.submit", resource_type="spot_weld_quality_sample", resource_id=str(sample.id), changes={"label": normalized_label}),
        allowed_changes={"label"},
    ):
        db.add(revision); db.flush()
        sample.current_label = normalized_label
        sample.current_note = data.note
        sample.review_status = "submitted"
        sample.current_revision_id = revision.id
        db.flush()
        statistics = dict(run.statistics or {})
        stored_progress = dict(statistics.get("annotation_progress") or {})
        label_mode = (run.input_fingerprint or {}).get("label_mode", "automatic")
        total_count = int(stored_progress.get("total_count") or db.query(
            SpotWeldQualitySample.id,
        ).filter(SpotWeldQualitySample.run_id == run.id).count())
        annotation_column = (
            SpotWeldQualitySample.automatic_label
            if label_mode == "automatic"
            else SpotWeldQualitySample.current_label
        )
        annotated_count = db.query(SpotWeldQualitySample.id).filter(
            SpotWeldQualitySample.run_id == run.id,
            annotation_column.isnot(None),
        ).count()
        run.statistics = {
            **statistics,
            **({"target_schema": target_schema} if label_mode == "manual" else {}),
            "annotation_progress": _annotation_progress(annotated_count, total_count),
        }
        if label_mode == "manual":
            run.status = "completed" if total_count and annotated_count >= total_count else "running"
        if label_mode == "manual":
            run.input_fingerprint = {
                **(run.input_fingerprint or {}),
                "target_schema": target_schema,
            }
    return _serialize_sample(sample)


@router.delete("/runs/{run_id}/samples/{sample_id}/labels")
def delete_label(
    project_id: uuid.UUID,
    run_id: str,
    sample_id: str,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    access = require_project_access(db, project_id, current_user.id, "quality.label")
    run = _run_or_404(db, project_id, run_id)
    sample = _sample_or_404(db, run, sample_id)
    with audit_service(db).project_action(
        db,
        request=request,
        actor=current_user,
        access=access,
        permission="quality.label",
        intent=AuditIntent(
            project_id=project_id,
            action="spot_weld_quality.label.delete",
            resource_type="spot_weld_quality_sample",
            resource_id=str(sample.id),
            changes={"label": None},
        ),
        allowed_changes={"label"},
    ):
        sample.current_label = None
        sample.current_note = None
        sample.current_revision_id = None
        sample.review_status = "pending_review"
        db.flush()
        statistics = dict(run.statistics or {})
        total_count = int(
            (statistics.get("annotation_progress") or {}).get("total_count")
            or statistics.get("row_count")
            or db.query(SpotWeldQualitySample.id).filter(
                SpotWeldQualitySample.run_id == run.id,
            ).count()
        )
        annotated_count = db.query(SpotWeldQualitySample.id).filter(
            SpotWeldQualitySample.run_id == run.id,
            SpotWeldQualitySample.current_label.isnot(None),
        ).count()
        run.statistics = {
            **statistics,
            "annotation_progress": _annotation_progress(annotated_count, total_count),
        }
        if (run.input_fingerprint or {}).get("label_mode", "automatic") == "manual":
            run.status = "completed" if total_count and annotated_count >= total_count else "running"
    return _serialize_sample(sample)


@router.post("/runs/{run_id}/submit-review")
def submit_run_for_review(
    project_id: uuid.UUID,
    run_id: str,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Submit every currently labeled sample in one run for review."""
    access = require_project_access(db, project_id, current_user.id, "quality.label")
    run = _run_or_404(db, project_id, run_id)
    samples = db.query(SpotWeldQualitySample).filter(
        SpotWeldQualitySample.run_id == run.id,
        SpotWeldQualitySample.current_label.isnot(None),
    ).all()
    submitted_count = 0
    with audit_service(db).project_action(
        db,
        request=request,
        actor=current_user,
        access=access,
        permission="quality.label",
        intent=AuditIntent(
            project_id=project_id,
            action="spot_weld_quality.run.submit_review",
            resource_type="spot_weld_quality_run",
            resource_id=str(run.id),
            changes={"submitted_count": len(samples)},
        ),
        allowed_changes={"submitted_count"},
    ):
        for sample in samples:
            if sample.review_status != "submitted":
                sample.review_status = "submitted"
                submitted_count += 1
    return {"run_id": str(run.id), "submitted_count": submitted_count, "labeled_count": len(samples)}


@router.post("/runs/{run_id}/samples/{sample_id}/review")
def review_label(
    project_id: uuid.UUID,
    run_id: str,
    sample_id: str,
    data: ReviewRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if data.decision not in {"approved", "returned"}:
        raise HTTPException(422, detail={"code": "QUALITY_REVIEW_DECISION_INVALID"})
    access = require_project_access(db, project_id, current_user.id, "quality.review")
    run = _run_or_404(db, project_id, run_id)
    sample = _sample_or_404(db, run, sample_id)
    if not sample.current_label:
        raise HTTPException(409, detail={"code": "QUALITY_LABEL_NOT_SUBMITTED"})
    revision = SpotWeldLabelRevision(
        project_id=project_id, run_id=run.id, sample_id=sample.id, author_id=current_user.id,
        label=sample.current_label, note=sample.current_note, action="reviewed", decision=data.decision,
        review_comment=data.comment, parent_revision_id=sample.current_revision_id,
    )
    with audit_service(db).project_action(
        db, request=request, actor=current_user, access=access, permission="quality.review",
        intent=AuditIntent(project_id=project_id, action="spot_weld_quality.label.review", resource_type="spot_weld_quality_sample", resource_id=str(sample.id), changes={"decision": data.decision}),
        allowed_changes={"decision"},
    ):
        db.add(revision); db.flush()
        sample.review_status = data.decision
        sample.current_revision_id = revision.id
    return _serialize_sample(sample)


@router.post("/runs/{run_id}/label-snapshots", status_code=201)
def create_snapshot(
    project_id: uuid.UUID,
    run_id: str,
    data: SnapshotRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    access = require_project_access(db, project_id, current_user.id, "quality.review")
    run = _run_or_404(db, project_id, run_id)
    if data.label_source == "automatic":
        if run.status != "completed":
            _quality_error(QualityPipelineError("QUALITY_AUTOMATIC_LABELS_UNAVAILABLE"))
        samples = db.query(SpotWeldQualitySample).filter(
            SpotWeldQualitySample.run_id == run.id,
            SpotWeldQualitySample.automatic_label.in_(VALID_LABELS),
        ).order_by(SpotWeldQualitySample.source_row_index).all()
        if not samples:
            _quality_error(QualityPipelineError("QUALITY_AUTOMATIC_LABELS_UNAVAILABLE"))
        labels = [
            {"sample_id": str(sample.id), "label": sample.automatic_label, "revision_id": None, "source": "automatic"}
            for sample in samples
        ]
    else:
        samples = db.query(SpotWeldQualitySample).filter(
            SpotWeldQualitySample.run_id == run.id,
            SpotWeldQualitySample.review_status == "approved",
            SpotWeldQualitySample.current_label.isnot(None),
        ).order_by(SpotWeldQualitySample.source_row_index).all()
        labels = [
            {
                "sample_id": str(sample.id),
                "label": sample.current_label,
                "revision_id": str(sample.current_revision_id) if sample.current_revision_id else None,
                "source": "approved",
            }
            for sample in samples
        ]
    snapshot = SpotWeldLabelSnapshot(
        id=uuid.uuid4(), project_id=project_id, run_id=run.id, created_by_id=current_user.id, name=data.name,
        labels=labels, label_counts=dict(Counter(item["label"] for item in labels)),
    )
    with audit_service(db).project_action(
        db, request=request, actor=current_user, access=access, permission="quality.review",
        intent=AuditIntent(project_id=project_id, action="spot_weld_quality.snapshot.create", resource_type="spot_weld_label_snapshot", resource_id=str(snapshot.id), changes={"name": data.name, "label_source": data.label_source, "sample_count": len(labels)}),
        allowed_changes={"name", "label_source", "sample_count"},
    ):
        db.add(snapshot)
    return {"id": str(snapshot.id), "name": snapshot.name, "label_source": data.label_source, "label_counts": snapshot.label_counts, "sample_count": len(labels)}


@router.get("/runs/{run_id}/label-snapshots")
def list_snapshots(
    project_id: uuid.UUID,
    run_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    require_project_access(db, project_id, current_user.id, "project.read")
    run = _run_or_404(db, project_id, run_id)
    snapshots = db.query(SpotWeldLabelSnapshot).filter(SpotWeldLabelSnapshot.run_id == run.id).order_by(SpotWeldLabelSnapshot.created_at.desc()).all()
    return {"items": [{"id": str(item.id), "name": item.name, "label_source": next((label.get("source", "approved") for label in (item.labels or [])), "approved"), "label_counts": item.label_counts, "sample_count": len(item.labels or []), "created_at": item.created_at.isoformat() if item.created_at else None} for item in snapshots], "total": len(snapshots)}


@router.post("/runs/{run_id}/label-snapshots/{snapshot_id}/train")
def train_snapshot(
    project_id: uuid.UUID,
    run_id: str,
    snapshot_id: str,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Train only from a frozen, editor-approved label snapshot."""
    access = require_project_access(db, project_id, current_user.id, "quality.review")
    run = _run_or_404(db, project_id, run_id)
    snapshot = _snapshot_or_404(db, project_id, run, snapshot_id)
    try:
        with audit_service(db).project_action(
            db,
            request=request,
            actor=current_user,
            access=access,
            permission="quality.review",
            intent=AuditIntent(
                project_id=project_id,
                action="spot_weld_quality.snapshot.train",
                resource_type="spot_weld_label_snapshot",
                resource_id=str(snapshot.id),
                changes={"snapshot_id": str(snapshot.id), "feature_version": "report_v1"},
            ),
            allowed_changes={"snapshot_id", "feature_version"},
        ):
            outcome = train_label_snapshot(
                db,
                snapshot.id,
                artifact_service=get_quality_artifact_service(request, db),
                commit=False,
            )
    except QualityPipelineError as error:
        _quality_error(error, status=409)
    return {
        "snapshot_id": outcome.snapshot_id,
        "run_id": outcome.run_id,
        "model": _serialize_quality_model(outcome.model_library),
        "output_artifacts": outcome.output_artifacts,
    }


@router.get("/runs/{run_id}/quality-model")
def get_quality_model(
    project_id: uuid.UUID,
    run_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    require_project_access(db, project_id, current_user.id, "project.read")
    run = _run_or_404(db, project_id, run_id)
    model_id = (run.statistics or {}).get("model_library_id")
    try:
        identifier = uuid.UUID(str(model_id))
    except (TypeError, ValueError):
        raise HTTPException(404, detail={"code": "QUALITY_MODEL_NOT_FOUND"})
    model = db.query(ModelLibrary).filter(
        ModelLibrary.id == identifier,
        ModelLibrary.project_id == project_id,
        ModelLibrary.params["source"].as_string() == "spot_weld_quality",
    ).first()
    if model is None:
        raise HTTPException(404, detail={"code": "QUALITY_MODEL_NOT_FOUND"})
    return _serialize_quality_model(model)


@router.get("/runs/{run_id}/artifacts/{artifact_key}/download")
def download_quality_artifact(
    project_id: uuid.UUID,
    run_id: str,
    artifact_key: str,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    require_project_access(db, project_id, current_user.id, "project.read")
    run = _run_or_404(db, project_id, run_id)
    expected_type = QUALITY_OUTPUT_ARTIFACT_TYPES.get(artifact_key)
    artifact_id = (run.output_artifacts or {}).get(artifact_key)
    if expected_type is None or artifact_id is None:
        raise HTTPException(404, detail={"code": "QUALITY_OUTPUT_ARTIFACT_NOT_FOUND"})
    artifact_service = get_quality_artifact_service(request, db)
    try:
        artifact = artifact_service.resolve(artifact_id, project_id, expected_type=expected_type)
        with artifact_service.materialize(artifact.id, project_id, expected_type=expected_type) as path:
            content = Path(path).read_bytes()
    except (ArtifactAccessError, OSError, ValueError):
        raise HTTPException(404, detail={"code": "QUALITY_OUTPUT_ARTIFACT_NOT_FOUND"})
    media_type = {
        "quality_report": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "quality_schema": "application/json",
        "model": "application/octet-stream",
        "quality_report_chart": "image/png",
    }[expected_type]
    return StreamingResponse(
        io.BytesIO(content),
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{Path(artifact.name).name}"'},
    )


@router.get("/warnings")
def warning_summary(
    project_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    require_project_access(db, project_id, current_user.id, "project.read")
    rows = db.query(SpotWeldQualitySample, SpotWeldQualityRun).join(
        SpotWeldQualityRun, SpotWeldQualitySample.run_id == SpotWeldQualityRun.id,
    ).filter(SpotWeldQualityRun.project_id == project_id).all()
    counts = Counter(sample.warning_level for sample, _ in rows)
    priority = {"critical": 0, "warning": 1, "notice": 2, "none": 3}
    items = [
        {"run_id": str(run.id), **_serialize_sample(sample)}
        for sample, run in rows
        if sample.warning_level != "none"
    ]
    items.sort(key=lambda item: (
        priority.get(str(item.get("warning_level")), 4),
        -(float(item.get("defect_probability") or 0)),
        str(item.get("display_id") or ""),
    ))
    return {
        "counts": {level: counts.get(level, 0) for level in ("critical", "warning", "notice", "none")},
        "items": items,
    }
