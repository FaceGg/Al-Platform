"""Durable TrainingJob execution across ORM, tracking, and artifacts."""

import tempfile
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

import joblib
import pandas as pd

from app.config import settings
from app.database import SessionLocal
from app.models.experiment import Experiment
from app.models.model_library import ModelLibrary
from app.models.training import TrainingJob
from app.services.artifact_service import build_artifact_service
from app.services.experiment_tracking import (
    MlflowExperimentTracking,
    TrackingError,
    TrackingUnavailable,
)
from app.services.iterative_training import IterativeTrainer, TrainingCheckpoint, TrainingConfig


@dataclass(frozen=True)
class TrainingExecutionOutcome:
    job_id: str
    status: str
    error_code: str | None = None


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def build_training_tracking():
    if not settings.mlflow_tracking_uri or not settings.mlflow_artifact_root:
        raise TrackingUnavailable("Experiment tracking is not configured")
    from mlflow.tracking import MlflowClient

    return MlflowExperimentTracking(
        client=MlflowClient(tracking_uri=settings.mlflow_tracking_uri),
        artifact_root=settings.mlflow_artifact_root,
    )


def claim_training_job(db, job_id, *, task_id: str, worker_id: str) -> bool:
    now = utcnow()
    if db.get_bind().dialect.name == "sqlite":
        updated = db.query(TrainingJob).filter(
            TrainingJob.id == job_id,
            TrainingJob.status.in_(["pending", "queued"]),
        ).update({
            TrainingJob.status: "running",
            TrainingJob.task_id: task_id,
            TrainingJob.worker_id: worker_id,
            TrainingJob.heartbeat_at: now,
            TrainingJob.started_at: now,
        }, synchronize_session=False)
        db.commit()
        return updated == 1

    job = db.query(TrainingJob).with_for_update(skip_locked=True).filter(
        TrainingJob.id == job_id,
    ).first()
    if job is None or job.status not in {"pending", "queued"}:
        return False
    job.status = "running"
    job.task_id = task_id
    job.worker_id = worker_id
    job.heartbeat_at = now
    job.started_at = now
    db.commit()
    return True


def execute_training_job(
    job_id,
    *,
    session_factory=SessionLocal,
    artifact_service_factory=build_artifact_service,
    tracking_factory=build_training_tracking,
    worker_id: str,
    task_id: str,
    checkpoint_interval: int | None = None,
) -> TrainingExecutionOutcome:
    job_uuid = uuid.UUID(str(job_id))
    with session_factory() as claim_db:
        if not claim_training_job(
            claim_db,
            job_uuid,
            task_id=task_id,
            worker_id=worker_id,
        ):
            return TrainingExecutionOutcome(str(job_uuid), "skipped")

    tracking = None
    run = None
    db = session_factory()
    try:
        job = db.query(TrainingJob).filter(TrainingJob.id == job_uuid).one()
        experiment = db.query(Experiment).filter(
            Experiment.id == job.experiment_id,
        ).one()
        tracking = tracking_factory()
        run = tracking.start_run(
            experiment.mlflow_experiment_id,
            run_name=job.name,
            tags={
                "platform.project_id": str(job.project_id),
                "platform.job_id": str(job.id),
                "platform.user_id": str(job.user_id),
                "platform.resumed_from_job_id": str(job.resumed_from_job_id or ""),
                "platform.resumed_from_run_id": str(job.resumed_from_run_id or ""),
            },
        )
        job.mlflow_run_id = run.run_id
        job.logs = [*(job.logs or []), {"level": "info", "message": "Training started"}]
        db.commit()

        artifact_service = artifact_service_factory(db)
        dataset = artifact_service.resolve(
            job.dataset_artifact_id,
            job.project_id,
            expected_type="dataset",
        )
        with artifact_service.materialize(
            dataset.id,
            job.project_id,
            expected_type="dataset",
        ) as dataset_path:
            frame = (
                pd.read_excel(dataset_path)
                if Path(dataset_path).suffix.lower() in {".xls", ".xlsx"}
                else pd.read_csv(dataset_path)
            )

        params = dict(job.params or {})
        task = str(params.get("task", "auto"))
        monitor = job.monitor_name or (
            "val_r2" if task == "regression" else "val_accuracy"
        )
        config = TrainingConfig(
            task=task,
            total_epochs=int(job.total_epochs or params.get("total_epochs", 20)),
            monitor=monitor,
            mode=job.monitor_mode or "max",
            patience=int(job.early_stopping_patience or 5),
            min_delta=float(job.early_stopping_min_delta or 0.0),
            restore_best=job.restore_best if job.restore_best is not None else True,
            checkpoint_interval=int(
                checkpoint_interval
                or params.get("checkpoint_interval")
                or settings.training_checkpoint_interval_epochs
            ),
        )
        target_column = params.get("target_column")
        if not target_column:
            raise ValueError("target_column is required")
        tracking.log_params(run.run_id, {
            **params,
            **asdict(config),
            "target_column": str(target_column),
        })

        with tempfile.TemporaryDirectory() as temporary:
            temporary_path = Path(temporary)
            resume_from = None
            if job.resume_checkpoint_uri:
                if not job.resumed_from_run_id:
                    raise ValueError("Resume source Run is missing")
                checkpoint_path = _checkpoint_artifact_path(job.resume_checkpoint_uri)
                downloaded = tracking.download_artifact(
                    job.resumed_from_run_id,
                    checkpoint_path,
                    temporary_path,
                )
                resume_from = TrainingCheckpoint.loads(Path(downloaded).read_bytes())

            def metric_callback(epoch_metrics):
                tracking.log_metrics(
                    run.run_id,
                    epoch_metrics.values,
                    step=epoch_metrics.epoch,
                )
                with session_factory() as metric_db:
                    current = metric_db.query(TrainingJob).filter(
                        TrainingJob.id == job_uuid,
                    ).one()
                    current.current_epoch = epoch_metrics.epoch
                    current.epochs_completed = epoch_metrics.epoch
                    current.metrics = dict(epoch_metrics.values)
                    current.heartbeat_at = utcnow()
                    metric_db.commit()

            def checkpoint_callback(envelope):
                epoch_name = f"epoch-{envelope.epoch:06d}.joblib"
                epoch_path = temporary_path / epoch_name
                epoch_path.write_bytes(envelope.payload)
                tracking.log_artifact(run.run_id, epoch_path, "checkpoints")

                latest_path = temporary_path / "latest.joblib"
                latest_path.write_bytes(envelope.payload)
                tracking.log_artifact(run.run_id, latest_path, "checkpoints")
                latest_uri = _run_artifact_uri(run.artifact_uri, "checkpoints/latest.joblib")

                best_uri = None
                if envelope.is_best:
                    best_path = temporary_path / "best.joblib"
                    best_path.write_bytes(envelope.payload)
                    tracking.log_artifact(run.run_id, best_path, "checkpoints")
                    best_uri = _run_artifact_uri(run.artifact_uri, "checkpoints/best.joblib")

                with session_factory() as checkpoint_db:
                    current = checkpoint_db.query(TrainingJob).filter(
                        TrainingJob.id == job_uuid,
                    ).one()
                    current.latest_checkpoint_uri = latest_uri
                    if best_uri is not None:
                        current.best_checkpoint_uri = best_uri
                    current.heartbeat_at = utcnow()
                    checkpoint_db.commit()

            def cancel_requested():
                with session_factory() as control_db:
                    status = control_db.query(TrainingJob.status).filter(
                        TrainingJob.id == job_uuid,
                    ).scalar()
                    return status == "cancel_requested"

            result = IterativeTrainer().fit(
                frame,
                target_column=str(target_column),
                config=config,
                metric_callback=metric_callback,
                checkpoint_callback=checkpoint_callback,
                cancel_requested=cancel_requested,
                resume_from=resume_from,
                dataset_artifact_id=str(job.dataset_artifact_id),
                source_job_id=str(job.id),
                source_run_id=run.run_id,
            )

            if result.cancelled:
                tracking.end_run(run.run_id, "KILLED")
                with session_factory() as cancelled_db:
                    current = cancelled_db.query(TrainingJob).filter(
                        TrainingJob.id == job_uuid,
                    ).one()
                    current.status = "cancelled"
                    current.finished_at = utcnow()
                    current.heartbeat_at = utcnow()
                    cancelled_db.commit()
                return TrainingExecutionOutcome(str(job_uuid), "cancelled")

            model_path = temporary_path / f"{job.id}.joblib"
            joblib.dump({
                "model": result.model,
                "scaler": result.scaler,
                "feature_schema": result.model_state.feature_schema,
                "target_schema": result.model_state.target_schema,
                "training_config": asdict(config),
            }, model_path)
            model_artifact = artifact_service.create_from_file(
                job.project_id,
                model_path,
                f"{job.name}.joblib",
                "model",
                metadata={
                    "source": "training",
                    "training_job_id": str(job.id),
                    "dataset_artifact_id": str(dataset.id),
                    "mlflow_run_id": run.run_id,
                    "metrics": dict(result.metrics),
                },
            )

        db.expire_all()
        job = db.query(TrainingJob).filter(TrainingJob.id == job_uuid).one()
        feature_schema = [
            {"name": name, "dtype": dtype}
            for name, dtype in result.model_state.feature_schema
        ]
        model_entry = ModelLibrary(
            name=job.name,
            project_id=job.project_id,
            owner_id=job.user_id,
            status="completed",
            framework="scikit-learn",
            backbone=type(result.model).__name__,
            metrics=dict(result.metrics),
            params=job.params or {},
            model_path=artifact_service.storage_reference(model_artifact),
            file_size=model_artifact.file_size or 0,
            format="joblib",
            training_job_id=job.id,
            dataset_artifact_id=dataset.id,
            model_artifact_id=model_artifact.id,
        )
        db.add(model_entry)
        db.flush()
        job.model_path = artifact_service.storage_reference(model_artifact)
        job.model_artifact_id = model_artifact.id
        job.model_library_id = model_entry.id
        job.feature_schema = feature_schema
        job.target_schema = dict(result.model_state.target_schema)
        job.preprocessing = {"scaler": "StandardScaler", "numeric_features_only": True}
        job.metrics = dict(result.metrics)
        job.current_epoch = result.epochs_completed
        job.epochs_completed = result.epochs_completed
        job.best_metric_value = result.best_metric
        job.status = "completed"
        job.finished_at = utcnow()
        job.heartbeat_at = utcnow()
        job.logs = [*(job.logs or []), {"level": "info", "message": "Training completed"}]
        tracking.set_tags(run.run_id, {
            "platform.model_artifact_id": str(model_artifact.id),
            "platform.model_library_id": str(model_entry.id),
        })
        tracking.end_run(run.run_id, "FINISHED")
        db.commit()
        return TrainingExecutionOutcome(str(job_uuid), "completed")
    except Exception as error:
        db.rollback()
        if tracking is not None and run is not None:
            try:
                tracking.end_run(run.run_id, "FAILED")
            except Exception:
                pass
        error_code = (
            "TRACKING_UNAVAILABLE"
            if isinstance(error, TrackingError)
            else "TRAINING_FAILED"
        )
        with session_factory() as failed_db:
            failed = failed_db.query(TrainingJob).filter(
                TrainingJob.id == job_uuid,
            ).first()
            if failed is not None:
                failed.status = "failed"
                failed.error_code = error_code
                failed.error_message = str(error)
                failed.error_details = {"exception_type": type(error).__name__}
                failed.finished_at = utcnow()
                failed.heartbeat_at = utcnow()
                failed.logs = [*(failed.logs or []), {
                    "level": "error",
                    "code": error_code,
                    "message": str(error),
                }]
                failed_db.commit()
        return TrainingExecutionOutcome(str(job_uuid), "failed", error_code)
    finally:
        db.close()


def _run_artifact_uri(artifact_uri: str | None, path: str) -> str:
    if not artifact_uri:
        raise TrackingUnavailable("Run artifact URI is unavailable")
    return f"{artifact_uri.rstrip('/')}/{path.lstrip('/')}"


def _checkpoint_artifact_path(uri: str) -> str:
    marker = "checkpoints/"
    index = uri.find(marker)
    if index < 0 or ".." in uri[index:].split("/"):
        raise ValueError("Resume checkpoint URI is invalid")
    return uri[index:]
