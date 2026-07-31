"""Project-authorized asynchronous training management API."""

import tempfile
import uuid
from pathlib import Path

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.api.auth import get_current_user
from app.api.experiments import get_experiment_tracking
from app.config import settings
from app.database import get_db
from app.models.experiment import Experiment
from app.models.project import Project
from app.models.training import TERMINAL_TRAINING_STATUSES, TrainingJob
from app.models.user import User
from app.services.automl_execution import resolve_candidates
from app.services.artifact_service import ArtifactAccessError, build_artifact_service
from app.services.experiment_tracking import TrackingError
from app.services.iterative_training import IncompatibleCheckpoint, TrainingCheckpoint, TrainingConfig
from app.tensorboard_gateway.tokens import SessionSigner, SessionTokenInvalid
from app.api.project_security import audit_service, require_project_access, resolve_project_access
from app.services.audit import AuditIntent
from app.services.project_access import ProjectAccessService


router = APIRouter(prefix="/api/training", tags=["training"])
PROJECT_WRITE_ACTIONS = {
    "POST /api/training/run": "training_job.start",
    "POST /api/training/jobs/{job_id}/stop": "training_job.stop",
    "POST /api/training/jobs/{job_id}/resume": "training_job.resume",
    "POST /api/training/automl/run": "training_job.automl_start",
    "POST /api/training/batch-delete": "training_job.delete",
}


class TrainingRunRequest(BaseModel):
    project_id: uuid.UUID
    experiment_id: uuid.UUID
    dataset_artifact_id: uuid.UUID
    name: str = Field(default="training-job", min_length=1, max_length=128)
    target_column: str = Field(min_length=1)
    task: str = "auto"
    total_epochs: int = Field(default=20, ge=1, le=10000)
    monitor: str | None = None
    mode: str = "max"
    patience: int = Field(default=5, ge=1)
    min_delta: float = Field(default=0.0, ge=0)
    restore_best: bool = True
    checkpoint_interval: int | None = Field(default=None, ge=1)


class ResumeRequest(BaseModel):
    checkpoint_uri: str | None = None
    checkpoint_path: str | None = None
    total_epochs: int | None = Field(default=None, ge=1, le=10000)


class AutoMLRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: uuid.UUID
    experiment_id: uuid.UUID
    dataset_artifact_id: uuid.UUID
    target_column: str = Field(min_length=1)
    task: str = "classification"
    candidate_ids: list[str] = Field(default_factory=list)
    time_budget: int = Field(default=60, ge=10, le=3600)
    name: str = Field(default="automl-job", min_length=1, max_length=128)


class BatchDeleteRequest(BaseModel):
    ids: list[str]


class CeleryTrainingDispatcher:
    def __init__(self, task):
        self.task = task

    def enqueue(self, job_id) -> str:
        return self.task.delay(str(job_id)).id

    def cancel(self, task_id: str) -> None:
        from celery.result import AsyncResult

        AsyncResult(task_id, app=self.task.app).revoke(terminate=False)


def get_training_dispatcher(request: Request):
    configured = getattr(request.app.state, "training_dispatcher", None)
    if configured is not None:
        return configured
    app_settings = getattr(request.app.state, "settings", None) or settings
    if app_settings.task_backend == "celery":
        from app.tasks.training_tasks import execute_training_task

        configured = CeleryTrainingDispatcher(execute_training_task)
    else:
        from app.tasks.training_tasks import LocalTrainingDispatcher, execute_local_training_task

        configured = LocalTrainingDispatcher(execute_local_training_task)
    request.app.state.training_dispatcher = configured
    return configured


def get_automl_dispatcher(request: Request):
    configured = getattr(request.app.state, "automl_dispatcher", None)
    if configured is not None:
        return configured
    app_settings = getattr(request.app.state, "settings", None) or settings
    if app_settings.task_backend == "celery":
        from app.tasks.training_tasks import execute_automl_task

        configured = CeleryTrainingDispatcher(execute_automl_task)
    else:
        from app.tasks.training_tasks import LocalTrainingDispatcher, execute_local_automl_task

        configured = LocalTrainingDispatcher(execute_local_automl_task)
    request.app.state.automl_dispatcher = configured
    return configured


def get_artifact_service(request: Request, db: Session):
    factory = getattr(request.app.state, "artifact_service_factory", None)
    return factory(db) if factory is not None else build_artifact_service(db)


def get_tensorboard_signer(request: Request):
    configured = getattr(request.app.state, "tensorboard_signer", None)
    if configured is not None:
        return configured
    from app.config import settings

    secret = settings.resolved_tensorboard_session_secret
    if secret is None:
        raise HTTPException(503, _error(
            "TENSORBOARD_UNAVAILABLE",
            "TensorBoard sessions are not configured",
        ))
    configured = SessionSigner(secret.get_secret_value())
    request.app.state.tensorboard_signer = configured
    return configured


@router.post("/run", status_code=202)
def start_training(
    data: TrainingRunRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    experiment, access = _visible_experiment(
        db,
        data.experiment_id,
        data.project_id,
        current_user.id,
    )
    if experiment is None:
        raise HTTPException(404, _error("EXPERIMENT_NOT_FOUND", "Experiment not found"))
    job_id = uuid.uuid4()
    with audit_service(db).project_action(
        db, request=request, actor=current_user, access=access,
        permission="execution.operate",
        intent=AuditIntent(
            project_id=data.project_id, action="training_job.start",
            resource_type="training_job", resource_id=str(job_id),
            changes={"name": data.name, "task": data.task, "total_epochs": data.total_epochs},
        ),
        allowed_changes={"name", "task", "total_epochs"},
    ):
        artifact_service = get_artifact_service(request, db)
        try:
            dataset = artifact_service.resolve(
                data.dataset_artifact_id, data.project_id, expected_type="dataset",
            )
        except (ValueError, ArtifactAccessError) as error:
            raise HTTPException(400, _error("DATASET_ARTIFACT_INVALID", str(error))) from error

        monitor = data.monitor or (
            "val_r2" if data.task == "regression" else "val_accuracy"
        )
        try:
            TrainingConfig(
                task=data.task, total_epochs=data.total_epochs, monitor=monitor,
                mode=data.mode, patience=data.patience, min_delta=data.min_delta,
                restore_best=data.restore_best,
                checkpoint_interval=data.checkpoint_interval or 5,
            )
        except ValueError as error:
            raise HTTPException(400, _error("TRAINING_CONFIG_INVALID", str(error))) from error

        params = {"target_column": data.target_column, "task": data.task}
        if data.checkpoint_interval is not None:
            params["checkpoint_interval"] = data.checkpoint_interval
        job = TrainingJob(
            id=job_id, project_id=data.project_id, user_id=current_user.id,
            experiment_id=experiment.id, name=data.name, operator_id="incremental_sgd",
            params=params, dataset_artifact_id=dataset.id,
            dataset_path=artifact_service.storage_reference(dataset), status="pending",
            total_epochs=data.total_epochs, monitor_name=monitor, monitor_mode=data.mode,
            early_stopping_patience=data.patience,
            early_stopping_min_delta=data.min_delta, restore_best=data.restore_best,
        )
        db.add(job)
    db.refresh(job)
    _dispatch_job(
        db, job, get_training_dispatcher(request), request, current_user, access,
    )
    return {"job_id": str(job.id), "status": "queued", "task_id": job.task_id}


@router.get("/jobs")
def list_training_jobs(
    project_id: uuid.UUID | None = Query(default=None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if project_id is not None:
        require_project_access(db, project_id, current_user.id, "project.read")
        query = db.query(TrainingJob).filter(TrainingJob.project_id == project_id)
    else:
        project_ids = [
            project.id for project in ProjectAccessService()
            .accessible_project_query(db, current_user.id).all()
        ]
        query = db.query(TrainingJob).filter(TrainingJob.project_id.in_(project_ids))
    return [_job_to_dict(job) for job in query.order_by(TrainingJob.created_at.desc()).all()]


@router.get("/jobs/{job_id}")
def get_training_job(
    job_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    job, _ = _visible_job(db, job_id, current_user.id)
    if job is None:
        raise HTTPException(404, _error("TRAINING_JOB_NOT_FOUND", "Training job not found"))
    return _job_to_dict(job)


@router.get("/jobs/{job_id}/checkpoints")
def list_checkpoints(
    job_id: uuid.UUID,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    job, _ = _visible_job(db, job_id, current_user.id)
    if job is None:
        raise HTTPException(404, _error("TRAINING_JOB_NOT_FOUND", "Training job not found"))
    if not job.mlflow_run_id:
        return {"job_id": str(job.id), "checkpoints": []}
    tracking = get_experiment_tracking(request)
    try:
        artifacts = tracking.list_artifacts(job.mlflow_run_id, "checkpoints")
    except TrackingError as error:
        raise HTTPException(503, _error("TRACKING_UNAVAILABLE", str(error))) from error
    return {
        "job_id": str(job.id),
        "checkpoints": [
            {
                "path": item.path,
                "is_dir": item.is_dir,
                "file_size": item.file_size,
                "uri": _run_artifact_uri(job, item.path),
            }
            for item in artifacts
        ],
    }


@router.post("/jobs/{job_id}/stop")
def stop_training_job(
    job_id: uuid.UUID,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    job, access = _visible_job(db, job_id, current_user.id)
    if job is None:
        raise HTTPException(404, _error("TRAINING_JOB_NOT_FOUND", "Training job not found"))
    with audit_service(db).project_action(
        db, request=request, actor=current_user, access=access,
        permission="execution.operate",
        intent=AuditIntent(
            project_id=job.project_id, action="training_job.stop",
            resource_type="training_job", resource_id=str(job.id),
            changes={"previous_status": job.status},
        ),
        allowed_changes={"previous_status"},
    ):
        if job.status not in {"pending", "queued", "running"}:
            raise HTTPException(409, _error("TRAINING_NOT_ACTIVE", "Training job is not active"))
        job.status = "cancel_requested"
    if job.task_id:
        get_training_dispatcher(request).cancel(job.task_id)
    return {"job_id": str(job.id), "status": "cancel_requested"}


@router.post("/jobs/{job_id}/resume", status_code=202)
def resume_training_job(
    job_id: uuid.UUID,
    data: ResumeRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    source, access = _visible_job(db, job_id, current_user.id)
    if source is None:
        raise HTTPException(404, _error("TRAINING_JOB_NOT_FOUND", "Training job not found"))
    resumed_id = uuid.uuid4()
    with audit_service(db).project_action(
        db, request=request, actor=current_user, access=access,
        permission="execution.operate",
        intent=AuditIntent(
            project_id=source.project_id, action="training_job.resume",
            resource_type="training_job", resource_id=str(resumed_id),
            changes={"source_job_id": str(source.id), "total_epochs": data.total_epochs},
        ),
        allowed_changes={"source_job_id", "total_epochs"},
    ):
        checkpoint_uri = data.checkpoint_uri or source.latest_checkpoint_uri
        if not checkpoint_uri or not source.mlflow_run_id:
            raise HTTPException(409, _error("CHECKPOINT_NOT_FOUND", "Checkpoint not found"))
        checkpoint_path = (
            _checkpoint_path(data.checkpoint_path)
            if data.checkpoint_path else _checkpoint_path(checkpoint_uri)
        )
        tracking = get_experiment_tracking(request)
        try:
            available = {
                item.path for item in tracking.list_artifacts(source.mlflow_run_id, "checkpoints")
                if not item.is_dir
            }
            if checkpoint_path not in available:
                raise HTTPException(404, _error("CHECKPOINT_NOT_FOUND", "Checkpoint not found"))
            with tempfile.TemporaryDirectory() as temporary:
                downloaded = tracking.download_artifact(
                    source.mlflow_run_id, checkpoint_path, temporary,
                )
                checkpoint = TrainingCheckpoint.loads(Path(downloaded).read_bytes())
        except HTTPException:
            raise
        except IncompatibleCheckpoint as error:
            raise HTTPException(400, _error("CHECKPOINT_INCOMPATIBLE", str(error))) from error
        except (TrackingError, KeyError) as error:
            raise HTTPException(503, _error("TRACKING_UNAVAILABLE", str(error))) from error

        if (
            checkpoint.dataset_artifact_id != str(source.dataset_artifact_id)
            or checkpoint.source_job_id != str(source.id)
        ):
            raise HTTPException(400, _error(
                "CHECKPOINT_INCOMPATIBLE", "Checkpoint lineage does not match the training job",
            ))
        total_epochs = data.total_epochs or source.total_epochs or checkpoint.epoch + 1
        if total_epochs <= checkpoint.epoch:
            raise HTTPException(400, _error(
                "CHECKPOINT_INCOMPATIBLE", "Total epochs must exceed the checkpoint epoch",
            ))

        resumed = TrainingJob(
            id=resumed_id, project_id=source.project_id, user_id=current_user.id,
            experiment_id=source.experiment_id, name=f"{source.name}-resume",
            operator_id=source.operator_id, params=dict(source.params or {}),
            dataset_artifact_id=source.dataset_artifact_id, dataset_path=source.dataset_path,
            status="pending", total_epochs=total_epochs, monitor_name=source.monitor_name,
            monitor_mode=source.monitor_mode,
            early_stopping_patience=source.early_stopping_patience,
            early_stopping_min_delta=source.early_stopping_min_delta,
            restore_best=source.restore_best, resumed_from_job_id=source.id,
            resumed_from_run_id=source.mlflow_run_id,
            resume_checkpoint_uri=(
                _replace_checkpoint_path(checkpoint_uri, checkpoint_path)
                if data.checkpoint_path else checkpoint_uri
            ),
            attempt=0,
        )
        db.add(resumed)
    db.refresh(resumed)
    _dispatch_job(
        db, resumed, get_training_dispatcher(request), request, current_user, access,
    )
    return {"job_id": str(resumed.id), "status": "queued", "task_id": resumed.task_id}


@router.post("/jobs/{job_id}/tensorboard-session", status_code=201)
def create_tensorboard_session(
    job_id: uuid.UUID,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    job, _ = _visible_job(db, job_id, current_user.id)
    if job is None:
        raise HTTPException(404, _error("TRAINING_JOB_NOT_FOUND", "Training job not found"))
    if not job.mlflow_run_id:
        raise HTTPException(409, _error(
            "TENSORBOARD_RUN_UNAVAILABLE",
            "Training job has no tracked Run",
        ))
    signer = get_tensorboard_signer(request)
    session_id = uuid.uuid4().hex
    ttl = int(getattr(
        request.app.state,
        "tensorboard_session_ttl_seconds",
        300,
    ))
    expires_at = int(signer.clock()) + ttl
    relative_logdir = f"{job.project_id}/{job.mlflow_run_id}"
    try:
        token = signer.issue(
            session_id=session_id,
            run_id=job.mlflow_run_id,
            relative_logdir=relative_logdir,
            expires_at=expires_at,
        )
    except SessionTokenInvalid as error:
        raise HTTPException(500, _error(
            "TENSORBOARD_SESSION_INVALID",
            "TensorBoard session could not be created",
        )) from error
    return {
        "session_id": session_id,
        "run_id": job.mlflow_run_id,
        "expires_at": expires_at,
        "token": token,
        "url": f"/api/training/tensorboard/{token}/",
    }


@router.api_route(
    "/tensorboard/{token}/{path:path}",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
)
async def proxy_tensorboard(token: str, path: str, request: Request):
    signer = get_tensorboard_signer(request)
    try:
        claims = signer.verify(token)
    except SessionTokenInvalid as error:
        raise HTTPException(403, _error(
            "TENSORBOARD_SESSION_INVALID",
            "TensorBoard session is invalid or expired",
        )) from error
    injected = getattr(request.app.state, "tensorboard_proxy_handler", None)
    if injected is not None:
        return await injected(claims, path, request)

    from app.config import settings

    gateway_url = getattr(
        request.app.state,
        "tensorboard_gateway_url",
        settings.tensorboard_gateway_url,
    )
    if not gateway_url:
        raise HTTPException(503, _error(
            "TENSORBOARD_UNAVAILABLE",
            "TensorBoard gateway is unavailable",
        ))
    target = (
        f"{str(gateway_url).rstrip('/')}/sessions/"
        f"{claims.session_id}/{path.lstrip('/')}"
    )
    async with httpx.AsyncClient() as client:
        upstream = await client.request(
            request.method,
            target,
            params={**request.query_params, "token": token},
            content=await request.body(),
            headers={
                key: value for key, value in request.headers.items()
                if key.lower() in {"accept", "content-type", "range"}
            },
        )
    return Response(
        content=upstream.content,
        status_code=upstream.status_code,
        headers={
            key: value for key, value in upstream.headers.items()
            if key.lower() in {"content-type", "content-range", "accept-ranges", "location"}
        },
    )


@router.post("/automl/run", status_code=202)
def start_automl(
    data: AutoMLRunRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    experiment, access = _visible_experiment(
        db,
        data.experiment_id,
        data.project_id,
        current_user.id,
    )
    if experiment is None:
        raise HTTPException(404, _error("EXPERIMENT_NOT_FOUND", "Experiment not found"))
    job_id = uuid.uuid4()
    with audit_service(db).project_action(
        db, request=request, actor=current_user, access=access,
        permission="execution.operate",
        intent=AuditIntent(
            project_id=data.project_id, action="training_job.automl_start",
            resource_type="training_job", resource_id=str(job_id),
            changes={"name": data.name, "task": data.task},
        ),
        allowed_changes={"name", "task"},
    ):
        if data.task not in {"classification", "regression"}:
            raise HTTPException(400, _error("AUTOML_CONFIG_INVALID", "Invalid AutoML task"))
        try:
            resolve_candidates(data.task, data.candidate_ids)
        except ValueError as error:
            raise HTTPException(400, _error("AUTOML_CONFIG_INVALID", str(error))) from error
        artifact_service = get_artifact_service(request, db)
        try:
            dataset = artifact_service.resolve(
                data.dataset_artifact_id, data.project_id, expected_type="dataset",
            )
        except (ValueError, ArtifactAccessError) as error:
            raise HTTPException(400, _error("DATASET_ARTIFACT_INVALID", str(error))) from error
        job = TrainingJob(
            id=job_id, project_id=data.project_id, user_id=current_user.id,
            experiment_id=experiment.id, name=data.name, operator_id="automl",
            params={
                "target_column": data.target_column,
                "task": data.task,
                "candidate_ids": data.candidate_ids,
                "time_budget": data.time_budget,
            },
            dataset_artifact_id=dataset.id,
            dataset_path=artifact_service.storage_reference(dataset), status="pending",
        )
        db.add(job)
    db.refresh(job)
    _dispatch_job(
        db, job, get_automl_dispatcher(request), request, current_user, access,
    )
    return {"job_id": str(job.id), "status": "queued", "task_id": job.task_id}


@router.get("/automl/jobs")
def list_automl_jobs(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    project_ids = [
        project.id for project in ProjectAccessService()
        .accessible_project_query(db, current_user.id).all()
    ]
    jobs = db.query(TrainingJob).filter(
        TrainingJob.project_id.in_(project_ids),
        TrainingJob.operator_id == "automl",
    ).order_by(TrainingJob.created_at.desc()).all()
    return [_job_to_dict(job) for job in jobs]


@router.get("/models/versions")
def list_model_versions(
    project_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    project = require_project_access(
        db, project_id, current_user.id, "project.read",
    ).project
    jobs = db.query(TrainingJob).filter(
        TrainingJob.project_id == project.id,
        TrainingJob.status == "completed",
    ).order_by(TrainingJob.finished_at.desc()).all()
    return {"versions": [_job_to_dict(job) for job in jobs]}


@router.post("/batch-delete")
def batch_delete_training_jobs(
    data: BatchDeleteRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    deleted = 0
    for value in data.ids:
        try:
            job_id = uuid.UUID(value)
        except ValueError:
            continue
        job, access = _visible_job(db, job_id, current_user.id)
        if job is None or job.status not in TERMINAL_TRAINING_STATUSES:
            continue
        with audit_service(db).project_action(
            db, request=request, actor=current_user, access=access,
            permission="resource.delete",
            intent=AuditIntent(
                project_id=job.project_id, action="training_job.delete",
                resource_type="training_job", resource_id=str(job.id),
            ),
            allowed_changes=set(),
        ):
            db.delete(job)
        deleted += 1
    return {"deleted": deleted}


def _dispatch_job(db, job, dispatcher, request, actor, access) -> None:
    try:
        task_id = dispatcher.enqueue(job.id)
        start = getattr(dispatcher, "start", None)
        with audit_service(db).project_action(
            db, request=request, actor=actor, access=access,
            permission="execution.operate",
            intent=AuditIntent(
                project_id=job.project_id, action="training_job.dispatch",
                resource_type="training_job", resource_id=str(job.id),
                changes={"status": "queued"},
            ),
            allowed_changes={"status"},
        ):
            job.status = "queued"
            job.task_id = task_id
        if callable(start):
            start(task_id)
    except Exception as error:
        with audit_service(db).project_action(
            db, request=request, actor=actor, access=access,
            permission="execution.operate",
            intent=AuditIntent(
                project_id=job.project_id, action="training_job.dispatch_failed",
                resource_type="training_job", resource_id=str(job.id),
                changes={"status": "failed", "error_code": "TRAINING_DISPATCH_FAILED"},
            ),
            allowed_changes={"status", "error_code"},
        ):
            job.status = "failed"
            job.error_code = "TRAINING_DISPATCH_FAILED"
            job.error_message = "Training task could not be queued"
        raise HTTPException(503, _error(
            "TRAINING_DISPATCH_FAILED",
            "Training task could not be queued",
        )) from error


def _visible_experiment(db, experiment_id, project_id, user_id):
    experiment = db.query(Experiment).filter(
        Experiment.id == experiment_id,
        Experiment.project_id == project_id,
    ).first()
    if experiment is None:
        return None, None
    access = resolve_project_access(db, project_id, user_id)
    return (experiment, access) if access is not None else (None, None)


def _visible_job(db, job_id, user_id):
    job = db.query(TrainingJob).filter(TrainingJob.id == job_id).first()
    if job is None:
        return None, None
    access = resolve_project_access(db, job.project_id, user_id)
    return (job, access) if access is not None else (None, None)


def _checkpoint_path(uri: str) -> str:
    marker = "checkpoints/"
    index = uri.find(marker)
    if index < 0 or ".." in uri[index:].split("/"):
        raise HTTPException(400, _error("CHECKPOINT_INVALID", "Checkpoint URI is invalid"))
    return uri[index:]


def _replace_checkpoint_path(uri: str, path: str) -> str:
    marker = "checkpoints/"
    index = uri.find(marker)
    if index < 0:
        raise HTTPException(400, _error("CHECKPOINT_INVALID", "Checkpoint URI is invalid"))
    return f"{uri[:index]}{path}"


def _run_artifact_uri(job: TrainingJob, path: str) -> str:
    for uri in (job.latest_checkpoint_uri, job.best_checkpoint_uri):
        if uri and "checkpoints/" in uri:
            return f"{uri[:uri.index('checkpoints/')]}{path}"
    return path


def _job_to_dict(job: TrainingJob) -> dict:
    return {
        "id": str(job.id),
        "project_id": str(job.project_id),
        "user_id": str(job.user_id),
        "experiment_id": str(job.experiment_id) if job.experiment_id else None,
        "mlflow_run_id": job.mlflow_run_id,
        "name": job.name,
        "operator_id": job.operator_id,
        "params": job.params or {},
        "dataset_artifact_id": str(job.dataset_artifact_id) if job.dataset_artifact_id else None,
        "status": job.status,
        "task_id": job.task_id,
        "worker_id": job.worker_id,
        "current_epoch": job.current_epoch or 0,
        "total_epochs": job.total_epochs,
        "metrics": job.metrics or {},
        "latest_checkpoint_uri": job.latest_checkpoint_uri,
        "best_checkpoint_uri": job.best_checkpoint_uri,
        "resumed_from_job_id": str(job.resumed_from_job_id) if job.resumed_from_job_id else None,
        "resumed_from_run_id": job.resumed_from_run_id,
        "model_artifact_id": str(job.model_artifact_id) if job.model_artifact_id else None,
        "model_library_id": str(job.model_library_id) if job.model_library_id else None,
        "error_code": job.error_code,
        "error_message": job.error_message,
        "created_at": job.created_at.isoformat() if job.created_at else None,
        "started_at": job.started_at.isoformat() if job.started_at else None,
        "finished_at": job.finished_at.isoformat() if job.finished_at else None,
    }


def _error(code: str, message: str) -> dict[str, str]:
    return {"code": code, "message": message}
