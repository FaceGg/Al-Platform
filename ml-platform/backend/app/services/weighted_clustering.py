"""Deterministic feature-importance weighted clustering primitives."""

from __future__ import annotations

import heapq
import hashlib
from dataclasses import dataclass
from typing import Callable, Iterable, Mapping, Sequence

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


@dataclass(frozen=True)
class _ReverseSampleRank:
    """Heap entry whose least item is the lexicographically largest rank."""

    rank: tuple[bytes, bytes]
    vector: np.ndarray

    def __lt__(self, other: "_ReverseSampleRank") -> bool:
        return self.rank > other.rank


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
    for index, sample_id in enumerate(sample_ids):
        digest, sample_id_bytes = _sample_evaluation_rank(
            sample_id,
            task_revision=task_revision,
            seed=seed,
        )
        ranked.append((digest, sample_id_bytes, index))
    ranked.sort(key=lambda item: (item[0], item[1]))
    selected = ranked[:limit]

    return np.asarray([item[2] for item in selected], dtype=np.int64), _evaluation_sample_hash(
        selected,
        task_revision=task_revision,
        seed=seed,
    )


def _sample_evaluation_rank(sample_id: object, *, task_revision: int, seed: int) -> tuple[bytes, bytes]:
    revision_bytes = str(int(task_revision)).encode("utf-8")
    seed_bytes = str(int(seed)).encode("utf-8")
    sample_id_bytes = str(sample_id).encode("utf-8")
    digest = hashlib.sha256(
        b"annotation-cluster-evaluation-v1\x00"
        + revision_bytes
        + b"\x00"
        + seed_bytes
        + b"\x00"
        + sample_id_bytes
    ).digest()
    return digest, sample_id_bytes


def _evaluation_sample_hash(
    ranked_entries: Sequence[tuple[bytes, bytes, object]],
    *,
    task_revision: int,
    seed: int,
) -> str:
    revision_bytes = str(int(task_revision)).encode("utf-8")
    seed_bytes = str(int(seed)).encode("utf-8")

    hash_builder = hashlib.sha256()
    hash_builder.update(b"annotation-cluster-evaluation-sample-v1\x00")
    hash_builder.update(revision_bytes)
    hash_builder.update(b"\x00")
    hash_builder.update(seed_bytes)
    hash_builder.update(b"\x00")
    for digest, sample_id_bytes, _ in ranked_entries:
        hash_builder.update(digest)
        hash_builder.update(b"\x00")
        hash_builder.update(sample_id_bytes)
        hash_builder.update(b"\x00")
    return hash_builder.hexdigest()


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


def cluster_artifact_from_payload(payload: Mapping[str, object]) -> ClusterArtifact:
    """Restore a frozen cluster artifact persisted in JSON metadata.

    Per-sample labels deliberately do not belong to this payload.  They are
    stored in the indexed annotation-strategy decision table, while this
    helper restores only the preprocessing and centers needed to assign a
    caller-provided source batch without refitting.
    """
    try:
        feature_map_payload = payload.get("feature_map")
        if not isinstance(feature_map_payload, Mapping):
            raise ValueError("CLUSTER_ARTIFACT_INVALID")
        dimensions_payload = feature_map_payload.get("one_hot_dimensions") or {}
        if not isinstance(dimensions_payload, Mapping):
            raise ValueError("CLUSTER_ARTIFACT_INVALID")
        feature_map = FeatureMap(
            tuple(str(column) for column in feature_map_payload.get("source_columns") or ()),
            {
                str(column): tuple(int(index) for index in dimensions)
                for column, dimensions in dimensions_payload.items()
            },
        )
        weights_payload = payload.get("weights")
        centers_payload = payload.get("centers")
        preprocessing = payload.get("preprocessing")
        if (
            not isinstance(weights_payload, Mapping)
            or not isinstance(centers_payload, (list, tuple))
            or not isinstance(preprocessing, Mapping)
        ):
            raise ValueError("CLUSTER_ARTIFACT_INVALID")
        return ClusterArtifact(
            labels=(),
            k_scores={int(key): float(value) for key, value in (payload.get("k_scores") or {}).items()},
            selected_k=int(payload["selected_k"]),
            seed=int(payload["seed"]),
            weights={str(key): float(value) for key, value in weights_payload.items()},
            feature_map=feature_map,
            sample_count_evaluated=int(payload["sample_count_evaluated"]),
            total_sample_count=int(payload["total_sample_count"]),
            sampling_mode=str(payload["sampling_mode"]),
            sampling_hash=str(payload["sampling_hash"]),
            preprocessing=dict(preprocessing),
            centers=tuple(
                tuple(float(value) for value in center)
                for center in centers_payload
            ),
        )
    except (AttributeError, KeyError, TypeError, ValueError) as error:
        raise ValueError("CLUSTER_ARTIFACT_INVALID") from error


def _nearest_cluster_labels(matrix: np.ndarray, centers: np.ndarray) -> np.ndarray:
    distances = np.sum((matrix[:, np.newaxis, :] - centers[np.newaxis, :, :]) ** 2, axis=2)
    return np.argmin(distances, axis=1)


def _fit_streaming_lloyd_kmeans(
    batches: Callable[[], Iterable[tuple[Sequence[object], pd.DataFrame]]],
    *,
    columns: Sequence[str],
    scaler: StandardScaler,
    weights_root: np.ndarray,
    initial_centers: np.ndarray,
    expected_count: int,
    on_batch: Callable[[], None] | None,
    max_iterations: int = 300,
    tolerance: float = 1e-4,
) -> tuple[np.ndarray, int]:
    """Run deterministic, full-scope Lloyd KMeans without a global matrix.

    Each iteration aggregates assignment sums and counts over every frozen
    source batch.  This is batch KMeans rather than MiniBatchKMeans: the
    bounded batches are an I/O and memory boundary only, never a sampling
    substitute for the final centers.
    """
    centers = np.asarray(initial_centers, dtype=float).copy()
    if centers.ndim != 2 or centers.shape[0] < 2 or centers.shape[1] != len(columns):
        raise ValueError("CLUSTER_ARTIFACT_INVALID")
    for iteration in range(1, max_iterations + 1):
        sums = np.zeros_like(centers)
        counts = np.zeros(centers.shape[0], dtype=np.int64)
        observed_count = 0
        for sample_ids, frame in batches():
            if len(sample_ids) != len(frame):
                raise ValueError("CLUSTER_SAMPLE_ID_COUNT_MISMATCH")
            matrix = _numeric_feature_matrix(frame, columns)
            weighted = scaler.transform(matrix) * weights_root
            labels = _nearest_cluster_labels(weighted, centers)
            np.add.at(sums, labels, weighted)
            counts += np.bincount(labels, minlength=centers.shape[0])
            observed_count += len(weighted)
            if on_batch is not None:
                on_batch()
        if observed_count != expected_count:
            raise ValueError("CLUSTER_SAMPLE_ID_COUNT_MISMATCH")
        if np.any(counts == 0):
            raise ValueError("CLUSTER_EMPTY_CLUSTER")
        updated_centers = sums / counts[:, np.newaxis]
        if not np.all(np.isfinite(updated_centers)):
            raise ValueError("CLUSTER_INPUT_INVALID")
        shift = float(np.max(np.linalg.norm(updated_centers - centers, axis=1)))
        scale = max(1.0, float(np.max(np.abs(centers))))
        centers = updated_centers
        if shift <= tolerance * scale:
            return centers, iteration
    return centers, max_iterations


def build_weighted_clusters_streaming(
    batches: Callable[[], Iterable[tuple[Sequence[object], pd.DataFrame]]],
    model: object,
    feature_contract: InputContract,
    seed: int,
    *,
    max_k: int = 8,
    task_revision: int = 0,
    total_sample_count: int,
    feature_importance: Mapping[str, float] | Sequence[float] | None = None,
    on_batch: Callable[[], None] | None = None,
) -> ClusterArtifact:
    """Fit weighted clusters from repeatable bounded source batches.

    The all-row standardizer and final cluster fit consume every eligible row,
    while only the proposal's allowed silhouette-evaluation subset remains in
    memory. Callers use :func:`assign_clusters_from_artifact` for the final
    full-scope assignment pass after this immutable artifact is frozen.
    """
    expected_count = int(total_sample_count)
    if expected_count < 3:
        raise ValueError("CLUSTER_TOO_FEW_ROWS")
    columns = tuple(str(column) for column in feature_contract.feature_columns)
    if not columns:
        raise ValueError("CLUSTER_FEATURE_MISSING")
    raw_importance = (
        _extract_importance(model, len(columns))
        if feature_importance is None
        else _frozen_importance_values(feature_importance, columns)
    )
    scaler = StandardScaler()
    observed_count = 0
    for sample_ids, frame in batches():
        if len(sample_ids) != len(frame):
            raise ValueError("CLUSTER_SAMPLE_ID_COUNT_MISMATCH")
        matrix = _numeric_feature_matrix(frame, columns)
        scaler.partial_fit(matrix)
        observed_count += len(matrix)
        if on_batch is not None:
            on_batch()
    if observed_count != expected_count:
        raise ValueError("CLUSTER_SAMPLE_ID_COUNT_MISMATCH")

    evaluation_limit = expected_count if expected_count <= 100_000 else 50_000
    all_evaluation_rows: list[tuple[bytes, bytes, np.ndarray]] = []
    sampled_evaluation_rows: list[_ReverseSampleRank] = []
    weights_root = np.sqrt(raw_importance)
    for sample_ids, frame in batches():
        if len(sample_ids) != len(frame):
            raise ValueError("CLUSTER_SAMPLE_ID_COUNT_MISMATCH")
        matrix = _numeric_feature_matrix(frame, columns)
        weighted = scaler.transform(matrix) * weights_root
        for sample_id, vector in zip(sample_ids, weighted):
            digest, sample_id_bytes = _sample_evaluation_rank(
                sample_id,
                task_revision=task_revision,
                seed=seed,
            )
            if expected_count <= 100_000:
                all_evaluation_rows.append((digest, sample_id_bytes, np.asarray(vector, dtype=float).copy()))
                continue
            candidate = _ReverseSampleRank((digest, sample_id_bytes), np.asarray(vector, dtype=float).copy())
            if len(sampled_evaluation_rows) < evaluation_limit:
                heapq.heappush(sampled_evaluation_rows, candidate)
            elif candidate.rank < sampled_evaluation_rows[0].rank:
                heapq.heapreplace(sampled_evaluation_rows, candidate)
        if on_batch is not None:
            on_batch()

    if expected_count <= 100_000:
        evaluation_rows = all_evaluation_rows
        sampling_mode = "all_rows"
    else:
        evaluation_rows = [
            (entry.rank[0], entry.rank[1], entry.vector)
            for entry in sampled_evaluation_rows
        ]
        sampling_mode = "deterministic_hash_sample"
    evaluation_rows.sort(key=lambda item: (item[0], item[1]))
    if len(evaluation_rows) < 3:
        raise ValueError("CLUSTER_TOO_FEW_ROWS")
    evaluation_matrix = np.stack([item[2] for item in evaluation_rows])
    if len(np.unique(evaluation_matrix, axis=0)) < 2:
        raise ValueError("CLUSTER_SILHOUETTE_UNAVAILABLE")
    upper_k = min(max(2, int(max_k)), len(evaluation_matrix) - 1)
    if upper_k < 2:
        raise ValueError("CLUSTER_TOO_FEW_ROWS")
    scores: dict[int, float] = {}
    for k in range(2, upper_k + 1):
        labels = KMeans(n_clusters=k, random_state=seed, n_init=10).fit_predict(evaluation_matrix)
        if len(set(labels)) < 2:
            continue
        scores[k] = float(silhouette_score(evaluation_matrix, labels))
    if not scores:
        raise ValueError("CLUSTER_SILHOUETTE_UNAVAILABLE")
    selected_k = max(scores, key=lambda key: (scores[key], -key))

    final = KMeans(n_clusters=selected_k, random_state=seed, n_init=10).fit(evaluation_matrix)
    if expected_count <= 100_000:
        centers = final.cluster_centers_
        fit_algorithm = "sklearn_kmeans"
        fit_iterations = int(getattr(final, "n_iter_", 0))
    else:
        centers, fit_iterations = _fit_streaming_lloyd_kmeans(
            batches,
            columns=columns,
            scaler=scaler,
            weights_root=weights_root,
            initial_centers=final.cluster_centers_,
            expected_count=expected_count,
            on_batch=on_batch,
        )
        fit_algorithm = "streaming_full_batch_lloyd_kmeans"

    weights = {column: float(value) for column, value in zip(columns, raw_importance)}
    preprocessing = {
        "version": "weighted-clustering-v1",
        "fit_scope": "frozen_task_sample_scope",
        "fit_algorithm": fit_algorithm,
        "fit_iterations": fit_iterations,
        "feature_columns": tuple(columns),
        "standardizer": {
            "mean": tuple(float(value) for value in scaler.mean_),
            "scale": tuple(float(value) for value in scaler.scale_),
        },
    }
    return ClusterArtifact(
        labels=(),
        k_scores=scores,
        selected_k=selected_k,
        seed=int(seed),
        weights=weights,
        feature_map=FeatureMap(tuple(columns), {}),
        sample_count_evaluated=len(evaluation_rows),
        total_sample_count=expected_count,
        sampling_mode=sampling_mode,
        sampling_hash=_evaluation_sample_hash(
            evaluation_rows,
            task_revision=task_revision,
            seed=seed,
        ),
        preprocessing=preprocessing,
        centers=tuple(tuple(float(item) for item in row) for row in centers),
    )


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
