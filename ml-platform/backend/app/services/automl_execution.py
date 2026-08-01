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
    if task not in {"classification", "regression"}:
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
    if task not in {"classification", "regression"}:
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
        task = params.get("task", "classification")
        if task not in {"classification", "regression"}:
            raise ValueError("AutoML task must be classification or regression")
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

        configured_candidates = (
            tuple(candidates)
            if candidates is not None
            else resolve_candidates(task, params.get("candidate_ids"))
        )
        if not configured_candidates:
            raise ValueError("AutoML requires at least one candidate")
        evaluation = normalize_evaluation_config(
            params.get("cross_validation_enabled", True),
            params.get("cross_validation_folds", 5),
        )
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
                duration = time.perf_counter() - started
                tracking.log_metrics(child.run_id, {
                    "cv_score" if cv is not None else "holdout_score": score,
                }, step=0)
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

        model_entry = ModelLibrary(
            name=job.name,
            project_id=job.project_id,
            owner_id=job.user_id,
            status="completed",
            framework="scikit-learn",
            backbone=type(winner).__name__,
            metrics={"best_score": best_score, "evaluation": evaluation},
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
        job.metrics = {
            "best_score": best_score,
            "best_candidate": best_candidate.name,
            "evaluation": evaluation,
            "best_model": {
                "name": best_candidate.name,
                "score": best_score,
            },
            "all_results": [
                {"name": candidate.name, "score": score}
                for score, index, candidate, _child_run_id in sorted(
                    successes,
                    key=lambda item: (-item[0], item[1]),
                )
            ],
        }
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
