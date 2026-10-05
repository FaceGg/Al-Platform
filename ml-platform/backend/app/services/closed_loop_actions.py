"""Reusable closed-loop actions shared by the demo-loop service and the
orchestration serving operators (append error dataset / notify admins /
retrain threshold trigger + completion swap)."""

from __future__ import annotations

import hashlib
import io
import json
import tempfile
import threading
import uuid
from datetime import datetime
from pathlib import Path

import pandas as pd

from app.config import settings
from app.database import SessionLocal
from app.models.artifact import Artifact
from app.models.experiment import Experiment, ExperimentAutoMLBinding
from app.models.model_registry import InferenceDeployment, ModelVersion
from app.models.notifications import InAppNotification
from app.models.project import Project
from app.models.training import TrainingJob
from app.models.user import User
from app.services.artifact_service import build_artifact_service
from app.services.automl_catalog import AUTOML_FAMILY_IDS, resolve_algorithm_families
from app.services.automl_execution import normalize_evaluation_config, resolve_automl_feature_columns
from app.services.automl_search import normalize_search_controls, validate_target_columns
from app.services.model_registry import ModelRegistryService, ModelRegistryError


class ClosedLoopError(ValueError):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


_LOCKS_GUARD = threading.Lock()
_LOCKS: dict[str, threading.Lock] = {}


def lock_for(key: str) -> threading.Lock:
    with _LOCKS_GUARD:
        lock = _LOCKS.get(key)
        if lock is None:
            lock = threading.Lock()
            _LOCKS[key] = lock
        return lock


def json_value(value):
    import math

    import numpy as np

    if value is None or value is pd.NaT:
        return None
    if isinstance(value, (pd.Timestamp, datetime)):
        return value.isoformat()
    if isinstance(value, np.generic):
        return json_value(value.item())
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, dict):
        return {str(key): json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_value(item) for item in value]
    return value


# Backwards-compatible alias for the demo_loop service.
_json_value = json_value


def automl_dispatcher():
    if getattr(settings, "task_backend", "local") == "celery":
        # CeleryTrainingDispatcher lives in the training API module; the celery
        # task itself lives in app.tasks.training_tasks.
        from app.api.training import CeleryTrainingDispatcher
        from app.tasks.training_tasks import execute_automl_task

        return CeleryTrainingDispatcher(execute_automl_task)
    from app.tasks.training_tasks import LocalTrainingDispatcher, execute_local_automl_task

    return LocalTrainingDispatcher(execute_local_automl_task)


# Backwards-compatible alias: demo_loop re-exports this so its tests can patch
# the dispatcher on the demo_loop module.
_automl_dispatcher = automl_dispatcher


# ---------------------------------------------------------------- dataset append


def _as_uuid(value) -> uuid.UUID:
    return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))


def append_rows_to_dataset_artifact(
    db, artifact_service, artifact: Artifact, rows: list[dict],
) -> int:
    """Append JSON-safe rows to a CSV dataset artifact in place.

    Returns the new total row count. Concurrency is serialized per artifact.
    """
    if not rows:
        return int((artifact.metadata_ or {}).get("row_count", 0))
    columns = sorted({key for row in rows for key in row})
    with lock_for(f"artifact:{artifact.id}"):
        service = artifact_service
        old_uri = artifact.storage_uri
        with service.storage.materialize(artifact.storage_uri) as path:
            frame = pd.read_csv(path)
        for row in rows:
            frame.loc[len(frame)] = [json_value(row.get(column)) for column in frame.columns]
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "rows.csv"
            frame.to_csv(out, index=False)
            stored = service.storage.put(
                out,
                project_id=str(artifact.project_id),
                artifact_id=str(artifact.id),
                filename=Path(artifact.name).name or "rows.csv",
            )
        schema = [
            {"name": str(column), "dtype": str(frame[column].dtype),
             "null_count": int(frame[column].isna().sum())}
            for column in frame.columns
        ]
        artifact.storage_uri = stored.uri
        artifact.file_size = stored.size
        artifact.metadata_ = {
            **(artifact.metadata_ or {}),
            "sha256": stored.sha256,
            "row_count": int(len(frame)),
            "column_count": int(len(frame.columns)),
            "schema": schema,
        }
        db.commit()
        if old_uri and old_uri != stored.uri:
            try:
                service.storage.delete(old_uri)
            except Exception:
                pass
    return int(len(frame))


# ---------------------------------------------------------------- notifications


def notify_project_admins(
    db, project_id, title: str, body: str, *,
    severity: str = "warning",
    event_type: str = "closed_loop.notify",
    payload: dict | None = None,
) -> int:
    project_id = _as_uuid(project_id)
    recipients: set = set()
    project = db.query(Project).filter(Project.id == project_id).first()
    if project is not None and project.owner_id:
        recipients.add(uuid.UUID(str(project.owner_id)))
    for row in db.query(User.id).filter(User.role == "admin").all():
        recipients.add(row.id)
    for recipient in recipients:
        db.add(InAppNotification(
            recipient_user_id=recipient,
            project_id=project_id,
            event_id=uuid.uuid4(),
            event_type=event_type,
            deduplication_key=f"cl-{uuid.uuid4().hex[:16]}",
            severity=severity,
            title=title,
            body=body,
            payload=json_value(payload or {}) or {},
        ))
    db.commit()
    return len(recipients)


# ---------------------------------------------------------------- retrain


def trigger_retrain_job(
    db, *, project_id, actor_id, experiment_name: str, job_name: str,
    dataset_artifact_id, target_column: str, max_trials: int = 10,
) -> TrainingJob:
    """Create and dispatch one AutoML job on the given dataset/target."""
    project_id = _as_uuid(project_id)
    dataset_artifact_id = _as_uuid(dataset_artifact_id)
    actor_id = _as_uuid(actor_id)
    service = build_artifact_service(db)
    dataset = service.resolve(dataset_artifact_id, project_id, expected_type="dataset")

    experiment = db.query(Experiment).filter(
        Experiment.project_id == project_id,
        Experiment.name == experiment_name,
    ).first()
    if experiment is None:
        experiment = Experiment(
            project_id=project_id,
            created_by=actor_id,
            name=experiment_name,
            description="闭环流程自动创建的实验",
            # Unique placeholder; the real tracking id is registered below and
            # the column is globally unique.
            mlflow_experiment_id=f"pending-{uuid.uuid4().hex[:24]}",
        )
        db.add(experiment)
        db.flush()
    if experiment.mlflow_experiment_id.startswith("pending-"):
        # Register the experiment with the real tracking backend so the
        # AutoML worker can start a run against it.
        from mlflow.tracking import MlflowClient

        from app.services.experiment_tracking import (
            MlflowExperimentTracking,
            resolve_tracking_configuration,
        )
        tracking_uri, artifact_root = resolve_tracking_configuration(settings)
        tracking = MlflowExperimentTracking(
            client=MlflowClient(tracking_uri=tracking_uri),
            artifact_root=artifact_root,
        )
        experiment.mlflow_experiment_id = tracking.ensure_experiment(
            f"project/{experiment.project_id}/{experiment.id}",
        )
        db.flush()

    with service.materialize(dataset.id, project_id, expected_type="dataset") as path:
        frame = pd.read_csv(path)
    if target_column not in frame.columns:
        raise ClosedLoopError(
            "CLOSED_LOOP_TARGET_MISSING", f"目标列 {target_column} 不在重训数据集中")
    task_type = "classification"
    validate_target_columns(frame, task_type, [target_column])
    feature_columns = resolve_automl_feature_columns(
        frame, target_column, None, target_columns=[target_column],
    )
    families = resolve_algorithm_families(list(AUTOML_FAMILY_IDS))
    evaluation = normalize_evaluation_config(True, 3)
    controls = normalize_search_controls(strength="light", time_budget=600, class_weight=True)
    trials = max(int(max_trials or 10), len(families))
    fingerprint = hashlib.sha256(json.dumps({
        "experiment": experiment_name, "dataset": str(dataset.id), "target": target_column,
    }, sort_keys=True).encode("utf-8")).hexdigest()
    job = TrainingJob(
        id=uuid.uuid4(),
        project_id=project_id,
        user_id=actor_id,
        experiment_id=experiment.id,
        name=job_name or f"{experiment_name}-job",
        operator_id="automl",
        params={
            "target_column": target_column,
            "target_columns": [target_column],
            "input_columns": list(feature_columns),
            "task": task_type,
            "search_contract": "optuna_v1",
            "algorithm_ids": [family.id for family in families],
            "search_method": "bayesian",
            "max_trials": trials,
            **evaluation,
            "time_budget": controls["time_budget"],
            "search_strength": controls["strength"],
            "class_weight": controls["class_weight"],
        },
        dataset_artifact_id=dataset.id,
        dataset_path=service.storage_reference(dataset),
        status="pending",
        automl_contract={
            "task_type": task_type,
            "target_columns": [target_column],
            "cross_validation_folds": evaluation["cross_validation_folds"],
            "cv_strategy": "stratified",
            "random_seed": 42,
            "idempotency_fingerprint": fingerprint,
        },
        automl_idempotency_key=f"closed-loop-{fingerprint[:24]}",
    )
    db.add(job)
    db.add(ExperimentAutoMLBinding(experiment_id=experiment.id, job_id=job.id))
    db.flush()
    # Local dispatcher only registers on enqueue and needs start(task_id)
    # to spawn the worker thread; Celery's delay runs it inside enqueue.
    dispatcher = automl_dispatcher()
    task_id = dispatcher.enqueue(job.id)
    if hasattr(dispatcher, "start"):
        dispatcher.start(task_id)
    return job


# ---------------------------------------------------------------- model swap


def candidate_score(row: dict) -> float:
    metrics = row.get("metrics") or {}
    if isinstance(metrics, dict):
        for key in ("auc", "accuracy", "f1", "precision", "recall", "r2"):
            value = metrics.get(key)
            if isinstance(value, (int, float)):
                return float(value)
        for value in metrics.values():
            if isinstance(value, (int, float)):
                return float(value)
    return 0.0


def complete_retrain_swap(
    db, *, deployment_id, job: TrainingJob, actor_id, model_name: str,
):
    """Register the best candidate of a finished AutoML job, approve it and
    point the deployment at it. Returns the new ModelVersion, or None when
    the job has no registerable candidates."""
    deployment_id = _as_uuid(deployment_id) if deployment_id else None
    actor_id = _as_uuid(actor_id)
    registry = ModelRegistryService(artifact_service=build_artifact_service(db))
    candidates = registry.list_registerable_candidates(db, job.id)
    if not candidates:
        return None
    best = max(candidates, key=candidate_score)
    candidate_id = best.get("candidate_id") or best.get("id")
    version, _created = registry.register_automl_candidate(
        db,
        task_id=job.id,
        candidate_id=candidate_id,
        model_name=model_name,
        actor_id=actor_id,
        idempotency_key=f"closed-loop-{job.id}",
    )
    registry.transition_model_version(db, version.id, "approve", actor_id)
    if deployment_id is not None:
        deployment = db.query(InferenceDeployment).filter(
            InferenceDeployment.id == deployment_id,
        ).first()
        if deployment is not None:
            deployment.model_version_id = version.id
    if hasattr(version, "_sa_instance_state"):
        db.commit()
        db.refresh(version)
    return version
