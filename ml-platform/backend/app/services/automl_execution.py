"""Finite, deterministic AutoML execution with MLflow child Runs."""

import math
import tempfile
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Sequence

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import (
    ExtraTreesClassifier,
    ExtraTreesRegressor,
    GradientBoostingClassifier,
    GradientBoostingRegressor,
    HistGradientBoostingClassifier,
    HistGradientBoostingRegressor,
    RandomForestClassifier,
    RandomForestRegressor,
)
from sklearn.linear_model import LinearRegression, LogisticRegression
from sklearn.metrics import get_scorer
from sklearn.model_selection import KFold, StratifiedKFold, cross_val_score, train_test_split
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import LabelEncoder, StandardScaler

from app.database import SessionLocal
from app.models.experiment import Experiment
from app.models.model_library import ModelLibrary
from app.models.training import TrainingJob
from app.services.artifact_service import build_artifact_service
from app.services.automl_catalog import resolve_algorithm_families
from app.services.automl_search import (
    AllFamilySearchesFailed,
    SearchConfig,
    TrialSummary,
    automl_metric_order_key,
    automl_metric_sort_key,
    classification_metrics,
    choose_family_winner,
    run_family_search,
    normalize_task_type,
)
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
    family_search: Callable = run_family_search
    monotonic: Callable[[], float] = time.monotonic


@dataclass(frozen=True)
class AutoMLExecutionResult:
    job_id: str
    status: str
    best_candidate: str | None = None
    error_code: str | None = None


class AllCandidatesFailed(RuntimeError):
    pass


VALID_CROSS_VALIDATION_FOLDS = frozenset({3, 4, 5})


def normalize_evaluation_config(
    cross_validation_enabled: bool = True,
    cross_validation_folds: int | None = 5,
) -> dict[str, bool | int | None]:
    """Return the persisted evaluation contract used by request and worker paths."""
    if not isinstance(cross_validation_enabled, bool):
        raise ValueError("AUTOML_CONFIG_INVALID")
    if not cross_validation_enabled:
        return {
            "cross_validation_enabled": False,
            "cross_validation_folds": None,
        }
    if (
        isinstance(cross_validation_folds, bool)
        or cross_validation_folds not in VALID_CROSS_VALIDATION_FOLDS
    ):
        raise ValueError("AUTOML_CONFIG_INVALID")
    return {
        "cross_validation_enabled": True,
        "cross_validation_folds": int(cross_validation_folds),
    }


def _optional_boosting_factory(
    task: str,
    library: str,
    overrides: dict | None = None,
) -> Callable[[], object]:
    """Use the requested library when installed and a deterministic sklearn fallback otherwise."""
    def factory():
        is_classifier = task == "classification"
        if library == "lightgbm":
            try:
                from lightgbm import LGBMClassifier, LGBMRegressor
                estimator = LGBMClassifier if is_classifier else LGBMRegressor
                params = {
                    "n_estimators": 160,
                    "learning_rate": 0.05,
                    "num_leaves": 31,
                    "random_state": 42,
                    "verbosity": -1,
                }
                params.update(overrides or {})
                return estimator(**params)
            except ImportError:
                return GradientBoostingClassifier(random_state=42) if is_classifier else GradientBoostingRegressor(random_state=42)
        if library == "xgboost":
            try:
                from xgboost import XGBClassifier, XGBRegressor
                estimator = XGBClassifier if is_classifier else XGBRegressor
                params = {
                    "n_estimators": 160,
                    "learning_rate": 0.05,
                    "max_depth": 5,
                    "subsample": 0.85,
                    "colsample_bytree": 0.85,
                    "random_state": 42,
                    "n_jobs": 1,
                }
                params.update(overrides or {})
                if is_classifier:
                    params["eval_metric"] = "logloss"
                else:
                    params["objective"] = "reg:squarederror"
                return estimator(**params)
            except ImportError:
                return GradientBoostingClassifier(random_state=42) if is_classifier else GradientBoostingRegressor(random_state=42)
        if library == "catboost":
            try:
                from catboost import CatBoostClassifier, CatBoostRegressor
                estimator = CatBoostClassifier if is_classifier else CatBoostRegressor
                params = {
                    "iterations": 160,
                    "learning_rate": 0.05,
                    "depth": 6,
                    "random_seed": 42,
                    "verbose": False,
                    "allow_writing_files": False,
                }
                params.update(overrides or {})
                return estimator(**params)
            except ImportError:
                return GradientBoostingClassifier(random_state=42) if is_classifier else GradientBoostingRegressor(random_state=42)
        raise ValueError(f"Unknown optional AutoML library: {library}")
    return factory


def _legacy_candidates(task: str) -> tuple[AutoMLCandidate, ...]:
    """Compatibility aliases for jobs created before the report candidate catalog."""
    is_classifier = task == "classification"
    return (
        AutoMLCandidate(
            "random_forest",
            (lambda: RandomForestClassifier(n_estimators=160, random_state=42, n_jobs=1))
            if is_classifier else (lambda: RandomForestRegressor(n_estimators=160, random_state=42, n_jobs=1)),
            {"n_estimators": 160, "random_state": 42},
        ),
        AutoMLCandidate(
            "gradient_boosting",
            (lambda: GradientBoostingClassifier(random_state=42))
            if is_classifier else (lambda: GradientBoostingRegressor(random_state=42)),
            {"random_state": 42},
        ),
        AutoMLCandidate(
            "logistic_regression" if is_classifier else "linear_regression",
            (lambda: make_pipeline(StandardScaler(), LogisticRegression(max_iter=500, random_state=42)))
            if is_classifier else LinearRegression,
            {"max_iter": 500, "random_state": 42} if is_classifier else {},
        ),
    )


def default_candidates(task: str) -> tuple[AutoMLCandidate, ...]:
    if normalize_task_type(task) not in {"classification", "regression"}:
        raise ValueError("AUTOML_CONFIG_INVALID")
    is_classifier = task == "classification"
    return (
        AutoMLCandidate(
            "LGB_v1",
            _optional_boosting_factory(task, "lightgbm", {"n_estimators": 200, "learning_rate": 0.05, "num_leaves": 31}),
            {"n_estimators": 200, "learning_rate": 0.05, "num_leaves": 31},
        ),
        AutoMLCandidate(
            "LGB_v2",
            _optional_boosting_factory(task, "lightgbm", {"n_estimators": 500, "learning_rate": 0.03, "num_leaves": 63, "subsample": 0.7, "colsample_bytree": 0.7, "reg_alpha": 0.1, "reg_lambda": 0.1}),
            {"n_estimators": 500, "learning_rate": 0.03, "num_leaves": 63, "subsample": 0.7, "colsample_bytree": 0.7, "reg_alpha": 0.1, "reg_lambda": 0.1},
        ),
        AutoMLCandidate(
            "XGB_v1",
            _optional_boosting_factory(task, "xgboost", {"n_estimators": 200, "learning_rate": 0.05, "max_depth": 5}),
            {"n_estimators": 200, "learning_rate": 0.05, "max_depth": 5},
        ),
        AutoMLCandidate(
            "XGB_v2",
            _optional_boosting_factory(task, "xgboost", {"n_estimators": 500, "learning_rate": 0.03, "max_depth": 7}),
            {"n_estimators": 500, "learning_rate": 0.03, "max_depth": 7},
        ),
        AutoMLCandidate(
            "CAT_v1",
            _optional_boosting_factory(task, "catboost", {"iterations": 200, "learning_rate": 0.05, "depth": 6}),
            {"iterations": 200, "learning_rate": 0.05, "depth": 6},
        ),
        AutoMLCandidate(
            "CAT_v2",
            _optional_boosting_factory(task, "catboost", {"iterations": 500, "learning_rate": 0.03, "depth": 8}),
            {"iterations": 500, "learning_rate": 0.03, "depth": 8},
        ),
        AutoMLCandidate(
            "GBDT_v1",
            (lambda: GradientBoostingClassifier(n_estimators=200, learning_rate=0.1, max_depth=5, random_state=42))
            if is_classifier else (lambda: GradientBoostingRegressor(n_estimators=200, learning_rate=0.1, max_depth=5, random_state=42)),
            {"n_estimators": 200, "learning_rate": 0.1, "max_depth": 5},
        ),
        AutoMLCandidate(
            "RF_v1",
            (lambda: RandomForestClassifier(n_estimators=300, random_state=42, n_jobs=1))
            if is_classifier else (lambda: RandomForestRegressor(n_estimators=300, random_state=42, n_jobs=1)),
            {"n_estimators": 300},
        ),
        AutoMLCandidate(
            "ET_v1",
            (lambda: ExtraTreesClassifier(n_estimators=300, random_state=42, n_jobs=1))
            if is_classifier else (lambda: ExtraTreesRegressor(n_estimators=300, random_state=42, n_jobs=1)),
            {"n_estimators": 300},
        ),
        AutoMLCandidate(
            "HGB_v1",
            (lambda: HistGradientBoostingClassifier(max_iter=300, learning_rate=0.05, random_state=42))
            if is_classifier else (lambda: HistGradientBoostingRegressor(max_iter=300, learning_rate=0.05, random_state=42)),
            {"max_iter": 300, "learning_rate": 0.05},
        ),
    )


def resolve_candidates(
    task: str,
    candidate_ids: Sequence[str] | None = None,
) -> tuple[AutoMLCandidate, ...]:
    if normalize_task_type(task) not in {"classification", "regression"}:
        raise ValueError("AUTOML_CONFIG_INVALID")
    catalog = {
        candidate.name: candidate
        for candidate in (*default_candidates(task), *_legacy_candidates(task))
    }
    requested = tuple(candidate_ids or ())
    if len(set(requested)) != len(requested) or any(name not in catalog for name in requested):
        raise ValueError("AUTOML_CONFIG_INVALID")
    return tuple(catalog[name] for name in requested) if requested else default_candidates(task)


def read_automl_dataset(path: str | Path) -> pd.DataFrame:
    return (
        pd.read_excel(path)
        if Path(path).suffix.lower() in {".xls", ".xlsx"}
        else pd.read_csv(path)
    )


def resolve_automl_feature_columns(
    frame: pd.DataFrame,
    target_column: str | None,
    requested_input_columns: Sequence[str] | None,
) -> list[str]:
    if not target_column or target_column not in frame.columns:
        raise ValueError("AutoML target column is missing")
    if requested_input_columns is None:
        return frame.drop(columns=[target_column]).select_dtypes(include=["number"]).columns.tolist()
    if not isinstance(requested_input_columns, (list, tuple)):
        raise ValueError("AutoML input columns must be a list")
    feature_columns = [str(column) for column in requested_input_columns]
    if not feature_columns:
        raise ValueError("AutoML requires at least one input column")
    if len(set(feature_columns)) != len(feature_columns):
        raise ValueError("AutoML input columns must be unique")
    if target_column in feature_columns:
        raise ValueError("AutoML target column cannot be an input column")
    missing_columns = [column for column in feature_columns if column not in frame.columns]
    if missing_columns:
        raise ValueError(f"AutoML input columns are missing: {', '.join(missing_columns)}")
    non_numeric_columns = [
        column for column in feature_columns
        if not pd.api.types.is_numeric_dtype(frame[column])
    ]
    if non_numeric_columns:
        raise ValueError(
            f"AutoML input columns must be numeric: {', '.join(non_numeric_columns)}",
        )
    return feature_columns


def _family_summary(result) -> dict:
    return {
        "algorithm_id": result.algorithm_id,
        "name": result.display_name,
        "status": result.status,
        "best_score": result.best_score,
        "auc": result.auc,
        "f1": result.f1,
        "best_params": result.best_params,
        "completed_trials": result.completed_trials,
        "pruned_trials": result.pruned_trials,
        "failed_trials": result.failed_trials,
        "training_time_seconds": result.training_time_seconds,
        "error_code": result.error_code,
        "error_message": result.error_message,
        "budget_exhausted": result.budget_exhausted,
        "trials": [
            {
                "number": trial.number,
                "state": trial.state,
                "score": trial.score,
                "auc": trial.auc,
                "f1": trial.f1,
                "accuracy": trial.accuracy,
                "params": trial.params,
                "duration_seconds": trial.duration_seconds,
                "error_code": trial.error_code,
            }
            for trial in result.trials
        ],
    }


def _persist_family_models(
    *,
    job,
    db,
    artifact_service,
    dataset,
    features,
    target,
    target_column,
    target_classes,
    evaluation,
    search_method,
    family_results,
) -> dict[str, ModelLibrary]:
    """Persist one trusted joblib source for every completed AutoML family."""
    persisted: dict[str, ModelLibrary] = {}
    feature_schema = [
        {"name": str(name), "dtype": str(features[name].dtype)}
        for name in features.columns
    ]
    target_schema = {
        "name": target_column,
        "dtype": str(target.dtype),
        "task": "classification" if target_classes else "regression",
        "classes": target_classes,
    }
    for result in family_results:
        if result.status != "completed" or result.best_estimator is None:
            continue
        with tempfile.TemporaryDirectory() as temporary:
            model_path = Path(temporary) / f"{job.id}-{result.algorithm_id}.joblib"
            joblib.dump({
                "model": result.best_estimator,
                "feature_schema": feature_schema,
                "target_schema": target_schema,
            }, model_path)
            model_artifact = artifact_service.create_from_file(
                job.project_id,
                model_path,
                f"{job.name}-{result.algorithm_id}.joblib",
                "model",
                metadata={
                    "source": "automl",
                    "training_job_id": str(job.id),
                    "dataset_artifact_id": str(dataset.id),
                    "best_algorithm": result.algorithm_id,
                    "best_score": result.best_score,
                    "best_params": result.best_params,
                    "evaluation": evaluation,
                },
            )
        persisted[result.algorithm_id] = model_artifact
    return persisted


def _execute_optuna_job(
    *,
    job,
    db,
    tracking,
    parent,
    artifact_service,
    dataset,
    features,
    target,
    target_column,
    target_classes,
    task,
    params,
    evaluation,
    dependencies: AutoMLDependencies,
) -> AutoMLExecutionResult:
    families = resolve_algorithm_families(params.get("algorithm_ids"))
    method = str(params.get("search_method", "bayesian"))
    max_trials = int(params.get("max_trials", 20))
    time_budget = int(params.get("time_budget", 600))
    planned_trials = sum(
        min(max_trials, math.prod(len(values) for values in family.grid.values()))
        if method == "grid" else max_trials
        for family in families
    )
    completed_trials = 0
    family_results = []
    all_results = []
    deadline = dependencies.monotonic() + time_budget
    job.metrics = {
        "evaluation": evaluation,
        "search": {"method": method, "max_trials": max_trials, "time_budget": time_budget, "budget_exhausted": False},
        "progress": {
            "completed": 0, "total": planned_trials, "percent": 0,
            "current_algorithm": None, "current_trial": None,
            "search_method": method, "budget_exhausted": False,
        },
        "algorithm_results": [],
        "all_results": [],
    }
    db.commit()

    for catalog_index, family in enumerate(families):
        remaining_families = len(families) - catalog_index
        remaining_seconds = deadline - dependencies.monotonic()
        if remaining_seconds <= 0:
            break

        def record_progress(progress_event) -> None:
            nonlocal completed_trials
            completed_trials += 1
            progress = {
                "completed": completed_trials,
                "total": planned_trials,
                "percent": round((completed_trials / planned_trials) * 100, 2) if planned_trials else 100,
                "current_algorithm": family.id,
                "current_trial": progress_event.trial_number + 1,
                "search_method": method,
                "budget_exhausted": False,
            }
            metrics = dict(job.metrics or {})
            metrics["progress"] = progress
            job.metrics = metrics
            job.heartbeat_at = utcnow()
            db.commit()

        def record_trial(summary: TrialSummary) -> None:
            child = tracking.start_run(
                parent.experiment_id,
                run_name=f"{family.id}-{summary.number}",
                tags={
                    "platform.algorithm_family": family.id,
                    "platform.search_method": method,
                    "platform.trial_number": summary.number,
                    "platform.trial_state": summary.state,
                    "platform.run_type": "automl_trial",
                },
                parent_run_id=parent.run_id,
            )
            tracking.log_params(child.run_id, summary.params)
            if summary.score is not None:
                tracking.log_metrics(child.run_id, {"search_score": summary.score}, step=0)
            tracking.set_tags(child.run_id, {
                "platform.duration_seconds": summary.duration_seconds,
                "platform.error_code": summary.error_code or "",
            })
            tracking.end_run(child.run_id, "FINISHED" if summary.state == "complete" else "FAILED")

        result = dependencies.family_search(
            family=family,
            task=task,
            features=features.to_numpy(),
            target=np.asarray(target),
            evaluation=evaluation,
            config=SearchConfig(
                method=method,
                max_trials=max_trials,
                timeout_seconds=remaining_seconds / remaining_families,
            ),
            catalog_index=catalog_index,
            progress_callback=record_progress,
            trial_callback=record_trial,
            monotonic=dependencies.monotonic,
        )
        family_results.append(result)
        if result.status == "completed":
            all_results.append({
                "name": result.display_name,
                "algorithm_id": result.algorithm_id,
                "score": result.best_score,
                "auc": result.auc,
                "f1": result.f1,
                "params": result.best_params,
                "training_time_seconds": result.training_time_seconds,
                "status": "completed",
            })
        metrics = dict(job.metrics or {})
        metrics["algorithm_results"] = [_family_summary(item) for item in family_results]
        metrics["all_results"] = all_results
        job.metrics = metrics
        job.heartbeat_at = utcnow()
        db.commit()

    winner = choose_family_winner(family_results)
    budget_exhausted = dependencies.monotonic() >= deadline
    if budget_exhausted and completed_trials < planned_trials:
        raise TimeoutError(
            f"AutoML time budget exhausted before all trials completed "
            f"({completed_trials}/{planned_trials} trials completed)"
        )
    all_results.sort(
        key=lambda item: automl_metric_order_key(
            auc=item.get("auc"),
            f1=item.get("f1"),
            accuracy=item.get("score"),
            duration=item.get("training_time_seconds"),
            catalog_index=next(index for index, family in enumerate(families) if family.id == item["algorithm_id"]),
        ),
    )
    persisted = _persist_family_models(
        job=job,
        db=db,
        artifact_service=artifact_service,
        dataset=dataset,
        features=features,
        target=target,
        target_column=target_column,
        target_classes=target_classes,
        evaluation=evaluation,
        search_method=method,
        family_results=family_results,
    )
    model_artifact = persisted.get(winner.algorithm_id)
    if model_artifact is None:
        raise AllCandidatesFailed("AUTOML_MODEL_PERSIST_FAILED")
    result_rows = []
    for item in all_results:
        source = persisted.get(str(item["algorithm_id"]))
        result_rows.append({**item, "model_artifact_id": str(source.id) if source else None})
    all_results = result_rows
    family_summaries = []
    for item in family_results:
        source = persisted.get(item.algorithm_id)
        summary = _family_summary(item)
        summary["model_artifact_id"] = str(source.id) if source else None
        family_summaries.append(summary)
    job.status = "completed"
    job.metrics = {
        "best_score": winner.best_score,
        "best_candidate": winner.algorithm_id,
        "evaluation": evaluation,
        "search": {"method": method, "max_trials": max_trials, "time_budget": time_budget, "budget_exhausted": budget_exhausted},
        "progress": {"completed": completed_trials, "total": planned_trials, "percent": round((completed_trials / planned_trials) * 100, 2) if planned_trials else 100, "current_algorithm": winner.algorithm_id, "current_trial": None, "search_method": method, "budget_exhausted": budget_exhausted},
        "algorithm_results": family_summaries,
        "best_model": {"algorithm_id": winner.algorithm_id, "name": winner.display_name, "score": winner.best_score, "auc": winner.auc, "f1": winner.f1, "params": winner.best_params, "model_artifact_id": str(model_artifact.id)},
        "all_results": all_results,
        "feature_importance": dict(zip(features.columns, winner.feature_importance)),
    }
    job.model_path = artifact_service.storage_reference(model_artifact)
    job.model_artifact_id = model_artifact.id
    job.model_library_id = None
    job.finished_at = utcnow()
    job.heartbeat_at = utcnow()
    tracking.log_metrics(parent.run_id, {"best_score": winner.best_score}, step=0)
    tracking.set_tags(parent.run_id, {
        "platform.best_candidate": winner.algorithm_id,
        "platform.search_method": method,
        "platform.model_artifact_id": str(model_artifact.id),
    })
    tracking.end_run(parent.run_id, "FINISHED")
    db.commit()
    return AutoMLExecutionResult(str(job.id), "completed", winner.algorithm_id)


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
            frame = read_automl_dataset(dataset_path)
        params = dict(job.params or {})
        target_column = params.get("target_column")
        task = normalize_task_type(params.get("task", "classification"))
        target_columns = list(params.get("target_columns") or [target_column])
        if task.startswith("multioutput_"):
            raise ValueError("multi-output AutoML jobs use the Task 3 search contract")
        requested_input_columns = params.get("input_columns")
        feature_columns = resolve_automl_feature_columns(
            frame,
            target_column,
            requested_input_columns,
        )
        prepared = frame.dropna(subset=[target_column, *feature_columns])
        features = prepared.loc[:, feature_columns]
        target = prepared[target_column]
        target_classes = None
        if task == "classification":
            encoder = LabelEncoder()
            target = encoder.fit_transform(target.astype(str))
            target_classes = encoder.classes_.tolist()
        if features.empty or len(features) < 10:
            raise ValueError("AutoML requires numeric features and at least ten rows")

        evaluation = normalize_evaluation_config(
            params.get("cross_validation_enabled", True),
            params.get("cross_validation_folds", 5),
        )
        params.setdefault("task_snapshot", {"task": task, "target_columns": target_columns, "random_seed": 42, "cv_strategy": "stratified" if task == "classification" else "kfold"})
        if params.get("search_contract") == "optuna_v1":
            return _execute_optuna_job(
                job=job,
                db=db,
                tracking=tracking,
                parent=parent,
                artifact_service=artifact_service,
                dataset=dataset,
                features=features,
                target=target,
                target_column=target_column,
                target_classes=target_classes,
                task=task,
                params=params,
                evaluation=evaluation,
                dependencies=dependencies,
            )

        configured_candidates = (
            tuple(candidates)
            if candidates is not None
            else resolve_candidates(task, params.get("candidate_ids"))
        )
        if not configured_candidates:
            raise ValueError("AutoML requires at least one candidate")
        scoring = "accuracy" if task == "classification" else "r2"
        scorer = get_scorer(scoring)
        cv = None
        if evaluation["cross_validation_enabled"]:
            cv = (
                StratifiedKFold(
                    n_splits=int(evaluation["cross_validation_folds"]),
                    shuffle=True,
                    random_state=42,
                )
                if task == "classification"
                else KFold(
                    n_splits=int(evaluation["cross_validation_folds"]),
                    shuffle=True,
                    random_state=42,
                )
            )
        successes = []
        candidate_results: list[dict] = []
        candidate_metrics: dict[str, tuple[float | None, float | None]] = {}
        total_candidates = len(configured_candidates)
        job.metrics = {
            "evaluation": evaluation,
            "progress": {"completed": 0, "total": total_candidates, "percent": 0},
            "all_results": [],
        }
        job.heartbeat_at = utcnow()
        db.commit()
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
                tracking.log_params(child.run_id, {**candidate.params, **evaluation})
                if cv is not None:
                    scores = cross_val_score(
                        estimator,
                        features,
                        target,
                        cv=cv,
                        scoring=scoring,
                        error_score="raise",
                    )
                    score = float(scores.mean())
                else:
                    train_features, test_features, train_target, test_target = train_test_split(
                        features,
                        target,
                        test_size=0.2,
                        random_state=42,
                        stratify=target if task == "classification" else None,
                    )
                    estimator.fit(train_features, train_target)
                    score = float(scorer(estimator, test_features, test_target))
                if not math.isfinite(score):
                    raise ValueError("Candidate score is not finite")
                auc = f1 = None
                if task == "classification":
                    try:
                        auc, f1 = classification_metrics(
                            estimator,
                            # Keep the DataFrame schema: custom estimators and
                            # feature-name-aware sklearn pipelines may require
                            # column labels during metric evaluation.
                            features=features,
                            target=np.asarray(target),
                            evaluation=evaluation,
                        )
                    except (TypeError, ValueError, RuntimeError):
                        auc, f1 = None, None
                    candidate_metrics[candidate.name] = (auc, f1)
                duration = time.perf_counter() - started
                tracking.log_metrics(child.run_id, {
                    "cv_score" if cv is not None else "holdout_score": score,
                }, step=0)
                tracking.set_tags(child.run_id, {"platform.duration_seconds": duration})
                tracking.end_run(child.run_id, "FINISHED")
                successes.append((score, index, candidate, child.run_id))
                candidate_results.append({
                    "name": candidate.name,
                    "score": score,
                    "auc": auc,
                    "f1": f1,
                    "training_time_seconds": duration,
                    "status": "completed",
                })
            except Exception as error:
                duration = time.perf_counter() - started
                tracking.set_tags(child.run_id, {
                    "platform.duration_seconds": duration,
                    "platform.error_type": type(error).__name__,
                    "platform.error_message": str(error),
                })
                tracking.end_run(child.run_id, "FAILED")
                candidate_results.append({
                    "name": candidate.name,
                    "score": None,
                    "training_time_seconds": duration,
                    "status": "failed",
                    "error_code": type(error).__name__,
                    "error_message": str(error),
                })
            completed_candidates = index + 1
            job.metrics = {
                "evaluation": evaluation,
                "progress": {
                    "completed": completed_candidates,
                    "total": total_candidates,
                    "percent": round((completed_candidates / total_candidates) * 100, 2),
                },
                "all_results": candidate_results,
            }
            job.heartbeat_at = utcnow()
            db.commit()

        if not successes:
            raise AllCandidatesFailed("All AutoML candidates failed")
        best_score, _index, best_candidate, best_child_run_id = max(
            successes,
            key=lambda item: automl_metric_sort_key(
                auc=candidate_metrics.get(item[2].name, (None, None))[0],
                f1=candidate_metrics.get(item[2].name, (None, None))[1],
                accuracy=item[0],
                duration=next(
                    result["training_time_seconds"]
                    for result in candidate_results
                    if result.get("name") == item[2].name
                ),
                catalog_index=item[1],
            ),
        )
        winner = best_candidate.factory()
        winner.fit(features, target)
        winner_auc, winner_f1 = candidate_metrics.get(best_candidate.name, (None, None))
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
                    "classes": target_classes,
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
                    "evaluation": evaluation,
                },
            )

        job.status = "completed"
        final_results = [
            result for result in candidate_results if result.get("status") == "completed"
        ]
        final_results.sort(
            key=lambda item: automl_metric_order_key(
                auc=item.get("auc"),
                f1=item.get("f1"),
                accuracy=item.get("score"),
                duration=item.get("training_time_seconds"),
                catalog_index=next(index for index, candidate in enumerate(configured_candidates) if candidate.name == item["name"]),
            ),
        )
        job.metrics = {
            "best_score": best_score,
            "best_candidate": best_candidate.name,
            "evaluation": evaluation,
            "progress": {"completed": total_candidates, "total": total_candidates, "percent": 100},
            "best_model": {
                "name": best_candidate.name,
                "score": best_score,
                "auc": winner_auc,
                "f1": winner_f1,
            },
            "all_results": final_results,
        }
        job.model_path = artifact_service.storage_reference(model_artifact)
        job.model_artifact_id = model_artifact.id
        job.model_library_id = None
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
            "AUTOML_TIME_BUDGET_EXCEEDED"
            if isinstance(error, TimeoutError)
            else
            "AUTOML_ALL_CANDIDATES_FAILED"
            if isinstance(error, AllCandidatesFailed)
            else "AUTOML_ALL_ALGORITHMS_FAILED"
            if isinstance(error, AllFamilySearchesFailed)
            else "AUTOML_FAILED"
        )
        with dependencies.session_factory() as failed_db:
            failed = failed_db.query(TrainingJob).filter(TrainingJob.id == job_uuid).first()
            if failed is not None:
                failed.status = "failed"
                failed.error_code = error_code
                failed.error_message = str(error)
                failed.error_details = {
                    "exception_type": type(error).__name__,
                    "message": str(error),
                    "budget_exhausted": isinstance(error, TimeoutError),
                }
                metrics = dict(failed.metrics or {})
                progress = dict(metrics.get("progress") or {})
                progress["budget_exhausted"] = isinstance(error, TimeoutError)
                metrics["progress"] = progress
                failed.metrics = metrics
                failed.finished_at = utcnow()
                failed_db.commit()
        return AutoMLExecutionResult(str(job_uuid), "failed", error_code=error_code)
    finally:
        db.close()
