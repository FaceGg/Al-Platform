"""Bounded Optuna search for one generic AutoML algorithm family."""

import math
import time
from dataclasses import dataclass, field
from typing import Callable, Literal, Mapping, Sequence

import numpy as np
import optuna
from optuna.exceptions import TrialPruned
from optuna.pruners import HyperbandPruner, NopPruner
from optuna.samplers import GridSampler, NSGAIISampler, RandomSampler, TPESampler
from optuna.trial import FrozenTrial, TrialState
from sklearn.base import clone
from sklearn.metrics import f1_score, get_scorer, roc_auc_score
from sklearn.model_selection import KFold, StratifiedKFold, cross_val_predict, cross_val_score, train_test_split

from app.services.automl_catalog import AlgorithmFamily, AlgorithmUnavailable, ParameterSpec, TaskType


SEARCH_METHODS = frozenset({"grid", "random", "bayesian", "evolutionary", "multi_fidelity"})


class AllFamilySearchesFailed(RuntimeError):
    code = "AUTOML_ALL_ALGORITHMS_FAILED"


class TrialEvaluationFailed(RuntimeError):
    pass


@dataclass(frozen=True)
class SearchConfig:
    method: str
    max_trials: int
    timeout_seconds: float

    def __post_init__(self):
        if self.method not in SEARCH_METHODS or self.max_trials < 1 or self.timeout_seconds <= 0:
            raise ValueError("AUTOML_SEARCH_CONFIG_INVALID")


@dataclass(frozen=True)
class TrialProgress:
    algorithm_id: str
    trial_number: int
    state: str
    score: float | None


@dataclass(frozen=True)
class TrialSummary:
    number: int
    state: str
    score: float | None
    params: dict[str, object]
    duration_seconds: float
    intermediate_scores: dict[int, float]
    error_code: str | None = None
    auc: float | None = None
    f1: float | None = None
    accuracy: float | None = None


@dataclass
class FamilySearchResult:
    algorithm_id: str
    display_name: str
    catalog_index: int
    status: Literal["completed", "failed", "unavailable"]
    best_score: float | None = None
    best_params: dict[str, object] = field(default_factory=dict)
    best_estimator: object | None = None
    auc: float | None = None
    f1: float | None = None
    feature_importance: list[float] = field(default_factory=list)
    completed_trials: int = 0
    pruned_trials: int = 0
    failed_trials: int = 0
    training_time_seconds: float = 0.0
    error_code: str | None = None
    error_message: str | None = None
    budget_exhausted: bool = False
    trials: list[TrialSummary] = field(default_factory=list)


def build_optuna_components(
    method: str,
    grid: Mapping[str, Sequence[object]],
    min_resource: int,
    max_resource: int,
    max_trials: int,
):
    """Return deterministic sampler/pruner pairs for the supported strategy IDs."""
    if method not in SEARCH_METHODS or max_trials < 1:
        raise ValueError("AUTOML_SEARCH_CONFIG_INVALID")
    startup = min(5, max_trials)
    if method == "grid":
        return GridSampler({key: list(values) for key, values in grid.items()}, seed=42), NopPruner()
    if method == "random":
        return RandomSampler(seed=42), NopPruner()
    if method == "bayesian":
        return TPESampler(seed=42, n_startup_trials=startup), NopPruner()
    if method == "evolutionary":
        return NSGAIISampler(seed=42), NopPruner()
    return TPESampler(seed=42, n_startup_trials=startup), HyperbandPruner(
        min_resource=min_resource,
        max_resource=max_resource,
        reduction_factor=2,
    )


def _suggest_parameter(trial: optuna.Trial, name: str, spec: ParameterSpec):
    if spec.kind == "categorical":
        return trial.suggest_categorical(name, list(spec.choices))
    if spec.kind == "int":
        return trial.suggest_int(
            name,
            int(spec.low),
            int(spec.high),
            step=int(spec.step or 1),
            log=spec.log,
        )
    if spec.kind == "float":
        return trial.suggest_float(
            name,
            float(spec.low),
            float(spec.high),
            step=spec.step,
            log=spec.log,
        )
    raise ValueError("AUTOML_SEARCH_CONFIG_INVALID")


def _suggest_params(
    trial: optuna.Trial,
    family: AlgorithmFamily,
    *,
    exclude: str | None = None,
) -> dict[str, object]:
    return {
        name: _suggest_parameter(trial, name, spec)
        for name, spec in family.search_space.items()
        if name != exclude
    }


def _resource_rungs(family: AlgorithmFamily) -> tuple[int, ...]:
    values = {
        max(family.min_resource, min(family.max_resource, int(math.ceil(family.max_resource * fraction))))
        for fraction in (0.25, 0.5, 1.0)
    }
    return tuple(sorted(values))


def _evaluate_estimator(
    estimator,
    *,
    task: TaskType,
    features: np.ndarray,
    target: np.ndarray,
    evaluation: Mapping[str, object],
) -> float:
    cross_validation = bool(evaluation.get("cross_validation_enabled", True))
    scoring = "accuracy" if task == "classification" else "r2"
    scorer = get_scorer(scoring)
    if cross_validation:
        folds = int(evaluation.get("cross_validation_folds") or 5)
        splitter = (
            StratifiedKFold(n_splits=folds, shuffle=True, random_state=42)
            if task == "classification"
            else KFold(n_splits=folds, shuffle=True, random_state=42)
        )
        scores = cross_val_score(estimator, features, target, cv=splitter, scoring=scorer, error_score="raise")
        return float(np.mean(scores))

    stratify = target if task == "classification" and len(np.unique(target)) > 1 else None
    train_features, test_features, train_target, test_target = train_test_split(
        features,
        target,
        test_size=0.2,
        random_state=42,
        stratify=stratify,
    )
    estimator.fit(train_features, train_target)
    return float(scorer(estimator, test_features, test_target))


def _finite_score(value: float) -> float:
    if not math.isfinite(value):
        raise TrialEvaluationFailed("non-finite score")
    return value


def _feature_importance(estimator, expected_width: int) -> list[float]:
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
    return array.tolist() if array.ndim == 1 and len(array) == expected_width else []


def classification_metrics(
    estimator,
    *,
    features: np.ndarray,
    target: np.ndarray,
    evaluation: Mapping[str, object],
) -> tuple[float | None, float | None]:
    """Evaluate a fitted model on held-out/CV predictions without training leakage."""
    if len(np.unique(target)) < 2:
        return None, None
    cross_validation = bool(evaluation.get("cross_validation_enabled", True))
    if cross_validation:
        folds = int(evaluation.get("cross_validation_folds") or 5)
        _, class_counts = np.unique(np.asarray(target), return_counts=True)
        if len(class_counts) > 0:
            folds = min(folds, int(class_counts.min()))
        if folds < 2:
            cross_validation = False
    if cross_validation:
        splitter = StratifiedKFold(n_splits=folds, shuffle=True, random_state=42)
        predictions = cross_val_predict(clone(estimator), features, target, cv=splitter, method="predict")
        scoring = None
        for method in ("predict_proba", "decision_function"):
            try:
                scoring = cross_val_predict(clone(estimator), features, target, cv=splitter, method=method)
                break
            except (AttributeError, TypeError, ValueError):
                continue
        metric_target = target
    else:
        stratify = target if len(np.unique(target)) > 1 else None
        train_features, test_features, train_target, test_target = train_test_split(
            features, target, test_size=0.2, random_state=42, stratify=stratify,
        )
        holdout = clone(estimator)
        holdout.fit(train_features, train_target)
        predictions = holdout.predict(test_features)
        scoring = None
        for method in ("predict_proba", "decision_function"):
            try:
                scoring = getattr(holdout, method)(test_features)
                break
            except (AttributeError, TypeError, ValueError):
                continue
        metric_target = test_target
    f1 = float(f1_score(metric_target, predictions, average="weighted", zero_division=0))
    auc = None
    if scoring is not None:
        try:
            scores = np.asarray(scoring)
            if scores.ndim == 1:
                auc = float(roc_auc_score(metric_target, scores))
            elif scores.ndim == 2 and scores.shape[1] == 2:
                auc = float(roc_auc_score(metric_target, scores[:, 1]))
            elif scores.ndim == 2:
                auc = float(roc_auc_score(metric_target, scores, multi_class="ovr", average="weighted"))
        except (TypeError, ValueError):
            auc = None
    return auc, f1


def _trial_summary(trial: FrozenTrial) -> TrialSummary:
    duration = trial.duration.total_seconds() if trial.duration else 0.0
    score = float(trial.value) if trial.value is not None and math.isfinite(float(trial.value)) else None
    return TrialSummary(
        number=trial.number,
        state=trial.state.name.lower(),
        score=score,
        params=dict(trial.params),
        duration_seconds=duration,
        intermediate_scores={int(key): float(value) for key, value in trial.intermediate_values.items()},
        error_code=trial.user_attrs.get("error_code"),
        auc=trial.user_attrs.get("auc"),
        f1=trial.user_attrs.get("f1"),
        accuracy=trial.user_attrs.get("accuracy", score),
    )


def _grid_trial_count(grid: Mapping[str, Sequence[object]]) -> int:
    return math.prod(len(values) for values in grid.values()) if grid else 1


def run_family_search(
    *,
    family: AlgorithmFamily,
    task: TaskType,
    features: np.ndarray,
    target: np.ndarray,
    evaluation: Mapping[str, object],
    config: SearchConfig,
    catalog_index: int,
    progress_callback: Callable[[TrialProgress], None] | None = None,
    trial_callback: Callable[[TrialSummary], None] | None = None,
    monotonic: Callable[[], float] = time.monotonic,
) -> FamilySearchResult:
    """Optimize one selected algorithm family within a bounded wall-time slice."""
    started = monotonic()
    result = FamilySearchResult(
        algorithm_id=family.id,
        display_name=family.display_name,
        catalog_index=catalog_index,
        status="failed",
    )
    try:
        family.build(task, family.default_params)
    except AlgorithmUnavailable as error:
        result.status = "unavailable"
        result.error_code = error.code
        result.error_message = str(error)
        return result

    sampler, pruner = build_optuna_components(
        config.method,
        family.grid,
        family.min_resource,
        family.max_resource,
        config.max_trials,
    )
    study = optuna.create_study(direction="maximize", sampler=sampler, pruner=pruner)
    requested_trials = min(config.max_trials, _grid_trial_count(family.grid)) if config.method == "grid" else config.max_trials

    def objective(trial: optuna.Trial) -> float:
        try:
            if config.method == "multi_fidelity":
                params = _suggest_params(trial, family, exclude=family.resource_parameter)
                for resource in _resource_rungs(family):
                    rung_params = {**params, family.resource_parameter: resource}
                    score = _finite_score(_evaluate_estimator(
                        family.build(task, rung_params), task=task, features=features,
                        target=target, evaluation=evaluation,
                    ))
                    trial.report(score, step=resource)
                    if trial.should_prune():
                        raise TrialPruned()
                if task == "classification":
                    try:
                        auc, f1 = classification_metrics(
                            family.build(task, {**params, family.resource_parameter: family.max_resource}),
                            features=features,
                            target=target,
                            evaluation=evaluation,
                        )
                        if auc is not None:
                            trial.set_user_attr("auc", auc)
                        if f1 is not None:
                            trial.set_user_attr("f1", f1)
                        trial.set_user_attr("accuracy", score)
                    except (TypeError, ValueError, RuntimeError):
                        pass
                return score

            params = _suggest_params(trial, family)
            score = _finite_score(_evaluate_estimator(
                family.build(task, params), task=task, features=features,
                target=target, evaluation=evaluation,
            ))
            if task == "classification":
                try:
                    auc, f1 = classification_metrics(
                        family.build(task, params),
                        features=features,
                        target=target,
                        evaluation=evaluation,
                    )
                    if auc is not None:
                        trial.set_user_attr("auc", auc)
                    if f1 is not None:
                        trial.set_user_attr("f1", f1)
                    trial.set_user_attr("accuracy", score)
                except (TypeError, ValueError, RuntimeError):
                    pass
            return score
        except TrialPruned:
            raise
        except AlgorithmUnavailable as error:
            trial.set_user_attr("error_code", error.code)
            raise TrialEvaluationFailed(error.code) from error
        except Exception as error:
            trial.set_user_attr("error_code", "AUTOML_SEARCH_TRIAL_FAILED")
            raise TrialEvaluationFailed(type(error).__name__) from error

    def on_complete(_study: optuna.Study, frozen_trial: FrozenTrial) -> None:
        summary = _trial_summary(frozen_trial)
        result.trials.append(summary)
        if frozen_trial.state == TrialState.COMPLETE:
            result.completed_trials += 1
        elif frozen_trial.state == TrialState.PRUNED:
            result.pruned_trials += 1
        else:
            result.failed_trials += 1
        if progress_callback is not None:
            progress_callback(TrialProgress(
                algorithm_id=family.id,
                trial_number=frozen_trial.number,
                state=summary.state,
                score=summary.score,
            ))
        if trial_callback is not None:
            trial_callback(summary)

    optuna.logging.set_verbosity(optuna.logging.WARNING)
    study.optimize(
        objective,
        n_trials=requested_trials,
        timeout=config.timeout_seconds,
        catch=(TrialEvaluationFailed,),
        callbacks=(on_complete,),
    )
    result.training_time_seconds = monotonic() - started
    result.budget_exhausted = result.training_time_seconds >= config.timeout_seconds
    completed = [trial for trial in study.trials if trial.state == TrialState.COMPLETE and trial.value is not None]
    if not completed:
        result.error_code = "AUTOML_ALGORITHM_SEARCH_FAILED"
        result.error_message = "No successful hyperparameter trial"
        return result

    best_trial = max(completed, key=trial_metric_sort_key)
    best_params = dict(best_trial.params)
    if config.method == "multi_fidelity":
        best_params[family.resource_parameter] = family.max_resource
    estimator = family.build(task, best_params)
    estimator.fit(features, target)
    result.status = "completed"
    result.best_score = float(best_trial.value)
    result.best_params = best_params
    result.best_estimator = estimator
    if task == "classification":
        try:
            result.auc, result.f1 = classification_metrics(
                estimator, features=features, target=target, evaluation=evaluation,
            )
        except (TypeError, ValueError, RuntimeError):
            result.auc, result.f1 = None, None
    result.feature_importance = _feature_importance(estimator, features.shape[1])
    return result


def choose_family_winner(results: Sequence[FamilySearchResult]) -> FamilySearchResult:
    """Choose by AUC, F1, accuracy, duration, then catalog order."""
    successful = [
        result for result in results
        if result.status == "completed" and result.best_score is not None and math.isfinite(result.best_score)
    ]
    if not successful:
        raise AllFamilySearchesFailed()
    return max(successful, key=family_result_sort_key)


def family_result_sort_key(item: FamilySearchResult) -> tuple[float, float, float, float, int]:
    return automl_metric_sort_key(
        auc=item.auc,
        f1=item.f1,
        accuracy=item.best_score,
        duration=item.training_time_seconds,
        catalog_index=item.catalog_index,
    )


def automl_metric_sort_key(
    *,
    auc: float | None,
    f1: float | None,
    accuracy: float | None,
    duration: float | None,
    catalog_index: int,
) -> tuple[float, float, float, float, int]:
    # The UI exposes these metrics to four decimal places. Use that same
    # precision for tie-breaking so hidden floating-point noise cannot defeat
    # the requested duration tie-breaker.
    finite = lambda value: round(float(value), 4) if value is not None and math.isfinite(float(value)) else float("-inf")
    finite_duration = float(duration) if duration is not None and math.isfinite(float(duration)) else float("inf")
    return (finite(auc), finite(f1), finite(accuracy), -finite_duration, -catalog_index)


def trial_metric_sort_key(trial: FrozenTrial) -> tuple[float, float, float, float, int]:
    """Choose a parameter trial by displayed metrics, duration, then number."""
    attrs = trial.user_attrs or {}
    accuracy = attrs.get("accuracy", trial.value)
    duration = trial.duration.total_seconds() if trial.duration else None
    return automl_metric_sort_key(
        auc=attrs.get("auc"),
        f1=attrs.get("f1"),
        accuracy=accuracy,
        duration=duration,
        catalog_index=trial.number,
    )


def automl_metric_order_key(
    *,
    auc: float | None,
    f1: float | None,
    accuracy: float | None,
    duration: float | None,
    catalog_index: int,
) -> tuple[float, float, float, float, int]:
    """Sort best-first: metrics descending, duration ascending."""
    winner_key = automl_metric_sort_key(
        auc=auc,
        f1=f1,
        accuracy=accuracy,
        duration=duration,
        catalog_index=catalog_index,
    )
    return tuple(-value for value in winner_key)
