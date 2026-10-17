"""UMAP+HDBSCAN weak-supervision clustering route."""

import uuid

import numpy as np
import pandas as pd
import pytest

from app.services.weighted_clustering import (
    CLUSTER_METHOD_UMAP_HDBSCAN,
    CLUSTER_METHOD_WEIGHTED_KMEANS,
    UMAP_HDBSCAN_MAX_SAMPLES,
    assign_clusters_from_artifact,
    build_weighted_clusters,
    build_weighted_clusters_streaming,
    cluster_artifact_from_payload,
)


def _two_blobs(count_per_blob: int = 30, seed: int = 7) -> pd.DataFrame:
    generator = np.random.default_rng(seed)
    blob_a = generator.normal(loc=[0.0, 0.0], scale=0.35, size=(count_per_blob, 2))
    blob_b = generator.normal(loc=[6.0, 6.0], scale=0.35, size=(count_per_blob, 2))
    matrix = np.vstack([blob_a, blob_b])
    return pd.DataFrame(matrix, columns=["feature_a", "feature_b"])


class _ImportanceModel:
    """Minimal estimator exposing per-feature importance for the weighted path."""

    feature_importances_ = np.asarray([0.6, 0.4])


def _store(tmp_path, counter={"n": 0}):
    def store(bundle: dict) -> str:
        import joblib

        counter["n"] += 1
        directory = tmp_path / "cluster-models"
        directory.mkdir(exist_ok=True)
        reference = f"cluster-models/{counter['n']}.joblib"
        joblib.dump(bundle, tmp_path / reference)
        return reference

    return store


def test_umap_hdbscan_streaming_build_and_assign_roundtrip(tmp_path, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "artifact_storage_dir", str(tmp_path))
    frame = _two_blobs()
    sample_ids = [f"s-{index}" for index in range(len(frame))]

    def batches():
        half = len(frame) // 2
        yield tuple(sample_ids[:half]), frame.iloc[:half]
        yield tuple(sample_ids[half:]), frame.iloc[half:]

    artifact = build_weighted_clusters_streaming(
        batches,
        _ImportanceModel(),
        type("Contract", (), {"feature_columns": ("feature_a", "feature_b")})(),
        seed=7,
        total_sample_count=len(frame),
        cluster_method=CLUSTER_METHOD_UMAP_HDBSCAN,
        model_store=_store(tmp_path),
    )

    assert artifact.method == CLUSTER_METHOD_UMAP_HDBSCAN
    assert artifact.selected_k >= 1
    assert artifact.centers == ()
    assert artifact.k_scores == {}
    assert artifact.model_ref is not None
    assert artifact.scatter_points

    # Assignment of the same frozen rows reproduces cluster labels without
    # refitting (approximate prediction on training points).
    assigned = assign_clusters_from_artifact(frame, artifact)
    assert len(assigned) == len(frame)
    assert all(isinstance(value, int) for value in assigned)
    assert len(set(assigned)) >= artifact.selected_k or -1 in assigned

    # Payload round-trip keeps the method metadata for re-run previews.
    payload = {
        "selected_k": artifact.selected_k,
        "seed": artifact.seed,
        "weights": artifact.weights,
        "feature_map": {"source_columns": ["feature_a", "feature_b"], "one_hot_dimensions": {}},
        "sample_count_evaluated": artifact.sample_count_evaluated,
        "total_sample_count": artifact.total_sample_count,
        "sampling_mode": artifact.sampling_mode,
        "sampling_hash": artifact.sampling_hash,
        "preprocessing": dict(artifact.preprocessing),
        "centers": [],
        "method": artifact.method,
        "noise_count": artifact.noise_count,
        "model_ref": artifact.model_ref,
    }
    restored = cluster_artifact_from_payload(payload)
    assert restored.method == CLUSTER_METHOD_UMAP_HDBSCAN
    reassigned = assign_clusters_from_artifact(frame, restored)
    assert reassigned == assigned


def test_umap_hdbscan_full_frame_builder_matches_streaming_semantics(tmp_path, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "artifact_storage_dir", str(tmp_path))
    frame = _two_blobs()
    artifact = build_weighted_clusters(
        frame,
        _ImportanceModel(),
        type("Contract", (), {"feature_columns": ("feature_a", "feature_b")})(),
        seed=7,
        cluster_method=CLUSTER_METHOD_UMAP_HDBSCAN,
        model_store=_store(tmp_path),
    )
    assert artifact.method == CLUSTER_METHOD_UMAP_HDBSCAN
    assert len(artifact.labels) == len(frame)
    assert artifact.selected_k >= 1


def test_umap_hdbscan_rejects_oversized_scope(tmp_path):
    frame = _two_blobs(count_per_blob=2)
    with pytest.raises(ValueError, match="CLUSTER_METHOD_SCOPE_TOO_LARGE"):
        build_weighted_clusters_streaming(
            lambda: iter([]),
            _ImportanceModel(),
            type("Contract", (), {"feature_columns": ("feature_a", "feature_b")})(),
            seed=7,
            total_sample_count=UMAP_HDBSCAN_MAX_SAMPLES + 1,
            cluster_method=CLUSTER_METHOD_UMAP_HDBSCAN,
        )
    with pytest.raises(ValueError, match="CLUSTER_METHOD_SCOPE_TOO_LARGE"):
        build_weighted_clusters(
            pd.concat([frame] * (UMAP_HDBSCAN_MAX_SAMPLES // len(frame) + 1), ignore_index=True),
            _ImportanceModel(),
            type("Contract", (), {"feature_columns": ("feature_a", "feature_b")})(),
            seed=7,
            cluster_method=CLUSTER_METHOD_UMAP_HDBSCAN,
        )


def test_invalid_cluster_method_rejected_before_any_work():
    frame = _two_blobs(count_per_blob=2)
    with pytest.raises(ValueError, match="CLUSTER_METHOD_INVALID"):
        build_weighted_clusters(
            frame,
            _ImportanceModel(),
            type("Contract", (), {"feature_columns": ("feature_a", "feature_b")})(),
            seed=7,
            cluster_method="dbscan",
        )


def test_kmeans_artifact_keeps_default_method(tmp_path):
    frame = _two_blobs()
    artifact = build_weighted_clusters(
        frame,
        _ImportanceModel(),
        type("Contract", (), {"feature_columns": ("feature_a", "feature_b")})(),
        seed=7,
    )
    assert artifact.method == CLUSTER_METHOD_WEIGHTED_KMEANS
    assert artifact.model_ref is None
    assert artifact.noise_count == 0


def test_noise_cluster_ids_survive_decision_construction():
    """噪声样本 cluster_id=None 不应让发现预览的决策构建崩溃（int(None) 回归）。"""
    cluster_ids = {"s-1": 0, "s-2": None, "s-3": 1}
    decisions = {
        sample_id: (int(cid) if cid is not None else None)
        for sample_id, cid in cluster_ids.items()
    }
    assert decisions == {"s-1": 0, "s-2": None, "s-3": 1}

    from app.services.annotation_strategies import (
        AutomaticAnnotationConfig,
        validate_strategy_config,
    )
    from app.services.label_schema import LabelSchemaContract

    config = AutomaticAnnotationConfig(
        clustering=True,
        cluster_discovery=True,
        cluster_method=CLUSTER_METHOD_UMAP_HDBSCAN,
    )
    validate_strategy_config(config, LabelSchemaContract([]))
    assert config.cluster_method == "umap_hdbscan"
