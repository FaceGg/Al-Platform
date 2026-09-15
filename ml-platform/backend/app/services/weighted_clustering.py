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
    total_sample_count: int
    sampling_mode: str
    sampling_hash: str
    preprocessing: Mapping[str, object]
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
    return _normalize_importance_values(raw, feature_count)


def _normalize_importance_values(raw: object, feature_count: int) -> np.ndarray:
    values = np.asarray(raw, dtype=float).reshape(-1)
    if len(values) != feature_count or not np.all(np.isfinite(values)) or np.any(values < 0) or values.sum() <= 0:
        raise ValueError("FEATURE_IMPORTANCE_UNAVAILABLE")
    return values / values.sum()


def _frozen_importance_values(
    feature_importance: Mapping[str, float] | Sequence[float],
    feature_columns: Sequence[str],
) -> np.ndarray:
    if isinstance(feature_importance, Mapping):
        expected = set(feature_columns)
        if set(feature_importance) != expected:
            raise ValueError("FEATURE_IMPORTANCE_UNAVAILABLE")
        try:
            values = [feature_importance[column] for column in feature_columns]
        except KeyError as error:
            raise ValueError("FEATURE_IMPORTANCE_UNAVAILABLE") from error
        return _normalize_importance_values(values, len(feature_columns))
    return _normalize_importance_values(feature_importance, len(feature_columns))


def _numeric_feature_matrix(frame: pd.DataFrame, columns: Sequence[str]) -> np.ndarray:
    missing = [column for column in columns if column not in frame.columns]
    if missing:
        raise ValueError(f"CLUSTER_FEATURE_MISSING:{','.join(missing)}")
    matrix = frame.loc[:, list(columns)].apply(pd.to_numeric, errors="raise").to_numpy(dtype=float)
    if not np.all(np.isfinite(matrix)):
        raise ValueError("CLUSTER_INPUT_INVALID")
    return matrix


def deterministic_sample_indices(
    sample_ids: Sequence[object],
    *,
    task_revision: int,
    seed: int,
    limit: int = 50_000,
) -> tuple[np.ndarray, str]:
    """Select a stable evaluation subset using frozen sample identities.

    The returned indices preserve hash rank rather than the input row order, so
    the same frozen samples produce the same evaluation matrix after a harmless
    source-row reordering.
    """
    if limit < 0:
        raise ValueError("CLUSTER_EVALUATION_LIMIT_INVALID")
    ranked: list[tuple[bytes, bytes, int]] = []
    revision_bytes = str(int(task_revision)).encode("utf-8")
    seed_bytes = str(int(seed)).encode("utf-8")
    for index, sample_id in enumerate(sample_ids):
        sample_id_bytes = str(sample_id).encode("utf-8")
        digest = hashlib.sha256(
            b"annotation-cluster-evaluation-v1\x00"
            + revision_bytes
            + b"\x00"
            + seed_bytes
            + b"\x00"
            + sample_id_bytes
        ).digest()
        ranked.append((digest, sample_id_bytes, index))
    ranked.sort(key=lambda item: (item[0], item[1]))
    selected = ranked[:limit]

    hash_builder = hashlib.sha256()
    hash_builder.update(b"annotation-cluster-evaluation-sample-v1\x00")
    hash_builder.update(revision_bytes)
    hash_builder.update(b"\x00")
    hash_builder.update(seed_bytes)
    hash_builder.update(b"\x00")
    for digest, sample_id_bytes, _ in selected:
        hash_builder.update(digest)
        hash_builder.update(b"\x00")
        hash_builder.update(sample_id_bytes)
        hash_builder.update(b"\x00")
    return np.asarray([item[2] for item in selected], dtype=np.int64), hash_builder.hexdigest()


def assign_clusters_from_artifact(frame: pd.DataFrame, artifact: ClusterArtifact) -> tuple[int, ...]:
    """Assign rows with only frozen weighted-cluster preprocessing and centers."""
    preprocessing = artifact.preprocessing
    if not isinstance(preprocessing, Mapping):
        raise ValueError("CLUSTER_PREPROCESSING_INVALID")
    feature_columns = preprocessing.get("feature_columns")
    standardizer = preprocessing.get("standardizer")
    if not isinstance(feature_columns, (list, tuple)) or not feature_columns or not isinstance(standardizer, Mapping):
        raise ValueError("CLUSTER_PREPROCESSING_INVALID")
    columns = tuple(str(column) for column in feature_columns)
    mean = np.asarray(standardizer.get("mean"), dtype=float)
    scale = np.asarray(standardizer.get("scale"), dtype=float)
    matrix = _numeric_feature_matrix(frame, columns)
    if (
        mean.ndim != 1
        or scale.ndim != 1
        or len(mean) != matrix.shape[1]
        or len(scale) != matrix.shape[1]
        or not np.all(np.isfinite(mean))
        or not np.all(np.isfinite(scale))
        or np.any(scale <= 0)
    ):
        raise ValueError("CLUSTER_PREPROCESSING_INVALID")
    try:
        weights = np.asarray([artifact.weights[column] for column in columns], dtype=float)
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError("CLUSTER_PREPROCESSING_INVALID") from error
    if not np.all(np.isfinite(weights)) or np.any(weights < 0) or weights.sum() <= 0:
        raise ValueError("CLUSTER_PREPROCESSING_INVALID")
    centers = np.asarray(artifact.centers, dtype=float)
    if centers.ndim != 2 or centers.shape[0] < 1 or centers.shape[1] != matrix.shape[1] or not np.all(np.isfinite(centers)):
        raise ValueError("CLUSTER_ARTIFACT_INVALID")
    weighted = ((matrix - mean) / scale) * np.sqrt(weights)
    distances = np.sum((weighted[:, np.newaxis, :] - centers[np.newaxis, :, :]) ** 2, axis=2)
    return tuple(int(value) for value in np.argmin(distances, axis=1))


def build_weighted_clusters(
    frame: pd.DataFrame,
    model: object,
    feature_contract: InputContract,
    seed: int,
    max_k: int = 8,
    task_revision: int = 0,
    sample_ids: Sequence[object] | None = None,
    feature_importance: Mapping[str, float] | Sequence[float] | None = None,
) -> ClusterArtifact:
    if frame.empty:
        raise ValueError("CLUSTER_INPUT_EMPTY")
    columns = list(feature_contract.feature_columns)
    matrix = _numeric_feature_matrix(frame, columns)
    scaler = StandardScaler().fit(matrix)
    scaled = scaler.transform(matrix)
    raw_importance = (
        _extract_importance(model, len(columns))
        if feature_importance is None
        else _frozen_importance_values(feature_importance, columns)
    )
    weighted = scaled * np.sqrt(raw_importance)
    row_count = len(weighted)
    evaluation_ids = tuple(frame.index) if sample_ids is None else tuple(sample_ids)
    if len(evaluation_ids) != row_count:
        raise ValueError("CLUSTER_SAMPLE_ID_COUNT_MISMATCH")
    if row_count > 100_000:
        eval_indices, sampling_hash = deterministic_sample_indices(
            evaluation_ids,
            task_revision=task_revision,
            seed=seed,
        )
        sampling_mode = "deterministic_hash_sample"
    else:
        eval_indices, sampling_hash = deterministic_sample_indices(
            evaluation_ids,
            task_revision=task_revision,
            seed=seed,
            limit=row_count,
        )
        sampling_mode = "all_rows"
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
    preprocessing = {
        "version": "weighted-clustering-v1",
        "fit_scope": "frozen_task_sample_scope",
        "feature_columns": tuple(columns),
        "standardizer": {
            "mean": tuple(float(value) for value in scaler.mean_),
            "scale": tuple(float(value) for value in scaler.scale_),
        },
    }
    return ClusterArtifact(
        labels=tuple(int(value) for value in final.labels_),
        k_scores=scores,
        selected_k=selected_k,
        seed=int(seed),
        weights=weights,
        feature_map=feature_map,
        sample_count_evaluated=len(eval_indices),
        total_sample_count=row_count,
        sampling_mode=sampling_mode,
        sampling_hash=sampling_hash,
        preprocessing=preprocessing,
        centers=tuple(tuple(float(item) for item in row) for row in final.cluster_centers_),
    )
