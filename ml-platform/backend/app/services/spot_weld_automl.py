"""点焊质量 AutoML 搜索 / 聚类 / 评估配置（P3 拆分：自 spot_weld_quality.py
原位迁出，纯算法块——不依赖 DB/artifact，全部输入显式传参）。

主模块 ``spot_weld_quality.py`` 通过 re-export 保持既有导入面不变
（normalize_*/CandidateResult/select_best_candidate/run_automl/
ClusterResult/run_clustering）。
"""
from __future__ import annotations

# 泛化门禁：本文件自 legacy 桥 spot_weld_quality.py 原位迁出，保留点焊域
# 字段名与阈值常量，随桥一并退役（genericization_gate.LEGACY_ADAPTER_FILES）。
LEGACY_ADAPTER_ONLY = True

import time
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Mapping, Sequence

import numpy as np
import pandas as pd
from sklearn.cluster import KMeans
from sklearn.decomposition import PCA
from sklearn.metrics import f1_score, roc_auc_score, silhouette_score
from sklearn.model_selection import StratifiedKFold, train_test_split
from sklearn.preprocessing import StandardScaler

from app.services.automl_catalog import resolve_algorithm_families
from app.services.automl_search import (
    FamilySearchResult,
    SEARCH_METHODS,
    SearchConfig,
    run_family_search,
)
from app.services.spot_weld_features import QualityPipelineError

QUALITY_CROSS_VALIDATION_FOLDS = frozenset({3, 4, 5})


def normalize_quality_search_config(
    algorithm_ids: Sequence[str] | None = None,
    search_method: str = "bayesian",
    max_trials: int = 20,
    time_budget: int = 600,
) -> dict[str, Any]:
    if (
        search_method not in SEARCH_METHODS
        or isinstance(max_trials, bool)
        or not 5 <= int(max_trials) <= 200
        or isinstance(time_budget, bool)
        or not 60 <= int(time_budget) <= 9999
    ):
        raise QualityPipelineError("QUALITY_AUTOML_SEARCH_CONFIG_INVALID")
    try:
        families = resolve_algorithm_families(list(algorithm_ids or []))
    except ValueError as error:
        raise QualityPipelineError("QUALITY_AUTOML_SEARCH_CONFIG_INVALID") from error
    return {
        "search_contract": "optuna_v1",
        "algorithm_ids": [family.id for family in families],
        "search_method": search_method,
        "max_trials": int(max_trials),
        "time_budget": int(time_budget),
    }


def normalize_quality_evaluation_config(
    cross_validation_enabled: bool = True,
    cross_validation_folds: int | None = 3,
) -> dict[str, bool | int | None]:
    if not isinstance(cross_validation_enabled, bool):
        raise QualityPipelineError("QUALITY_EVALUATION_CONFIG_INVALID")
    if not cross_validation_enabled:
        return {
            "cross_validation_enabled": False,
            "cross_validation_folds": None,
        }
    if (
        isinstance(cross_validation_folds, bool)
        or cross_validation_folds not in QUALITY_CROSS_VALIDATION_FOLDS
    ):
        raise QualityPipelineError("QUALITY_EVALUATION_CONFIG_INVALID")
    return {
        "cross_validation_enabled": True,
        "cross_validation_folds": int(cross_validation_folds),
    }


@dataclass
class CandidateResult:
    algorithm_id: str
    name: str
    status: str
    config_index: int
    best_score: float | None = None
    auc: float | None = None
    f1: float | None = None
    auc_std: float = 0.0
    f1_std: float = 0.0
    best_params: dict[str, Any] = field(default_factory=dict)
    completed_trials: int = 0
    pruned_trials: int = 0
    failed_trials: int = 0
    training_time_seconds: float = 0.0
    error_code: str | None = None
    error_message: str | None = None
    feature_importance: list[float] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "algorithm_id": self.algorithm_id,
            "status": self.status,
            "best_score": self.best_score,
            "auc": self.auc,
            "f1": self.f1,
            "config_index": self.config_index,
            "auc_std": self.auc_std,
            "f1_std": self.f1_std,
            "best_params": self.best_params,
            "completed_trials": self.completed_trials,
            "pruned_trials": self.pruned_trials,
            "failed_trials": self.failed_trials,
            "training_time_seconds": self.training_time_seconds,
            "error_code": self.error_code,
            "error_message": self.error_message,
            "feature_importance": self.feature_importance,
        }


def select_best_candidate(results: list[CandidateResult]) -> CandidateResult:
    successful = [result for result in results if result.error_code is None and result.auc is not None and result.f1 is not None]
    if not successful:
        raise QualityPipelineError("QUALITY_AUTOML_ALL_CANDIDATES_FAILED")
    return max(successful, key=lambda item: (float(item.auc), float(item.f1), -item.config_index))


def _feature_importance(model, feature_count: int) -> np.ndarray:
    importance = getattr(model, "feature_importances_", None)
    if importance is None:
        importance = np.abs(getattr(model, "coef_", np.ones((1, feature_count))))
    importance = np.asarray(importance, dtype=float).reshape(-1)
    if len(importance) != feature_count or not np.isfinite(importance).all() or float(importance.sum()) <= 0:
        return np.ones(feature_count, dtype=float)
    return importance


def _estimator_matrix(values: np.ndarray) -> pd.DataFrame:
    """Keep fitted and predicted model matrices on one stable feature-name contract."""
    matrix = np.asarray(values, dtype=np.float64)
    if matrix.ndim != 2:
        raise QualityPipelineError("QUALITY_AUTOML_INPUT_INVALID")
    return pd.DataFrame(matrix, columns=[f"feature_{index}" for index in range(matrix.shape[1])])


def _quality_automl_auc(y_true: np.ndarray, probabilities: np.ndarray, class_count: int) -> float:
    if class_count == 2:
        return float(roc_auc_score(y_true, probabilities[:, 1]))
    return float(roc_auc_score(
        y_true,
        probabilities,
        labels=np.arange(class_count),
        multi_class="ovr",
        average="macro",
    ))


def _quality_automl_splits(
    features: np.ndarray,
    target: np.ndarray,
    evaluation: Mapping[str, Any],
) -> tuple[tuple[np.ndarray, np.ndarray], ...]:
    if evaluation["cross_validation_enabled"]:
        splitter = StratifiedKFold(
            n_splits=int(evaluation["cross_validation_folds"]),
            shuffle=True,
            random_state=42,
        )
        return tuple(splitter.split(features, target))
    try:
        train_index, test_index = train_test_split(
            np.arange(len(target)),
            test_size=0.2,
            random_state=42,
            stratify=target,
        )
    except ValueError as error:
        raise QualityPipelineError("QUALITY_AUTOML_INSUFFICIENT_LABELS") from error
    return ((train_index, test_index),)


def _quality_estimator_metrics(
    estimator_factory: Callable[[], Any],
    *,
    features: np.ndarray,
    target: np.ndarray,
    evaluation: Mapping[str, Any],
) -> dict[str, Any]:
    class_count = len(np.unique(target))
    aucs: list[float] = []
    f1s: list[float] = []
    importances: list[np.ndarray] = []
    for train_index, test_index in _quality_automl_splits(features, target, evaluation):
        scaler = StandardScaler()
        train = scaler.fit_transform(features[train_index])
        test = scaler.transform(features[test_index])
        estimator = estimator_factory()
        estimator.fit(_estimator_matrix(train), target[train_index])
        probabilities = estimator.predict_proba(_estimator_matrix(test))
        predictions = estimator.predict(_estimator_matrix(test))
        aucs.append(_quality_automl_auc(target[test_index], probabilities, class_count))
        f1s.append(float(f1_score(
            target[test_index], predictions, average="macro", zero_division=0,
        )))
        importances.append(_feature_importance(estimator, features.shape[1]))
    return {
        "auc": float(np.mean(aucs)),
        "f1": float(np.mean(f1s)),
        "auc_std": float(np.std(aucs)),
        "f1_std": float(np.std(f1s)),
        "feature_importance": np.mean(importances, axis=0).tolist(),
    }


def _evaluate_quality_estimator(
    estimator,
    *,
    task: str,
    features: np.ndarray,
    target: np.ndarray,
    evaluation: Mapping[str, Any],
) -> float:
    if task != "classification":
        raise QualityPipelineError("QUALITY_AUTOML_SEARCH_CONFIG_INVALID")
    metrics = _quality_estimator_metrics(
        lambda: estimator,
        features=features,
        target=target,
        evaluation=evaluation,
    )
    return float(metrics["auc"])


def run_automl(
    features: np.ndarray,
    labels: Iterable[Any],
    *,
    algorithm_ids: Sequence[str] | None = None,
    search_method: str = "bayesian",
    max_trials: int = 20,
    time_budget: float = 600,
    evaluation: Mapping[str, Any] | None = None,
    progress_callback: Callable[[int, int, CandidateResult], None] | None = None,
    family_search: Callable[..., FamilySearchResult] = run_family_search,
    monotonic: Callable[[], float] = time.monotonic,
) -> tuple[list[CandidateResult], CandidateResult]:
    X = np.asarray(features, dtype=np.float64)
    y_raw = np.asarray(list(labels))
    if X.ndim != 2 or len(X) != len(y_raw):
        raise QualityPipelineError("QUALITY_AUTOML_INPUT_INVALID")
    unique, y = np.unique(y_raw, return_inverse=True)
    if len(unique) < 2:
        raise QualityPipelineError("QUALITY_AUTOML_INSUFFICIENT_LABELS")
    evaluation_config = normalize_quality_evaluation_config(
        (evaluation or {}).get("cross_validation_enabled", True),
        (evaluation or {}).get("cross_validation_folds", 3),
    )
    counts = np.bincount(y)
    minimum_count = (
        int(evaluation_config["cross_validation_folds"])
        if evaluation_config["cross_validation_enabled"]
        else 2
    )
    if len(counts) < 2 or int(counts.min()) < minimum_count:
        raise QualityPipelineError("QUALITY_AUTOML_INSUFFICIENT_LABELS")
    search_config = normalize_quality_search_config(
        algorithm_ids,
        search_method,
        int(max_trials),
        int(time_budget),
    )
    families = resolve_algorithm_families(search_config["algorithm_ids"])
    deadline = monotonic() + float(search_config["time_budget"])
    planned_trials = len(families) * search_config["max_trials"]
    terminal_trials = 0
    results: list[CandidateResult] = []
    for config_index, family in enumerate(families):
        remaining = deadline - monotonic()
        if remaining <= 0:
            results.append(CandidateResult(
                algorithm_id=family.id,
                name=family.display_name,
                status="failed",
                config_index=config_index,
                error_code="QUALITY_AUTOML_BUDGET_EXHAUSTED",
                error_message="Point-weld AutoML time budget exhausted",
            ))
            continue

        def on_trial(_summary, *, current_family=family) -> None:
            nonlocal terminal_trials
            terminal_trials += 1
            if progress_callback is not None:
                progress_callback(
                    terminal_trials,
                    planned_trials,
                    CandidateResult(
                        algorithm_id=current_family.id,
                        name=current_family.display_name,
                        status="running",
                        config_index=config_index,
                    ),
                )

        family_result = family_search(
            family=family,
            task="classification",
            features=X,
            target=y,
            evaluation=evaluation_config,
            config=SearchConfig(
                method=search_config["search_method"],
                max_trials=search_config["max_trials"],
                timeout_seconds=max(0.001, remaining / (len(families) - config_index)),
            ),
            catalog_index=config_index,
            estimator_evaluator=_evaluate_quality_estimator,
            trial_callback=on_trial,
        )
        result = CandidateResult(
            algorithm_id=family.id,
            name=family.display_name,
            status=family_result.status,
            config_index=config_index,
            best_score=family_result.best_score,
            best_params=dict(family_result.best_params),
            completed_trials=family_result.completed_trials,
            pruned_trials=family_result.pruned_trials,
            failed_trials=family_result.failed_trials,
            training_time_seconds=family_result.training_time_seconds,
            error_code=family_result.error_code,
            error_message=family_result.error_message,
        )
        if family_result.status == "completed":
            metrics = _quality_estimator_metrics(
                lambda family=family, params=result.best_params: family.build("classification", params),
                features=X,
                target=y,
                evaluation=evaluation_config,
            )
            result.auc = metrics["auc"]
            result.f1 = metrics["f1"]
            result.auc_std = metrics["auc_std"]
            result.f1_std = metrics["f1_std"]
            result.feature_importance = metrics["feature_importance"]
        results.append(result)
    return results, select_best_candidate(results)


@dataclass(frozen=True)
class ClusterResult:
    best_k: int
    silhouette_scores: dict[int, float]
    cluster_ids: list[int]
    pca_coordinates: np.ndarray
    anomaly_cluster: int
    weights: list[float]

    def to_dict(self) -> dict[str, Any]:
        return {
            "best_k": self.best_k,
            "silhouette_scores": {str(key): value for key, value in self.silhouette_scores.items()},
            "cluster_ids": self.cluster_ids,
            "pca_coordinates": self.pca_coordinates.tolist(),
            "anomaly_cluster": self.anomaly_cluster,
            "weights": self.weights,
        }


def run_clustering(
    features: np.ndarray,
    *,
    feature_names: list[str],
    feature_importance: np.ndarray | Iterable[float],
) -> ClusterResult:
    X = np.asarray(features, dtype=np.float64)
    if X.ndim != 2 or X.shape[1] != len(feature_names) or len(X) < 3:
        raise QualityPipelineError("QUALITY_CLUSTER_INPUT_INVALID")
    scaler = StandardScaler()
    scaled = scaler.fit_transform(X)
    importances = np.asarray(list(feature_importance), dtype=float).reshape(-1)
    if len(importances) != X.shape[1] or not np.isfinite(importances).all():
        importances = np.ones(X.shape[1], dtype=float)
    else:
        importances = np.maximum(importances, 0.0)
        if importances.sum() <= 0:
            importances = np.ones(X.shape[1], dtype=float)
    weights = importances / importances.sum()
    weighted = scaled * np.sqrt(weights)
    max_k = min(8, len(X) - 1)
    scores: dict[int, float] = {}
    for k in range(2, max_k + 1):
        labels = KMeans(n_clusters=k, random_state=42, n_init=10).fit_predict(weighted)
        if len(set(labels)) > 1:
            scores[k] = float(silhouette_score(weighted, labels))
    if not scores:
        raise QualityPipelineError("QUALITY_CLUSTER_FAILED")
    best_k = max(scores, key=lambda key: (scores[key], -key))
    labels = KMeans(n_clusters=best_k, random_state=42, n_init=10).fit_predict(weighted)
    coordinates = PCA(n_components=2, random_state=42).fit_transform(weighted)
    # Report v1 makes the highest spatter cluster the anomaly role; ties use energy then ID.
    spatter_index = feature_names.index("spatter_total") if "spatter_total" in feature_names else None
    energy_index = feature_names.index("energy_dev") if "energy_dev" in feature_names else None
    cluster_keys = []
    for cluster_id in sorted(set(labels)):
        members = labels == cluster_id
        spatter_score = float(np.mean(X[members, spatter_index])) if spatter_index is not None else 0.0
        energy_score = float(np.mean(np.abs(X[members, energy_index]))) if energy_index is not None else 0.0
        cluster_keys.append((spatter_score, energy_score, -cluster_id, cluster_id))
    anomaly_cluster = max(cluster_keys)[-1]
    return ClusterResult(
        best_k=best_k,
        silhouette_scores=scores,
        cluster_ids=labels.astype(int).tolist(),
        pca_coordinates=coordinates,
        anomaly_cluster=int(anomaly_cluster),
        weights=weights.tolist(),
    )
