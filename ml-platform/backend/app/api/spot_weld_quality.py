"""Project-scoped APIs for report-compatible spot-weld quality perception."""

from __future__ import annotations

import io
import uuid
from collections import Counter
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.auth import get_current_user
from app.api.project_security import audit_service, require_project_access
from app.config import settings
from app.database import get_db
from app.models.model_library import ModelLibrary
from app.models.spot_weld_quality import (
    SpotWeldLabelRevision,
    SpotWeldLabelSnapshot,
    SpotWeldQualityRun,
    SpotWeldQualitySample,
)
from app.models.user import User
from app.services.artifact_service import ArtifactAccessError, build_artifact_service
from app.services.audit import AuditIntent
from app.services.spot_weld_features import QualityPipelineError
from app.services.spot_weld_quality import (
    create_demo_quality_dataset,
    create_quality_run_record,
    resolve_dataset_frame,
    select_automl_configs,
    train_label_snapshot,
    validate_report_frame,
)


router = APIRouter(prefix="/api/projects/{project_id}/spot-weld", tags=["spot-weld-quality"])
VALID_LABELS = frozenset({
    "normal", "strong_splatter", "weak_splatter", "power_fluctuation", "spot_too_small",
    "spot_too_large", "energy_anomaly", "current_jump", "anomaly_cluster",
})
QUALITY_OUTPUT_ARTIFACT_TYPES = {
    "model": "model",
    "schema": "quality_schema",
    "report": "quality_report",
}


class DatasetQualityRequest(BaseModel):
    dataset_artifact_id: uuid.UUID
    field_mapping: dict[str, str] = Field(default_factory=dict)
    candidate_ids: list[str] = Field(default_factory=list)


class LabelRequest(BaseModel):
    label: str
    note: str = ""


class ReviewRequest(BaseModel):
    decision: str
    comment: str = ""


class SnapshotRequest(BaseModel):
    name: str = "approved-labels"
    label_source: Literal["approved", "automatic"] = "approved"


class DemoDatasetRequest(BaseModel):
    row_count: int = Field(default=60, ge=12, le=5000)


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


def _serialize_run(run: SpotWeldQualityRun, *, include_results: bool = True) -> dict:
    payload = {
        "id": str(run.id),
        "project_id": str(run.project_id),
        "dataset_artifact_id": str(run.dataset_artifact_id),
        "status": run.status,
        "task_id": run.task_id,
        "worker_id": run.worker_id,
        "sample_count": len(run.samples),
        "feature_version": (run.statistics or {}).get("feature_version", "report_v1"),
        "rule_set_version": run.rule_set_version,
        "selected_candidate_ids": list((run.input_fingerprint or {}).get("selected_candidate_ids") or []),
        "statistics": run.statistics or {},
        "error_code": run.error_code,
        "error_details": run.error_details or {},
        "created_at": run.created_at.isoformat() if run.created_at else None,
        "updated_at": run.updated_at.isoformat() if run.updated_at else None,
    }
    if include_results:
        payload.update({
            "field_mapping": run.field_mapping or {},
            "feature_schema": run.feature_schema or [],
            "automl_results": run.automl_results or [],
            "clustering_results": run.clustering_results or {},
            "output_artifacts": run.output_artifacts or {},
        })
    return payload


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


def _serialize_quality_model(model: ModelLibrary) -> dict:
    return {
        "id": str(model.id),
        "name": model.name,
        "version": model.version,
        "status": model.status,
        "framework": model.framework,
        "backbone": model.backbone,
        "metrics": model.metrics or {},
        "params": model.params or {},
        "model_artifact_id": str(model.model_artifact_id) if model.model_artifact_id else None,
        "format": model.format,
        "tags": model.tags or [],
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
        select_automl_configs(data.candidate_ids)
        _, frame = resolve_dataset_frame(
            db,
            get_quality_artifact_service(request, db),
            project_id,
            data.dataset_artifact_id,
        )
    except QualityPipelineError as error:
        _quality_error(error)
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
        select_automl_configs(data.candidate_ids)
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
                changes={"dataset_artifact_id": str(data.dataset_artifact_id), "feature_version": "report_v1", "candidate_ids": data.candidate_ids},
            ),
            allowed_changes={"dataset_artifact_id", "feature_version", "candidate_ids"},
        ):
            run = create_quality_run_record(
                db,
                project_id=project_id,
                user_id=current_user.id,
                dataset_artifact_id=data.dataset_artifact_id,
                field_mapping=data.field_mapping,
                candidate_ids=data.candidate_ids,
                artifact_service=get_quality_artifact_service(request, db),
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
    return {"items": [_serialize_run(run, include_results=False) for run in runs], "total": len(runs)}


@router.get("/models")
def list_quality_models(
    project_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List only platform-generated quality models within one readable project."""
    require_project_access(db, project_id, current_user.id, "project.read")
    models = db.query(ModelLibrary).filter(
        ModelLibrary.project_id == project_id,
    ).order_by(ModelLibrary.created_at.desc(), ModelLibrary.id.desc()).all()
    items = [
        _serialize_quality_model(model)
        for model in models
        if (model.params or {}).get("source") == "spot_weld_quality"
    ]
    return {"items": items, "total": len(items)}


@router.get("/runs/{run_id}")
def get_run(
    project_id: uuid.UUID,
    run_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    require_project_access(db, project_id, current_user.id, "project.read")
    return _serialize_run(_run_or_404(db, project_id, run_id))


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
    samples = query.order_by(SpotWeldQualitySample.source_row_index).all()
    return {"items": [_serialize_sample(sample) for sample in samples], "total": len(samples)}


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
    if data.label not in VALID_LABELS:
        raise HTTPException(422, detail={"code": "QUALITY_LABEL_INVALID"})
    access = require_project_access(db, project_id, current_user.id, "quality.label")
    run = _run_or_404(db, project_id, run_id)
    sample = _sample_or_404(db, run, sample_id)
    revision = SpotWeldLabelRevision(
        project_id=project_id, run_id=run.id, sample_id=sample.id, author_id=current_user.id,
        label=data.label, note=data.note, action="submitted", parent_revision_id=sample.current_revision_id,
    )
    with audit_service(db).project_action(
        db, request=request, actor=current_user, access=access, permission="quality.label",
        intent=AuditIntent(project_id=project_id, action="spot_weld_quality.label.submit", resource_type="spot_weld_quality_sample", resource_id=str(sample.id), changes={"label": data.label}),
        allowed_changes={"label"},
    ):
        db.add(revision); db.flush()
        sample.current_label = data.label
        sample.current_note = data.note
        sample.review_status = "submitted"
        sample.current_revision_id = revision.id
    return _serialize_sample(sample)


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
        "report": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "schema": "application/json",
        "model": "application/octet-stream",
    }[artifact_key]
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
