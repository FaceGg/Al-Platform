"""Deterministic feature-importance weighted clustering primitives."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Mapping, Sequence

import numpy as np
import pandas as pd
from sklearn.cluster import KMeans
from sklearn.metrics import silhouette_score
from sklearn.preprocessing import StandardScaler


@dataclass(frozen=True)
class FeatureMap:
    source_columns: tuple[str, ...]
    one_hot_dimensions: Mapping[str, tuple[int, ...]]

    def restore(self, vector: Sequence[float]) -> dict[str, float]:
        values = np.asarray(vector, dtype=float)
        result: dict[str, float] = {}
        mapped = set()
        for column in self.source_columns:
            dimensions = tuple(self.one_hot_dimensions.get(column, ()))
            if dimensions:
                result[column] = float(values[list(dimensions)].sum())
                mapped.update(dimensions)
        free_dimensions = [index for index in range(len(values)) if index not in mapped]
        free_index = 0
        for column in self.source_columns:
            if column in result:
                continue
            if free_index < len(free_dimensions):
                result[column] = float(values[free_dimensions[free_index]])
                free_index += 1
        if not result and len(values):
            result = {str(index): float(value) for index, value in enumerate(values)}
        return result


@dataclass(frozen=True)
class ImportanceVector:
    values: dict[str, float]
    source: str = "model"


@dataclass(frozen=True)
class InputContract:
    feature_columns: tuple[str, ...]


@dataclass(frozen=True)
class ClusterArtifact:
    labels: tuple[int, ...]
    k_scores: dict[int, float]
    selected_k: int
    seed: int
    weights: dict[str, float]
    feature_map: FeatureMap
    sample_count_evaluated: int
    sampling_mode: str
    sampling_hash: str
    centers: tuple[tuple[float, ...], ...]


def aggregate_model_importance(per_target: Mapping[str, Sequence[float]], feature_map: FeatureMap) -> ImportanceVector:
    if not per_target:
        return ImportanceVector({column: 0.0 for column in feature_map.source_columns}, source="unavailable")
    restored: list[dict[str, float]] = []
    for vector in per_target.values():
        values = np.asarray(vector, dtype=float)
        if values.ndim != 1 or not np.all(np.isfinite(values)) or np.any(values < 0) or values.sum() <= 0:
            return ImportanceVector({column: 0.0 for column in feature_map.source_columns}, source="needs_review")
        values = values / values.sum()
        restored.append(feature_map.restore(values))
    columns = feature_map.source_columns or tuple(sorted({key for item in restored for key in item}))
    averaged = {column: float(np.mean([item.get(column, 0.0) for item in restored])) for column in columns}
    return ImportanceVector(averaged, source="model")


def _extract_importance(model: object, feature_count: int) -> np.ndarray:
    steps = getattr(model, "steps", None)
    if steps:
        model = steps[-1][1]
    raw = getattr(model, "feature_importances_", None)
    if raw is None and hasattr(model, "coef_"):
        raw = np.asarray(getattr(model, "coef_"), dtype=float)
        if raw.ndim > 1:
            raw = np.mean(np.abs(raw), axis=0)
        else:
            raw = np.abs(raw)
    if raw is None:
        raise ValueError("FEATURE_IMPORTANCE_UNAVAILABLE")
    values = np.asarray(raw, dtype=float).reshape(-1)
    if len(values) != feature_count or not np.all(np.isfinite(values)) or np.any(values < 0) or values.sum() <= 0:
        raise ValueError("FEATURE_IMPORTANCE_UNAVAILABLE")
    return values / values.sum()


def build_weighted_clusters(
    frame: pd.DataFrame,
    model: object,
    feature_contract: InputContract,
    seed: int,
    max_k: int = 8,
) -> ClusterArtifact:
    if frame.empty:
        raise ValueError("CLUSTER_INPUT_EMPTY")
    columns = list(feature_contract.feature_columns)
    missing = [column for column in columns if column not in frame.columns]
    if missing:
        raise ValueError(f"CLUSTER_FEATURE_MISSING:{','.join(missing)}")
    matrix = frame.loc[:, columns].apply(pd.to_numeric, errors="raise").to_numpy(dtype=float)
    if not np.all(np.isfinite(matrix)):
        raise ValueError("CLUSTER_INPUT_INVALID")
    scaled = StandardScaler().fit_transform(matrix)
    raw_importance = _extract_importance(model, len(columns))
    weighted = scaled * np.sqrt(raw_importance)
    row_count = len(weighted)
    if row_count > 100_000:
        digest = np.array([int.from_bytes(hashlib.sha256(f"{seed}:{index}".encode()).digest()[:8], "big") for index in range(row_count)], dtype=np.uint64)
        eval_indices = np.argsort(digest)[:50_000]
        sampling_mode = "deterministic_hash_sample"
        sampling_hash = hashlib.sha256(digest[eval_indices].tobytes()).hexdigest()
    else:
        eval_indices = np.arange(row_count)
        sampling_mode = "all_rows"
        sampling_hash = hashlib.sha256(np.asarray(eval_indices, dtype=np.int64).tobytes()).hexdigest()
    eval_matrix = weighted[eval_indices]
    upper_k = min(max(2, int(max_k)), len(eval_matrix) - 1)
    if upper_k < 2:
        raise ValueError("CLUSTER_TOO_FEW_ROWS")
    scores: dict[int, float] = {}
    for k in range(2, upper_k + 1):
        labels = KMeans(n_clusters=k, random_state=seed, n_init=10).fit_predict(eval_matrix)
        if len(set(labels)) < 2:
            continue
        scores[k] = float(silhouette_score(eval_matrix, labels))
    if not scores:
        raise ValueError("CLUSTER_SILHOUETTE_UNAVAILABLE")
    selected_k = max(scores, key=lambda key: (scores[key], -key))
    final = KMeans(n_clusters=selected_k, random_state=seed, n_init=10).fit(weighted)
    weights = {column: float(value) for column, value in zip(columns, raw_importance)}
    feature_map = FeatureMap(tuple(columns), {})
    return ClusterArtifact(
        labels=tuple(int(value) for value in final.labels_),
        k_scores=scores,
        selected_k=selected_k,
        seed=int(seed),
        weights=weights,
        feature_map=feature_map,
        sample_count_evaluated=len(eval_indices),
        sampling_mode=sampling_mode,
        sampling_hash=sampling_hash,
        centers=tuple(tuple(float(item) for item in row) for row in final.cluster_centers_),
    )
