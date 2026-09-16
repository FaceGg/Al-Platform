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
from sklearn.metrics import (
    accuracy_score,
    f1_score,
    get_scorer,
    mean_absolute_error,
    mean_squared_error,
    r2_score,
    roc_auc_score,
)
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
    CandidateSummary,
    SearchConfig,
    TrialSummary,
    automl_metric_order_key,
    automl_metric_sort_key,
    classification_metrics,
    choose_family_winner,
    rank_candidates,
    run_family_search,
    normalize_task_type,
    SEARCH_STRENGTH_TRIALS,
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


def _rank_multioutput_trials(trials: Sequence[dict], task_type: str) -> list[dict]:
    """Apply the canonical candidate ranking contract to worker trial records."""
    completed = [trial for trial in trials if trial.get("status") == "completed"]
    pending = [trial for trial in trials if trial.get("status") != "completed"]
    summaries: list[CandidateSummary] = []
    for trial in completed:
        aggregate = trial.get("aggregate")
        aggregate = aggregate if isinstance(aggregate, dict) else {}
        summaries.append(CandidateSummary(
            algorithm_id=str(trial.get("algorithm_id") or ""),
            auc=aggregate.get("auc"),
            macro_f1=aggregate.get("macro_f1"),
            accuracy=aggregate.get("accuracy"),
            runtime_s=float(trial.get("training_time_seconds", trial.get("runtime_s", float("inf")))),
            r2=aggregate.get("r2"),
            rmse=aggregate.get("rmse"),
            mae=aggregate.get("mae"),
        ))
    ranked_summaries = rank_candidates(summaries, task_type)
    by_summary = {id(summary): trial for summary, trial in zip(summaries, completed)}
    return [by_summary[id(summary)] for summary in ranked_summaries] + pending


def _aggregate_multioutput_metrics(task: str, per_target: dict[str, dict[str, float | None]]) -> dict[str, float | None]:
    """Aggregate per-target reports without changing the task-specific metric contract."""
    values = list(per_target.values())
    if task == "multioutput_classification":
        auc_values = [item.get("auc") for item in values if item.get("auc") is not None]
        return {
            "macro_f1": float(np.mean([item["macro_f1"] for item in values])),
            "accuracy": float(np.mean([item["accuracy"] for item in values])),
            "auc": float(np.mean(auc_values)) if len(auc_values) == len(values) and values else None,
        }
    return {
        "r2": float(np.mean([item["r2"] for item in values])),
        "rmse": float(np.mean([item["rmse"] for item in values])),
        "mae": float(np.mean([item["mae"] for item in values])),
    }


def _build_multioutput_estimator(task: str, family, family_params: dict, *, class_weight: bool):
    """Build the fold-wrapped estimator used both for CV and candidate artifacts."""
    raw_estimator = family.build(task, family_params)
    if task == "multioutput_classification" and class_weight and "class_weight" in raw_estimator.get_params():
        raw_estimator.set_params(class_weight="balanced")
    base = make_pipeline(SimpleImputer(strategy="median"), StandardScaler(), raw_estimator)
    return MultiOutputClassifier(base) if task == "multioutput_classification" else MultiOutputRegressor(base)


def _apply_search_strength(family, params: dict, strength: str, *, preserve_existing: bool = False) -> dict:
    values = {"light": 0.25, "medium": 0.5, "high": 0.75, "ultra": 1.0}
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
    """Build a bounded task-level trial plan while covering every family."""
    if max_trials < len(families):
        raise ValueError("AUTOML_SEARCH_CONFIG_INVALID")
    if method not in {"strength", "grid", "random", "bayesian", "evolutionary", "multi_fidelity"}:
        raise ValueError("AUTOML_SEARCH_CONFIG_INVALID")

    def sample_value(spec, rng):
        if spec.kind == "categorical":
            return spec.choices[int(rng.integers(0, len(spec.choices)))]
        if spec.kind == "int":
            low, high = int(spec.low), int(spec.high)
            step = int(spec.step or 1)
            return int(rng.integers(low, high + 1)) // step * step
        if spec.kind == "float":
            low, high = float(spec.low), float(spec.high)
            if spec.log:
                return float(np.exp(rng.uniform(np.log(low), np.log(high))))
            return float(rng.uniform(low, high))
        raise ValueError("AUTOML_SEARCH_CONFIG_INVALID")

    grouped = {family.id: [] for family in families}
    for family in families:
        if method == "grid":
            names = tuple(family.grid)
            combinations = product(*(family.grid[name] for name in names))
            for values in combinations:
                params = dict(zip(names, values))
                grouped[family.id].append((family, _apply_search_strength(family, params, search_strength, preserve_existing=True)))
        else:
            rng = np.random.default_rng(42 + list(families).index(family))
            previous = _apply_search_strength(family, dict(family.default_params), search_strength)
            grouped[family.id].append((family, dict(previous)))
            if method == "strength":
                continue
            for trial_no in range(1, max_trials):
                candidate = dict(previous)
                if method == "multi_fidelity":
                    rungs = tuple(sorted({
                        max(family.min_resource, min(family.max_resource, int(family.max_resource * fraction)))
                        for fraction in (0.25, 0.5, 1.0)
                    }))
                    candidate[family.resource_parameter] = rungs[(trial_no - 1) % len(rungs)]
                elif method == "evolutionary":
                    parameter = list(family.search_space)[(trial_no - 1) % len(family.search_space)]
                    candidate[parameter] = sample_value(family.search_space[parameter], rng)
                elif method == "bayesian":
                    # Deterministic exploitation around the default, then exploration.
                    parameter = list(family.search_space)[(trial_no - 1) % len(family.search_space)]
                    spec = family.search_space[parameter]
                    candidate[parameter] = sample_value(spec, rng)
                else:  # random
                    for parameter, spec in family.search_space.items():
                        candidate[parameter] = sample_value(spec, rng)
                candidate = _apply_search_strength(family, candidate, search_strength, preserve_existing=True)
                grouped[family.id].append((family, candidate))
    selected = [grouped[family.id].pop(0) for family in families if grouped[family.id]]
    while len(selected) < max_trials and any(grouped.values()):
        for family in families:
            if grouped[family.id] and len(selected) < max_trials:
                selected.append(grouped[family.id].pop(0))
    return selected


def _aggregate_fold_classification_metrics(target, predictions, fold_scores):
    """Compute metrics from complete out-of-fold predictions and scores."""
    target = np.asarray(target)
    predictions = np.asarray(predictions).astype(target.dtype, copy=False)
    classes = np.unique(target)
    score_rows = None
    complete_scores = bool(fold_scores)
    for fold_score in fold_scores:
        if len(fold_score) == 2:
            test_index, scores = fold_score
            fold_classes = None
        else:
            test_index, scores, fold_classes = fold_score[:3]
        if scores is None:
            complete_scores = False
            continue
        values = np.asarray(scores)
        if fold_classes is not None:
            fold_classes = np.asarray(fold_classes)
            expected_class_count = values.shape[1] if values.ndim == 2 else len(classes)
            if len(fold_classes) != expected_class_count:
                complete_scores = False
                continue
            if values.ndim == 2:
                positions = []
                for label in classes:
                    matches = np.flatnonzero(fold_classes == label)
                    if len(matches) != 1:
                        complete_scores = False
                        positions = []
                        break
                    positions.append(int(matches[0]))
                if not positions:
                    continue
                values = values[:, positions]
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


def _native_feature_importance(estimator, expected_width: int) -> list[float]:
    """Read native importances through a preprocessing pipeline when present."""
    steps = getattr(estimator, "steps", None)
    if steps:
        estimator = steps[-1][1]
    values = getattr(estimator, "feature_importances_", None)
    if values is None:
        values = getattr(estimator, "coef_", None)
    if values is None:
        return []
    array = np.asarray(values, dtype=float)
    if array.ndim > 1:
        array = np.mean(np.abs(array), axis=0)
    else:
        array = np.abs(array)
    if array.ndim != 1 or len(array) != expected_width or not np.isfinite(array).all():
        return []
    total = float(array.sum())
    if total <= 0:
        return []
    return (array / total).tolist()


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
    task_type = "classification" if target_classes is not None else "regression"
    input_contract = {
        "task_type": task_type,
        "target_columns": [target_column],
        "input_columns": [str(name) for name in features.columns],
        "cross_validation_enabled": bool(evaluation.get("cross_validation_enabled", True)),
        "cross_validation_folds": evaluation.get("cross_validation_folds"),
        "random_seed": 42,
        "missing_policy": "drop_rows_before_training",
    }
    # Single-output estimators currently receive the already validated numeric
    # frame directly. Persist that fact explicitly so consumers do not infer a
    # hidden imputer/scaler from an artifact that does not contain one.
    preprocessing = {
        "version": "automl-v1",
        "feature_columns": [str(name) for name in features.columns],
        "steps": ["drop_rows_before_training"],
        "fold_local": False,
    }
    for result in family_results:
        if result.status != "completed" or result.best_estimator is None:
            continue
        importance = _native_feature_importance(result.best_estimator, len(features.columns))
        feature_importance = {
            str(name): float(importance[index])
            for index, name in enumerate(features.columns)
        } if importance else {}
        feature_importance_report = {
            "source": "model_native" if importance else "unavailable",
            "by_feature": feature_importance,
            "per_target": {target_column: feature_importance},
            "unavailable_targets": [] if importance else [target_column],
        }
        with tempfile.TemporaryDirectory() as temporary:
            model_path = Path(temporary) / f"{job.id}-{result.algorithm_id}.joblib"
            joblib.dump({
                "model": result.best_estimator,
                "feature_schema": feature_schema,
                "target_schema": target_schema,
                "input_contract": input_contract,
                "preprocessing": preprocessing,
                "feature_importance": feature_importance,
                "feature_importance_report": feature_importance_report,
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
                    "input_contract": input_contract,
                    "preprocessing": preprocessing,
                    "feature_importance_report": feature_importance_report,
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
    time_budget = int(params.get("time_budget", 3600))
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
        if dependencies.cancellation_requested and dependencies.cancellation_requested(job.id):
            raise AutoMLCancelled("AutoML cancellation requested")
        with dependencies.session_factory() as control_db:
            if control_db.query(TrainingJob.status).filter(
                TrainingJob.id == job.id,
            ).scalar() == "cancel_requested":
                raise AutoMLCancelled("AutoML cancellation requested")
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
        if dependencies.cancellation_requested and dependencies.cancellation_requested(job.id):
            raise AutoMLCancelled("AutoML cancellation requested")
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
    feature_schema = [
        {"name": str(name), "dtype": str(features[name].dtype)}
        for name in features.columns
    ]
    target_schema = {
        "name": str(target_column),
        "dtype": str(target.dtype),
        "task": task,
        "classes": target_classes,
    }
    input_contract = {
        "task_type": task,
        "target_columns": [str(target_column)],
        "input_columns": [item["name"] for item in feature_schema],
        "feature_schema": feature_schema,
        "target_schema": target_schema,
        "cross_validation_enabled": bool(evaluation.get("cross_validation_enabled", True)),
        "cross_validation_folds": evaluation.get("cross_validation_folds"),
        "random_seed": 42,
        "missing_policy": {
            "features": "drop_rows_before_training",
            "target": "reject_missing",
        },
    }
    preprocessing = {
        "version": "automl-v1",
        "feature_columns": [item["name"] for item in feature_schema],
        "steps": ["drop_rows_before_training"],
        "fold_local": False,
    }
    winner_importance = _native_feature_importance(winner.best_estimator, len(feature_schema))
    feature_importance = {
        str(name): float(winner_importance[index])
        for index, name in enumerate(features.columns)
    } if winner_importance else {}
    feature_importance_report = {
        "source": "model_native" if winner_importance else "unavailable",
        "by_feature": feature_importance,
        "per_target": {str(target_column): feature_importance},
        "unavailable_targets": [] if winner_importance else [str(target_column)],
    }
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
        "feature_importance": feature_importance,
        "feature_importance_report": feature_importance_report,
        "input_contract": input_contract,
        "preprocessing": preprocessing,
        "feature_schema": feature_schema,
        "target_schema": target_schema,
    }
    job.feature_schema = feature_schema
    job.target_schema = target_schema
    job.preprocessing = preprocessing
    job.automl_contract = {**(job.automl_contract or {}), **input_contract}
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

    strength_estimators = {"light": 40, "medium": 80, "high": 160, "ultra": 320}
    search_strength = str(params.get("search_strength", "medium")).lower()
    if search_strength not in strength_estimators:
        raise ValueError("AUTOML_SEARCH_CONFIG_INVALID")
    deadline = dependencies.monotonic() + float(params.get("time_budget", 3600))
    requested_trials = int(params.get("max_trials") or SEARCH_STRENGTH_TRIALS[search_strength])
    method = str(params.get("search_method") or "strength")
    base_estimators = strength_estimators[search_strength]
    requested_family_ids = list(params.get("algorithm_ids") or ["random_forest"])
    families = resolve_algorithm_families(requested_family_ids)
    trial_specs = (
        _build_multioutput_trial_specs(
            families,
            method=method,
            max_trials=requested_trials,
            search_strength=search_strength,
        )
        if method in {"strength", "grid"}
        else []
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
    budget_exhausted = False
    completed_candidates: list[dict[str, object]] = []
    job.metrics = {"search": {"method": method, "max_trials": requested_trials, "completed_trials": 0, "trials": [], "budget_exhausted": False}}
    db.commit()

    def evaluate_candidate(base):
        predictions = np.zeros(
            (len(features), len(target_columns)),
            dtype=object if task == "multioutput_classification" else float,
        )
        target_scores = {column: [] for column in target_columns}
        for train_index, test_index in splits:
            check_control()
            fold_model = clone(base)
            fold_model.fit(features.iloc[train_index], targets.iloc[train_index])
            predictions[test_index] = fold_model.predict(features.iloc[test_index])
            if task == "multioutput_classification":
                for target_index, target_column in enumerate(target_columns):
                    fitted = fold_model.estimators_[target_index]
                    continuous_score = None
                    for score_method in ("predict_proba", "decision_function"):
                        try:
                            continuous_score = getattr(fitted, score_method)(features.iloc[test_index])
                            break
                        except (AttributeError, TypeError, ValueError):
                            continue
                    target_scores[target_column].append((
                        np.asarray(test_index),
                        continuous_score,
                        getattr(fitted, "classes_", None),
                    ))
        per_target = {}
        for target_index, target_column in enumerate(target_columns):
            actual = targets[target_column].to_numpy()
            predicted = predictions[:, target_index]
            per_target[target_column] = (
                _aggregate_fold_classification_metrics(actual, predicted, target_scores[target_column])
                if task == "multioutput_classification"
                else {
                    "r2": float(r2_score(actual, predicted)),
                    "rmse": float(np.sqrt(mean_squared_error(actual, predicted))),
                    "mae": float(mean_absolute_error(actual, predicted)),
                }
            )
        aggregate = _aggregate_multioutput_metrics(task, per_target)
        score = (
            float(aggregate["auc"] if aggregate.get("auc") is not None else aggregate["macro_f1"])
            if task == "multioutput_classification"
            else float(aggregate["r2"])
        )
        return score, predictions, per_target, aggregate

    if method in {"random", "bayesian", "evolutionary", "multi_fidelity"}:
        base_trials, extra_trials = divmod(requested_trials, len(families))
        for family_index, family in enumerate(families):
            family_trial_count = base_trials + (1 if family_index < extra_trials else 0)
            if family_trial_count < 1:
                continue
            remaining_seconds = max(0.001, deadline - dependencies.monotonic())
            persisted_trial_rows: list[dict] = []

            def on_trial(summary: TrialSummary, *, current_family=family):
                row = {
                    "number": len(trials),
                    "family_trial_number": summary.number,
                    "algorithm_id": current_family.id,
                    "params": summary.params,
                    "score": summary.score,
                    "status": summary.state,
                    "training_time_seconds": summary.duration_seconds,
                    "error_code": summary.error_code,
                    "intermediate_scores": summary.intermediate_scores,
                }
                trials.append(row)
                persisted_trial_rows.append(row)
                job.metrics = {
                    "search": {
                        "method": method,
                        "max_trials": requested_trials,
                        "completed_trials": sum(item["status"] == "complete" for item in trials),
                        "trials": trials,
                        "budget_exhausted": False,
                    },
                }
                job.heartbeat_at = utcnow()
                db.commit()

            try:
                family_result = dependencies.family_search(
                    family=family,
                    task=task,
                    features=features.to_numpy(),
                    target=targets.to_numpy(),
                    evaluation={"cross_validation_enabled": True, "cross_validation_folds": contract.cross_validation_folds},
                    config=SearchConfig(method=method, max_trials=family_trial_count, timeout_seconds=remaining_seconds),
                    catalog_index=family_index,
                    trial_callback=on_trial,
                    estimator_builder=lambda current_family, _task, trial_params: _build_multioutput_estimator(
                        task,
                        current_family,
                        _apply_search_strength(current_family, dict(trial_params), search_strength, preserve_existing=True),
                        class_weight=bool(params.get("class_weight", True)),
                    ),
                    estimator_evaluator=lambda estimator, **_kwargs: evaluate_candidate(estimator)[0],
                    monotonic=dependencies.monotonic,
                )
            except (AutoMLCancelled, TimeoutError):
                raise
            except Exception as error:
                trials.append({
                    "number": len(trials),
                    "algorithm_id": family.id,
                    "params": {},
                    "score": None,
                    "status": "failed",
                    "training_time_seconds": 0.0,
                    "error_code": "AUTOML_CANDIDATE_FAILED",
                    "error_type": type(error).__name__,
                    "error_message": str(error),
                })
                continue
            budget_exhausted = budget_exhausted or family_result.budget_exhausted
            if family_result.status != "completed" or family_result.best_estimator is None:
                if not persisted_trial_rows:
                    trials.append({
                        "number": len(trials),
                        "algorithm_id": family.id,
                        "params": {},
                        "score": None,
                        "status": family_result.status,
                        "training_time_seconds": family_result.training_time_seconds,
                        "error_code": family_result.error_code,
                        "error_message": family_result.error_message,
                    })
                continue
            actual_params = _apply_search_strength(
                family, dict(family_result.best_params), search_strength, preserve_existing=True,
            )
            score, predictions, per_target, aggregate = evaluate_candidate(family_result.best_estimator)
            completed_trial = {
                "number": len(trials),
                "algorithm_id": family.id,
                "params": actual_params,
                "score": score,
                "status": "completed",
                "per_target": per_target,
                "aggregate": aggregate,
                "training_time_seconds": family_result.training_time_seconds,
            }
            completed_candidates.append({
                "trial": completed_trial,
                "family": family,
                "params": actual_params,
                "predictions": predictions,
                "per_target": per_target,
                "aggregate": aggregate,
            })
            if dependencies.monotonic() >= deadline:
                budget_exhausted = True
                break
    for trial_index, (family, family_params) in enumerate(runnable_specs):
        try:
            check_control()
        except TimeoutError:
            budget_exhausted = True
            break
        trial_started = time.perf_counter()
        try:
            base = _build_multioutput_estimator(
                task,
                family,
                family_params,
                class_weight=bool(params.get("class_weight", True)),
            )
            predictions = np.zeros((len(features), len(target_columns)), dtype=object if task == "multioutput_classification" else float)
            target_scores = {column: [] for column in target_columns}
            for train_index, test_index in splits:
                try:
                    check_control()
                except TimeoutError:
                    budget_exhausted = True
                    break
                fold_model = clone(base)
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
                        target_scores[target_column].append((
                            np.asarray(test_index),
                            score,
                            getattr(fitted, "classes_", None),
                        ))
        except (AutoMLCancelled, TimeoutError):
            raise
        except Exception as error:
            # A broken estimator must only consume its own trial. Keep the
            # failure visible in the persisted search record and continue with
            # the next family/parameter combination.
            training_time_seconds = time.perf_counter() - trial_started
            trials.append({
                "number": len(trials),
                "algorithm_id": family.id,
                "params": family_params,
                "score": None,
                "status": "failed",
                "training_time_seconds": training_time_seconds,
                "error_code": "AUTOML_CANDIDATE_FAILED",
                "error_type": type(error).__name__,
                "error_message": str(error),
            })
            job.metrics = {
                "search": {
                    "method": method,
                    "max_trials": requested_trials,
                    "completed_trials": sum(item["status"] == "completed" for item in trials),
                    "failed_trials": sum(item["status"] == "failed" for item in trials),
                    "trials": trials,
                    "budget_exhausted": False,
                },
            }
            job.heartbeat_at = utcnow()
            db.commit()
            continue
        if budget_exhausted:
            break
        per_target = {}
        for target_index, target_column in enumerate(target_columns):
            actual = targets[target_column].to_numpy()
            predicted = predictions[:, target_index]
            per_target[target_column] = (
                _aggregate_fold_classification_metrics(actual, predicted, target_scores[target_column])
                if task == "multioutput_classification"
                else {
                    "r2": float(r2_score(actual, predicted)),
                    "rmse": float(np.sqrt(mean_squared_error(actual, predicted))),
                    "mae": float(mean_absolute_error(actual, predicted)),
                }
            )
        aggregate = _aggregate_multioutput_metrics(task, per_target)
        score = (
            float(aggregate["auc"] if aggregate.get("auc") is not None else aggregate["macro_f1"])
            if task == "multioutput_classification"
            else float(aggregate["r2"])
        )
        training_time_seconds = time.perf_counter() - trial_started
        trial = {
            "number": len(trials),
            "algorithm_id": family.id,
            "params": family_params,
            "score": score,
            "status": "completed",
            "per_target": per_target,
            "aggregate": aggregate,
            "training_time_seconds": training_time_seconds,
        }
        trials.append(trial)
        completed_candidates.append({
            "trial": trial,
            "family": family,
            "params": family_params,
            "predictions": predictions.copy(),
            "per_target": per_target,
            "aggregate": aggregate,
        })
        completed_trials = sum(item["status"] == "completed" for item in trials)
        job.metrics = {"search": {"method": method, "max_trials": requested_trials, "completed_trials": completed_trials, "trials": trials, "budget_exhausted": False}}
        job.heartbeat_at = utcnow()
        db.commit()
    if not completed_candidates:
        if budget_exhausted:
            raise TimeoutError("AutoML time budget exceeded")
        raise AllCandidatesFailed("No multi-output trials completed")
    ranked_trials = _rank_multioutput_trials(
        [candidate["trial"] for candidate in completed_candidates],
        task,
    )
    best_trial = ranked_trials[0]
    best_candidate = next(
        candidate for candidate in completed_candidates if candidate["trial"] is best_trial
    )
    best_family = best_candidate["family"]
    best_params = best_candidate["params"]
    predictions = best_candidate["predictions"]
    per_target = best_candidate["per_target"]
    aggregate = best_candidate["aggregate"]
    estimator = _build_multioutput_estimator(
        task,
        best_family,
        best_params,
        class_weight=bool(params.get("class_weight", True)),
    )
    if not budget_exhausted:
        check_control()
    estimator.fit(features, targets)
    budget_exhausted = budget_exhausted or dependencies.monotonic() >= deadline
    prediction_payload = {}
    for index, target_column in enumerate(target_columns):
        predicted = predictions[:, index]
        prediction_payload[target_column] = predicted.tolist()
    winner_family_id = best_family.id
    algorithm_id = winner_family_id if params.get("algorithm_ids") else f"multioutput_{winner_family_id}"
    input_contract = {
        "task_type": task,
        "target_columns": target_columns,
        "input_columns": feature_columns,
        "cross_validation_folds": contract.cross_validation_folds,
        "random_seed": contract.random_seed,
    }
    preprocessing = {"feature_columns": feature_columns, "steps": ["median_imputation", "standard_scaling"], "fold_local": True}
    feature_schema = [{"name": str(name), "dtype": str(features[name].dtype)} for name in features.columns]
    target_schema = [
        {
            "name": name,
            "dtype": str(targets[name].dtype),
            "task": task,
            "classes": sorted(targets[name].dropna().unique().tolist(), key=str)
            if task == "multioutput_classification" else [],
        }
        for name in target_columns
    ]
    per_target_importance: dict[str, dict[str, float]] = {}
    importance_vectors: list[np.ndarray] = []
    for target_index, target_column in enumerate(target_columns):
        vector = _native_feature_importance(estimator.estimators_[target_index], len(feature_columns))
        if vector:
            values = np.asarray(vector, dtype=float)
            importance_vectors.append(values)
            per_target_importance[target_column] = {
                name: float(values[index]) for index, name in enumerate(feature_columns)
            }
        else:
            per_target_importance[target_column] = {}
    if importance_vectors:
        aggregate_importance = np.mean(np.vstack(importance_vectors), axis=0)
        aggregate_importance = aggregate_importance / aggregate_importance.sum()
        feature_importance = {
            name: float(aggregate_importance[index]) for index, name in enumerate(feature_columns)
        }
        feature_importance_source = "model_native"
    else:
        feature_importance = {}
        feature_importance_source = "unavailable"
    feature_importance_report = {
        "source": feature_importance_source,
        "by_feature": feature_importance,
        "per_target": per_target_importance,
        "unavailable_targets": [name for name, values in per_target_importance.items() if not values],
    }
    persisted_candidates = {}
    seen_candidate_bases: set[str] = set()
    for candidate in completed_candidates:
        family_id = candidate["family"].id
        base_candidate_id = family_id if params.get("algorithm_ids") else f"multioutput_{family_id}"
        if candidate is best_candidate:
            candidate_id = algorithm_id
        elif base_candidate_id in seen_candidate_bases or base_candidate_id == algorithm_id:
            candidate_id = f"{base_candidate_id}#trial-{candidate['trial']['number']}"
        else:
            candidate_id = base_candidate_id
        candidate["candidate_id"] = candidate_id
        seen_candidate_bases.add(base_candidate_id)
    for candidate in completed_candidates:
        candidate_family = candidate["family"]
        candidate_params = candidate["params"]
        family_id = candidate_family.id
        candidate_id = candidate["candidate_id"]
        candidate_model = _build_multioutput_estimator(
            task,
            candidate_family,
            candidate_params,
            class_weight=bool(params.get("class_weight", True)),
        )
        if candidate_id == winner_family_id:
            candidate_model = estimator
        else:
            candidate_model.fit(features, targets)
        candidate_target_importance: dict[str, dict[str, float]] = {}
        candidate_vectors: list[np.ndarray] = []
        for target_index, target_column in enumerate(target_columns):
            vector = _native_feature_importance(candidate_model.estimators_[target_index], len(feature_columns))
            if vector:
                values = np.asarray(vector, dtype=float)
                candidate_vectors.append(values)
                candidate_target_importance[target_column] = {name: float(values[index]) for index, name in enumerate(feature_columns)}
            else:
                candidate_target_importance[target_column] = {}
        if candidate_vectors:
            candidate_aggregate = np.mean(np.vstack(candidate_vectors), axis=0)
            candidate_aggregate = candidate_aggregate / candidate_aggregate.sum()
            candidate_feature_importance = {name: float(candidate_aggregate[index]) for index, name in enumerate(feature_columns)}
            candidate_importance_source = "model_native"
        else:
            candidate_feature_importance = {}
            candidate_importance_source = "unavailable"
        candidate_feature_importance_report = {
            "source": candidate_importance_source,
            "by_feature": candidate_feature_importance,
            "per_target": candidate_target_importance,
            "unavailable_targets": [name for name, values in candidate_target_importance.items() if not values],
        }
        with tempfile.TemporaryDirectory() as temporary:
            model_path = Path(temporary) / f"{job.id}-{candidate_id}-multioutput.joblib"
            joblib.dump({
                "model": candidate_model,
                "feature_schema": feature_schema,
                "target_schema": target_schema,
                "input_contract": input_contract,
                "preprocessing": preprocessing,
                "feature_importance": candidate_feature_importance,
                "feature_importance_report": candidate_feature_importance_report,
            }, model_path)
            model_artifact = artifact_service.create_from_file(
                job.project_id,
                model_path,
                f"{job.name}-{candidate_id}.joblib",
                "model",
                metadata={
                    "source": "automl",
                    "training_job_id": str(job.id),
                    "dataset_artifact_id": str(dataset.id),
                    "best_algorithm": family_id,
                    "best_candidate": candidate_id,
                    "candidate_id": candidate_id,
                    "input_contract": input_contract,
                },
            )
        persisted_candidates[candidate_id] = model_artifact
        candidate["trial"]["model_artifact_id"] = str(model_artifact.id)
    model_artifact = persisted_candidates[best_candidate["candidate_id"]]

    candidate_result_rows = [
        {
            "algorithm_id": candidate["candidate_id"],
            "name": candidate["candidate_id"],
            "status": "completed",
            "model_artifact_id": candidate["trial"]["model_artifact_id"],
            "per_target": candidate["per_target"],
            "aggregate": candidate["aggregate"],
            "params": candidate["params"],
            "training_time_seconds": candidate["trial"]["training_time_seconds"],
        }
        for candidate in completed_candidates
    ]
    completed_trial_numbers = {
        int(candidate["trial"]["number"])
        for candidate in completed_candidates
    }
    existing_result_ids = {str(row["algorithm_id"]) for row in candidate_result_rows}
    for trial in trials:
        if trial.get("status") == "completed" or int(trial.get("number", -1)) in completed_trial_numbers:
            continue
        candidate_result_id = str(trial.get("algorithm_id") or f"trial-{trial.get('number')}")
        if candidate_result_id in existing_result_ids:
            candidate_result_id = f"{candidate_result_id}#trial-{trial.get('number')}"
        existing_result_ids.add(candidate_result_id)
        candidate_result_rows.append({
            "algorithm_id": candidate_result_id,
            "name": candidate_result_id,
            "status": trial.get("status", "failed"),
            "params": trial.get("params", {}),
            "score": trial.get("score"),
            "training_time_seconds": trial.get("training_time_seconds", 0.0),
            "error_code": trial.get("error_code"),
            "error_type": trial.get("error_type"),
            "error_message": trial.get("error_message"),
        })
    job.metrics = {
        "task_type": task,
        "best_candidate": algorithm_id,
        "best_algorithm": algorithm_id,
        "best_model": {"algorithm_id": winner_family_id, "model_artifact_id": str(model_artifact.id), "aggregate": aggregate},
        "algorithm_results": candidate_result_rows,
        "all_results": candidate_result_rows,
        "per_target": per_target,
        "predictions": prediction_payload,
        "aggregate": aggregate,
        "feature_importance": feature_importance,
        "feature_importance_report": feature_importance_report,
        "cv_strategy": "iterative_stratified" if task == "multioutput_classification" else "kfold",
        "input_contract": input_contract,
        "preprocessing": preprocessing,
        "search": {
            "method": params.get("search_method", "default"),
            "strength": params.get("search_strength", "medium"),
            "time_budget": params.get("time_budget", 3600),
            "class_weight": bool(params.get("class_weight", True)),
            "n_estimators": base_estimators,
            "selected_algorithm": best_family.id,
            "selected_params": best_params,
            "selected_n_estimators": best_params.get("n_estimators"),
            "max_trials": requested_trials,
            "completed_trials": sum(item["status"] in {"complete", "completed"} for item in trials),
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
            if dependencies.cancellation_requested and dependencies.cancellation_requested(job.id):
                raise AutoMLCancelled("AutoML cancellation requested")
            with dependencies.session_factory() as control_db:
                if control_db.query(TrainingJob.status).filter(
                    TrainingJob.id == job.id,
                ).scalar() == "cancel_requested":
                    raise AutoMLCancelled("AutoML cancellation requested")
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

        if dependencies.cancellation_requested and dependencies.cancellation_requested(job.id):
            raise AutoMLCancelled("AutoML cancellation requested")
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
        if dependencies.cancellation_requested and dependencies.cancellation_requested(job.id):
            raise AutoMLCancelled("AutoML cancellation requested")
        winner = best_candidate.factory()
        winner.fit(features, target)
        if dependencies.cancellation_requested and dependencies.cancellation_requested(job.id):
            raise AutoMLCancelled("AutoML cancellation requested")
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
