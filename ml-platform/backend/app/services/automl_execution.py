"""Finite, deterministic AutoML execution with MLflow child Runs."""

import math
import tempfile
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Sequence

import joblib
import pandas as pd
from sklearn.ensemble import (
    GradientBoostingClassifier,
    GradientBoostingRegressor,
    RandomForestClassifier,
    RandomForestRegressor,
)
from sklearn.linear_model import LinearRegression, LogisticRegression
from sklearn.model_selection import KFold, StratifiedKFold, cross_val_score

from app.database import SessionLocal
from app.models.experiment import Experiment
from app.models.model_library import ModelLibrary
from app.models.training import TrainingJob
from app.services.artifact_service import build_artifact_service
from app.services.training_execution import build_training_tracking, claim_training_job, utcnow


@dataclass(frozen=True)
class AutoMLCandidate:
    name: str
    factory: Callable[[], object]
    params: dict


@dataclass(frozen=True)
class AutoMLDependencies:
    session_factory: Callable = SessionLocal
    artifact_service_factory: Callable = build_artifact_service
    tracking_factory: Callable = build_training_tracking
    worker_id: str = "worker"
    task_id: str = "unknown"


@dataclass(frozen=True)
class AutoMLExecutionResult:
    job_id: str
    status: str
    best_candidate: str | None = None
    error_code: str | None = None


class AllCandidatesFailed(RuntimeError):
    pass


def default_candidates(task: str) -> tuple[AutoMLCandidate, ...]:
    if task == "classification":
        return (
            AutoMLCandidate(
                "random_forest",
                lambda: RandomForestClassifier(n_estimators=100, random_state=42),
                {"n_estimators": 100, "random_state": 42},
            ),
            AutoMLCandidate(
                "gradient_boosting",
                lambda: GradientBoostingClassifier(random_state=42),
                {"random_state": 42},
            ),
            AutoMLCandidate(
                "logistic_regression",
                lambda: LogisticRegression(max_iter=500, random_state=42),
                {"max_iter": 500, "random_state": 42},
            ),
        )
    return (
        AutoMLCandidate(
            "random_forest",
            lambda: RandomForestRegressor(n_estimators=100, random_state=42),
            {"n_estimators": 100, "random_state": 42},
        ),
        AutoMLCandidate(
            "gradient_boosting",
            lambda: GradientBoostingRegressor(random_state=42),
            {"random_state": 42},
        ),
        AutoMLCandidate("linear_regression", LinearRegression, {}),
    )


def execute_automl_job(
    job_id,
    *,
    candidates: Sequence[AutoMLCandidate] | None = None,
    dependencies: AutoMLDependencies | None = None,
) -> AutoMLExecutionResult:
    dependencies = dependencies or AutoMLDependencies()
    job_uuid = uuid.UUID(str(job_id))
    with dependencies.session_factory() as claim_db:
        if not claim_training_job(
            claim_db,
            job_uuid,
            task_id=dependencies.task_id,
            worker_id=dependencies.worker_id,
        ):
            return AutoMLExecutionResult(str(job_uuid), "skipped")

    tracking = None
    parent = None
    db = dependencies.session_factory()
    try:
        job = db.query(TrainingJob).filter(TrainingJob.id == job_uuid).one()
        experiment = db.query(Experiment).filter(Experiment.id == job.experiment_id).one()
        tracking = dependencies.tracking_factory()
        parent = tracking.start_run(
            experiment.mlflow_experiment_id,
            run_name=job.name,
            tags={
                "platform.project_id": str(job.project_id),
                "platform.job_id": str(job.id),
                "platform.run_type": "automl",
            },
        )
        job.mlflow_run_id = parent.run_id
        db.commit()

        artifact_service = dependencies.artifact_service_factory(db)
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
        target_column = params.get("target_column")
        task = params.get("task", "classification")
        if task not in {"classification", "regression"}:
            raise ValueError("AutoML task must be classification or regression")
        if not target_column or target_column not in frame.columns:
            raise ValueError("AutoML target column is missing")
        prepared = frame.dropna()
        features = prepared.drop(columns=[target_column]).select_dtypes(include=["number"])
        target = prepared.loc[features.index, target_column]
        if features.empty or len(features) < 10:
            raise ValueError("AutoML requires numeric features and at least ten rows")

        configured_candidates = tuple(candidates or default_candidates(task))
        if not configured_candidates:
            raise ValueError("AutoML requires at least one candidate")
        cv = (
            StratifiedKFold(n_splits=5, shuffle=True, random_state=42)
            if task == "classification"
            else KFold(n_splits=5, shuffle=True, random_state=42)
        )
        scoring = "accuracy" if task == "classification" else "r2"
        successes = []
        for index, candidate in enumerate(configured_candidates):
            child = tracking.start_run(
                experiment.mlflow_experiment_id,
                run_name=candidate.name,
                tags={"platform.candidate": candidate.name},
                parent_run_id=parent.run_id,
            )
            started = time.perf_counter()
            try:
                estimator = candidate.factory()
                tracking.log_params(child.run_id, candidate.params)
                scores = cross_val_score(
                    estimator,
                    features,
                    target,
                    cv=cv,
                    scoring=scoring,
                    error_score="raise",
                )
                score = float(scores.mean())
                if not math.isfinite(score):
                    raise ValueError("Candidate score is not finite")
                duration = time.perf_counter() - started
                tracking.log_metrics(child.run_id, {"cv_score": score}, step=0)
                tracking.set_tags(child.run_id, {"platform.duration_seconds": duration})
                tracking.end_run(child.run_id, "FINISHED")
                successes.append((score, index, candidate, child.run_id))
            except Exception as error:
                duration = time.perf_counter() - started
                tracking.set_tags(child.run_id, {
                    "platform.duration_seconds": duration,
                    "platform.error_type": type(error).__name__,
                    "platform.error_message": str(error),
                })
                tracking.end_run(child.run_id, "FAILED")

        if not successes:
            raise AllCandidatesFailed("All AutoML candidates failed")
        best_score, _index, best_candidate, best_child_run_id = max(
            successes,
            key=lambda item: (item[0], -item[1]),
        )
        winner = best_candidate.factory()
        winner.fit(features, target)
        with tempfile.TemporaryDirectory() as temporary:
            model_path = Path(temporary) / f"{job.id}.joblib"
            joblib.dump({
                "model": winner,
                "feature_schema": [
                    {"name": str(name), "dtype": str(features[name].dtype)}
                    for name in features.columns
                ],
                "target_schema": {
                    "name": target_column,
                    "dtype": str(target.dtype),
                    "task": task,
                },
            }, model_path)
            model_artifact = artifact_service.create_from_file(
                job.project_id,
                model_path,
                f"{job.name}.joblib",
                "model",
                metadata={
                    "source": "automl",
                    "training_job_id": str(job.id),
                    "dataset_artifact_id": str(dataset.id),
                    "mlflow_run_id": parent.run_id,
                    "best_candidate": best_candidate.name,
                    "best_score": best_score,
                },
            )

        model_entry = ModelLibrary(
            name=job.name,
            project_id=job.project_id,
            owner_id=job.user_id,
            status="completed",
            framework="scikit-learn",
            backbone=type(winner).__name__,
            metrics={"best_score": best_score},
            params={**params, "best_candidate": best_candidate.name},
            model_path=artifact_service.storage_reference(model_artifact),
            file_size=model_artifact.file_size or 0,
            format="joblib",
            training_job_id=job.id,
            dataset_artifact_id=dataset.id,
            model_artifact_id=model_artifact.id,
        )
        db.add(model_entry)
        db.flush()
        job.status = "completed"
        job.metrics = {"best_score": best_score, "best_candidate": best_candidate.name}
        job.model_path = artifact_service.storage_reference(model_artifact)
        job.model_artifact_id = model_artifact.id
        job.model_library_id = model_entry.id
        job.finished_at = utcnow()
        job.heartbeat_at = utcnow()
        tracking.log_metrics(parent.run_id, {"best_score": best_score}, step=0)
        tracking.set_tags(parent.run_id, {
            "platform.best_child_run_id": best_child_run_id,
            "platform.best_candidate": best_candidate.name,
            "platform.model_artifact_id": str(model_artifact.id),
        })
        tracking.end_run(parent.run_id, "FINISHED")
        db.commit()
        return AutoMLExecutionResult(str(job_uuid), "completed", best_candidate.name)
    except Exception as error:
        db.rollback()
        if tracking is not None and parent is not None:
            try:
                tracking.end_run(parent.run_id, "FAILED")
            except Exception:
                pass
        error_code = (
            "AUTOML_ALL_CANDIDATES_FAILED"
            if isinstance(error, AllCandidatesFailed)
            else "AUTOML_FAILED"
        )
        with dependencies.session_factory() as failed_db:
            failed = failed_db.query(TrainingJob).filter(TrainingJob.id == job_uuid).first()
            if failed is not None:
                failed.status = "failed"
                failed.error_code = error_code
                failed.error_message = str(error)
                failed.error_details = {"exception_type": type(error).__name__}
                failed.finished_at = utcnow()
                failed_db.commit()
        return AutoMLExecutionResult(str(job_uuid), "failed", error_code=error_code)
    finally:
        db.close()
