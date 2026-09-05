"""Finite, deterministic AutoML execution with MLflow child Runs."""

import math
import tempfile
import time
import uuid
from dataclasses import dataclass
from itertools import product
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
from sklearn.base import clone
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LinearRegression, LogisticRegression
from sklearn.metrics import accuracy_score, f1_score, get_scorer, mean_squared_error, roc_auc_score
from sklearn.model_selection import KFold, StratifiedKFold, cross_val_predict, cross_val_score, train_test_split
from sklearn.multioutput import MultiOutputClassifier, MultiOutputRegressor
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import LabelEncoder, StandardScaler

from app.database import SessionLocal
from app.models.experiment import Experiment
from app.models.model_library import ModelLibrary
from app.models.training import TrainingJob
from app.services.artifact_service import build_artifact_service
from app.services.automl_catalog import AlgorithmUnavailable, resolve_algorithm_families
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
    cancellation_requested: Callable[[uuid.UUID], bool] | None = None


@dataclass(frozen=True)
class AutoMLExecutionResult:
    job_id: str
    status: str
    best_candidate: str | None = None
    error_code: str | None = None


class AllCandidatesFailed(RuntimeError):
    pass


class AutoMLCancelled(RuntimeError):
    pass


def _apply_search_strength(family, params: dict, strength: str, *, preserve_existing: bool = False) -> dict:
    values = {"light": 0.25, "balanced": 0.5, "thorough": 0.75, "maximum": 1.0}
    fraction = values[strength]
    if family.resource_parameter in family.search_space:
        spec = family.search_space[family.resource_parameter]
        if spec.kind == "int" and spec.low is not None and spec.high is not None:
            if preserve_existing and family.resource_parameter in params:
                params[family.resource_parameter] = int(float(params[family.resource_parameter]) * (0.5 + fraction / 2))
            else:
                params[family.resource_parameter] = int(spec.low + (spec.high - spec.low) * fraction)
            if spec.step:
                params[family.resource_parameter] = max(spec.low, min(spec.high, round(params[family.resource_parameter] / spec.step) * spec.step))
    return params


def _build_multioutput_trial_specs(families, *, method: str, max_trials: int, search_strength: str):
    """Build family candidates; grid uses full Cartesian parameter combinations."""
    defaults = []
    extras = []
    for family in families:
        if method == "grid":
            names = tuple(family.grid)
            combinations = product(*(family.grid[name] for name in names))
            for values in combinations:
                params = dict(zip(names, values))
                defaults.append((family, _apply_search_strength(family, params, search_strength, preserve_existing=True)))
        else:
            params = _apply_search_strength(family, dict(family.default_params), search_strength)
            defaults.append((family, params))
            for parameter, values in family.grid.items():
                for value in values:
                    candidate = dict(params)
                    candidate[parameter] = value
                    extras.append((family, candidate))
    if method in {"random", "bayesian", "evolutionary"} and extras:
        extras = [extras[index] for index in np.random.default_rng(42).permutation(len(extras))]
    specs = defaults if method == "grid" else defaults + extras
    if max_trials >= len(families) and len(families) > 1:
        grouped = {family.id: [] for family in families}
        for family, params in specs:
            grouped[family.id].append((family, params))
        selected = [grouped[family.id].pop(0) for family in families if grouped[family.id]]
        while len(selected) < max_trials and any(grouped.values()):
            for family in families:
                if grouped[family.id] and len(selected) < max_trials:
                    selected.append(grouped[family.id].pop(0))
        return selected
    return specs[:max_trials]


def _aggregate_fold_classification_metrics(target, predictions, fold_scores):
    """Compute metrics from complete out-of-fold predictions and scores."""
    target = np.asarray(target)
    predictions = np.asarray(predictions).astype(target.dtype, copy=False)
    classes = np.unique(target)
    score_rows = None
    complete_scores = bool(fold_scores)
    for test_index, scores in fold_scores:
        if scores is None:
            complete_scores = False
            continue
        values = np.asarray(scores)
        if len(classes) == 2:
            if values.ndim == 2:
                if values.shape[1] != 2:
                    complete_scores = False
                    continue
                values = values[:, 1]
            if values.ndim != 1:
                complete_scores = False
                continue
            if score_rows is None:
                score_rows = np.full(len(target), np.nan)
            score_rows[np.asarray(test_index)] = values
        else:
            if values.ndim != 2 or values.shape[1] != len(classes):
                complete_scores = False
                continue
            if score_rows is None:
                score_rows = np.full((len(target), len(classes)), np.nan)
            score_rows[np.asarray(test_index), :] = values
    auc = None
    if complete_scores and score_rows is not None and np.isfinite(score_rows).all():
        try:
            auc = float(roc_auc_score(
                target,
                score_rows,
                multi_class="ovr" if len(classes) > 2 else "raise",
                average="macro",
            ))
        except ValueError:
            auc = None
    return {
        "macro_f1": float(f1_score(target, predictions, average="macro")),
        "accuracy": float(accuracy_score(target, predictions)),
        "auc": auc,
    }


VALID_CROSS_VALIDATION_FOLDS = frozenset({2, 3, 4, 5})


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
    *,
    target_columns: Sequence[str] | None = None,
) -> list[str]:
    all_targets = [str(column) for column in (target_columns or ([target_column] if target_column else []))]
    if not all_targets or any(column not in frame.columns for column in all_targets):
        raise ValueError("AutoML target column is missing")
    if requested_input_columns is None:
        return frame.drop(columns=all_targets).select_dtypes(include=["number"]).columns.tolist()
    if not isinstance(requested_input_columns, (list, tuple)):
        raise ValueError("AutoML input columns must be a list")
    feature_columns = [str(column) for column in requested_input_columns]
    if not feature_columns:
        raise ValueError("AutoML requires at least one input column")
    if len(set(feature_columns)) != len(feature_columns):
        raise ValueError("AutoML input columns must be unique")
    if any(column in feature_columns for column in all_targets):
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


def _execute_multioutput_job(
    *,
    job,
    db,
    artifact_service,
    dataset,
    frame: pd.DataFrame,
    params: dict,
    task: str,
    parent,
    tracking,
    dependencies: AutoMLDependencies,
) -> AutoMLExecutionResult:
    """Train and persist one explicit multi-output candidate bundle."""
    from app.services.automl_search import AutoMLContract, auc_tier, iterative_stratified_splits, validate_target_columns

    target_columns = list(params.get("target_columns") or ([params.get("target_column")] if params.get("target_column") else []))
    contract = AutoMLContract(
        task_type=task,
        target_columns=target_columns,
        input_columns=params.get("input_columns"),
        cross_validation_folds=int(params.get("cross_validation_folds") or 5),
    )
    validate_target_columns(frame, task, target_columns)
    feature_columns = resolve_automl_feature_columns(
        frame,
        target_columns[0],
        params.get("input_columns"),
        target_columns=target_columns,
    )
    prepared = frame.dropna(subset=target_columns)
    features = prepared.loc[:, feature_columns]
    targets = prepared.loc[:, target_columns]
    if features.empty or len(features) < 10:
        raise ValueError("AutoML requires numeric features and at least ten rows")

    strength_estimators = {"light": 40, "balanced": 80, "thorough": 160, "maximum": 320}
    search_strength = str(params.get("search_strength", "balanced")).lower()
    if search_strength not in strength_estimators:
        raise ValueError("AUTOML_SEARCH_CONFIG_INVALID")
    deadline = dependencies.monotonic() + float(params.get("time_budget", 600))
    requested_trials = int(params.get("max_trials") or {"light": 1, "balanced": 2, "thorough": 3, "maximum": 4}[search_strength])
    method = str(params.get("search_method") or "strength")
    base_estimators = strength_estimators[search_strength]
    requested_family_ids = list(params.get("algorithm_ids") or ["random_forest"])
    families = resolve_algorithm_families(requested_family_ids)
    trial_specs = _build_multioutput_trial_specs(
        families,
        method=method,
        max_trials=requested_trials,
        search_strength=search_strength,
    )
    splits = (
        iterative_stratified_splits(targets, n_splits=contract.cross_validation_folds, random_seed=contract.random_seed)
        if task == "multioutput_classification"
        else list(KFold(contract.cross_validation_folds, shuffle=True, random_state=contract.random_seed).split(features))
    )

    def check_control():
        if dependencies.cancellation_requested:
            cancelled = dependencies.cancellation_requested(job.id)
        else:
            with dependencies.session_factory() as control_db:
                cancelled = control_db.query(TrainingJob.status).filter(
                    TrainingJob.id == job.id,
                ).scalar() == "cancel_requested"
        if cancelled:
            raise AutoMLCancelled("AutoML cancellation requested")
        if dependencies.monotonic() >= deadline:
            raise TimeoutError("AutoML time budget exceeded")
        job.heartbeat_at = utcnow()
        db.commit()

    trials = []
    runnable_specs = []
    for family, family_params in trial_specs:
        try:
            family.build(task, family_params)
            runnable_specs.append((family, family_params))
        except AlgorithmUnavailable as error:
            trials.append({
                "number": len(trials),
                "algorithm_id": family.id,
                "params": family_params,
                "score": None,
                "status": "unavailable",
                "error_code": error.code,
            })
    best = None
    budget_exhausted = False
    job.metrics = {"search": {"method": method, "max_trials": requested_trials, "completed_trials": 0, "trials": [], "budget_exhausted": False}}
    db.commit()
    for trial_index, (family, family_params) in enumerate(runnable_specs):
        try:
            check_control()
        except TimeoutError:
            budget_exhausted = True
            break
        raw_estimator = family.build(task, family_params)
        if task == "multioutput_classification" and params.get("class_weight") and "class_weight" in raw_estimator.get_params():
            raw_estimator.set_params(class_weight="balanced")
        base = make_pipeline(SimpleImputer(strategy="median"), StandardScaler(), raw_estimator)
        predictions = np.zeros((len(features), len(target_columns)), dtype=object if task == "multioutput_classification" else float)
        target_scores = {column: [] for column in target_columns}
        for train_index, test_index in splits:
            try:
                check_control()
            except TimeoutError:
                budget_exhausted = True
                break
            fold_model = MultiOutputClassifier(clone(base)) if task == "multioutput_classification" else MultiOutputRegressor(clone(base))
            fold_model.fit(features.iloc[train_index], targets.iloc[train_index])
            predictions[test_index] = fold_model.predict(features.iloc[test_index])
            if task == "multioutput_classification":
                for target_index, target_column in enumerate(target_columns):
                    fitted = fold_model.estimators_[target_index]
                    score = None
                    for score_method in ("predict_proba", "decision_function"):
                        try:
                            score = getattr(fitted, score_method)(features.iloc[test_index])
                            break
                        except (AttributeError, TypeError, ValueError):
                            continue
                    target_scores[target_column].append((np.asarray(test_index), score))
        if budget_exhausted:
            break
        per_target = {}
        for target_index, target_column in enumerate(target_columns):
            actual = targets[target_column].to_numpy()
            predicted = predictions[:, target_index]
            per_target[target_column] = (
                _aggregate_fold_classification_metrics(actual, predicted, target_scores[target_column])
                if task == "multioutput_classification"
                else {"rmse": float(np.sqrt(mean_squared_error(actual, predicted)))}
            )
        score = float(np.mean([
            item.get("auc") if item.get("auc") is not None else item.get("macro_f1", -1)
            for item in per_target.values()
        ])) if task == "multioutput_classification" else -float(np.mean([item["rmse"] for item in per_target.values()]))
        trial = {"number": len(trials), "algorithm_id": family.id, "params": family_params, "score": score, "status": "completed"}
        trials.append(trial)
        if best is None or score > best[0]:
            best = (score, family, family_params, predictions.copy(), per_target)
        completed_trials = sum(item["status"] == "completed" for item in trials)
        job.metrics = {"search": {"method": method, "max_trials": requested_trials, "completed_trials": completed_trials, "trials": trials, "budget_exhausted": False}}
        job.heartbeat_at = utcnow()
        db.commit()
    if best is None:
        if budget_exhausted:
            raise TimeoutError("AutoML time budget exceeded")
        raise AllCandidatesFailed("No multi-output trials completed")
    _best_score, best_family, best_params, predictions, per_target = best
    raw_estimator = best_family.build(task, best_params)
    if task == "multioutput_classification" and params.get("class_weight") and "class_weight" in raw_estimator.get_params():
        raw_estimator.set_params(class_weight="balanced")
    base = make_pipeline(SimpleImputer(strategy="median"), StandardScaler(), raw_estimator)
    estimator = MultiOutputClassifier(base) if task == "multioutput_classification" else MultiOutputRegressor(base)
    if not budget_exhausted:
        check_control()
    estimator.fit(features, targets)
    prediction_payload = {}
    for index, target_column in enumerate(target_columns):
        predicted = predictions[:, index]
        prediction_payload[target_column] = predicted.tolist()
    report_values = [value for value in per_target.values()]
    aggregate = {
        "macro_f1": float(np.mean([item["macro_f1"] for item in report_values if item.get("macro_f1") is not None]))
        if task == "multioutput_classification" else None,
        "accuracy": float(np.mean([item["accuracy"] for item in report_values if item.get("accuracy") is not None]))
        if task == "multioutput_classification" else None,
        "auc": float(np.mean([item["auc"] for item in report_values if item.get("auc") is not None]))
        if task == "multioutput_classification" and all(item.get("auc") is not None for item in report_values) else None,
        "rmse": float(np.mean([item["rmse"] for item in report_values])) if task != "multioutput_classification" else None,
    }
    algorithm_id = best_family.id if params.get("algorithm_ids") else "multioutput_random_forest"
    input_contract = {
        "task_type": task,
        "target_columns": target_columns,
        "input_columns": feature_columns,
        "cross_validation_folds": contract.cross_validation_folds,
        "random_seed": contract.random_seed,
    }
    preprocessing = {"feature_columns": feature_columns, "steps": ["median_imputation", "standard_scaling"], "fold_local": True}
    feature_schema = [{"name": str(name), "dtype": str(features[name].dtype)} for name in features.columns]
    target_schema = [{"name": name, "dtype": str(targets[name].dtype)} for name in target_columns]
    with tempfile.TemporaryDirectory() as temporary:
        model_path = Path(temporary) / f"{job.id}-multioutput.joblib"
        joblib.dump({
            "model": estimator,
            "feature_schema": feature_schema,
            "target_schema": target_schema,
            "input_contract": input_contract,
            "preprocessing": preprocessing,
        }, model_path)
        model_artifact = artifact_service.create_from_file(
            job.project_id,
            model_path,
            f"{job.name}-{algorithm_id}.joblib",
            "model",
            metadata={
                "source": "automl",
                "training_job_id": str(job.id),
                "dataset_artifact_id": str(dataset.id),
                "best_algorithm": algorithm_id,
                "best_candidate": algorithm_id,
                "candidate_id": algorithm_id,
                "input_contract": input_contract,
            },
        )

    job.metrics = {
        "task_type": task,
        "best_candidate": algorithm_id,
        "best_algorithm": algorithm_id,
        "best_model": {"algorithm_id": algorithm_id, "model_artifact_id": str(model_artifact.id), "aggregate": aggregate},
        "algorithm_results": [{
            "algorithm_id": algorithm_id,
            "name": algorithm_id,
            "status": "completed",
            "model_artifact_id": str(model_artifact.id),
            "per_target": per_target,
            "aggregate": aggregate,
        }],
        "per_target": per_target,
        "predictions": prediction_payload,
        "aggregate": aggregate,
        "cv_strategy": "iterative_stratified" if task == "multioutput_classification" else "kfold",
        "input_contract": input_contract,
        "preprocessing": preprocessing,
        "search": {
            "method": params.get("search_method", "default"),
            "strength": params.get("search_strength", "balanced"),
            "time_budget": params.get("time_budget", 600),
            "class_weight": bool(params.get("class_weight", False)),
            "n_estimators": base_estimators,
            "selected_algorithm": best_family.id,
            "selected_params": best_params,
            "selected_n_estimators": best_params.get("n_estimators"),
            "max_trials": requested_trials,
            "completed_trials": sum(item["status"] == "completed" for item in trials),
            "trials": trials,
            "budget_exhausted": budget_exhausted,
        },
        "prediction_source": "cross_validation",
        "auc_tier": auc_tier({name: item.get("auc") for name, item in per_target.items()}),
    }
    job.feature_schema = feature_schema
    job.target_schema = target_schema
    job.preprocessing = preprocessing
    job.automl_contract = {**(job.automl_contract or {}), **input_contract}
    job.model_path = artifact_service.storage_reference(model_artifact)
    job.model_artifact_id = model_artifact.id
    job.model_library_id = None
    job.status = "completed"
    job.finished_at = utcnow()
    job.heartbeat_at = utcnow()
    tracking.set_tags(parent.run_id, {
        "platform.best_candidate": algorithm_id,
        "platform.best_algorithm": algorithm_id,
        "platform.model_artifact_id": str(model_artifact.id),
    })
    tracking.end_run(parent.run_id, "FINISHED")
    db.commit()
    return AutoMLExecutionResult(str(job.id), "completed", algorithm_id)


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
            return _execute_multioutput_job(
                job=job,
                db=db,
                artifact_service=artifact_service,
                dataset=dataset,
                frame=frame,
                params=params,
                task=task,
                parent=parent,
                tracking=tracking,
                dependencies=dependencies,
            )
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
            "AUTOML_CANCELLED"
            if isinstance(error, AutoMLCancelled)
            else
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
                failed.status = "cancelled" if isinstance(error, AutoMLCancelled) else "failed"
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
                search = dict(metrics.get("search") or {})
                search["budget_exhausted"] = isinstance(error, TimeoutError)
                metrics["search"] = search
                failed.metrics = metrics
                failed.finished_at = utcnow()
                failed_db.commit()
        return AutoMLExecutionResult(
            str(job_uuid),
            "cancelled" if isinstance(error, AutoMLCancelled) else "failed",
            error_code=error_code,
        )
    finally:
        db.close()
