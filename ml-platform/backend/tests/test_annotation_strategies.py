from dataclasses import dataclass

import numpy as np
import pandas as pd
import pytest

from app.services import weighted_clustering
from app.services.annotation_strategies import (
    AnnotationDecision,
    AutomaticAnnotationConfig,
    StrategyConfigError,
    apply_annotation_strategy,
    validate_strategy_config,
    _model_outputs_from_package,
)
from app.services.label_schema import LabelColumnContract, LabelSchemaContract
from app.services.rule_dsl import RuleEvaluationError, evaluate_rule
from app.services.weighted_clustering import (
    FeatureMap,
    InputContract,
    aggregate_model_importance,
    assign_clusters_from_artifact,
    build_weighted_clusters,
    deterministic_sample_indices,
)


@pytest.fixture
def schema():
    return LabelSchemaContract(
        [
            LabelColumnContract("label_a", "string", required=True, enum_values=("a", "b", "other")),
            LabelColumnContract("label_b", "int", required=True, enum_values=(1, 2, 0)),
        ]
    )


def test_strategy_is_exclusive_and_fallback_is_required(schema):
    with pytest.raises(StrategyConfigError):
        validate_strategy_config(
            AutomaticAnnotationConfig(
                clustering=True,
                strategy="cluster_rule",
                cluster_labels={"1": {"label_a": "x"}},
                rules=[{"id": "r1", "when": {"score": {"gte": 0.5}}, "values": {"label_a": "y"}}],
                other_values={"label_a": "other", "label_b": 0},
            ),
            schema,
        )

    with pytest.raises(StrategyConfigError) as error:
        validate_strategy_config(
            AutomaticAnnotationConfig(
                clustering=True,
                strategy="cluster",
                cluster_labels={"1": {"label_a": "a", "label_b": 1}},
            ),
            schema,
        )
    assert error.value.code == "CLUSTER_FALLBACK_REQUIRED"


def test_model_output_ignores_cluster_when_clustering_disabled(schema):
    config = AutomaticAnnotationConfig(clustering=False, strategy=None)
    decision = apply_annotation_strategy(
        {"label_a": "a", "label_b": 1}, cluster_id=4, frame_row={"score": 0.9}, config=config, schema=schema
    )
    assert isinstance(decision, AnnotationDecision)
    assert decision.values == {"label_a": "a", "label_b": 1}
    assert decision.provenance["label_a"]["source"] == "model"


def test_cluster_rule_uses_rule_then_cluster_then_other_per_column(schema):
    config = AutomaticAnnotationConfig(
        clustering=True,
        strategy="cluster_rule",
        selected_clusters=["2"],
        cluster_labels={"2": {"label_a": "a", "label_b": 2}},
        rules=[{"id": "r1", "when": {"score": {"gte": 0.5}}, "values": {"label_a": "b"}}],
        other_values={"label_a": "other", "label_b": 0},
    )
    decision = apply_annotation_strategy(
        {"label_a": "a", "label_b": 1}, cluster_id=2, frame_row={"score": 0.9}, config=config, schema=schema
    )
    assert decision.values == {"label_a": "b", "label_b": 2}
    assert decision.provenance["label_a"]["source"] == "rule"
    assert decision.provenance["label_b"]["source"] == "cluster"


def test_same_priority_rule_conflict_needs_review(schema):
    config = AutomaticAnnotationConfig(
        clustering=True,
        strategy="rule",
        rules=[
            {"id": "r1", "when": {"score": {"gte": 0.5}}, "values": {"label_a": "a"}},
            {"id": "r2", "when": {"score": {"gte": 0.5}}, "values": {"label_a": "b"}},
        ],
        other_values={"label_a": "other", "label_b": 0},
    )
    decision = apply_annotation_strategy(
        {"label_a": "a", "label_b": 1}, cluster_id=None, frame_row={"score": 0.9}, config=config, schema=schema
    )
    assert decision.status == "needs_review"
    assert decision.values["label_a"] is None


def test_rule_priority_is_resolved_per_label_column(schema):
    config = AutomaticAnnotationConfig(
        clustering=True, strategy="rule",
        rules=[
            {"id": "low", "priority": 10, "when": {"score": {"gte": 0}}, "values": {"label_a": "a", "label_b": 2}},
            {"id": "high", "priority": 0, "when": {"score": {"gte": 0}}, "values": {"label_a": "b"}},
        ], other_values={"label_a": "other", "label_b": 0},
    )
    result = apply_annotation_strategy({"label_a": "a", "label_b": 1}, 1, {"score": 1}, config, schema)
    assert result.status == "ready"
    assert result.values == {"label_a": "b", "label_b": 2}


def test_unselected_cluster_does_not_enter_rule_scope(schema):
    config = AutomaticAnnotationConfig(
        clustering=True, strategy="cluster_rule", selected_clusters=["2"],
        cluster_labels={"2": {"label_a": "a", "label_b": 1}},
        rules=[{"id": "r", "when": {"score": {"gte": 0}}, "values": {"label_a": "b"}}],
        other_values={"label_a": "other", "label_b": 0},
    )
    result = apply_annotation_strategy({"label_a": "a", "label_b": 1}, 1, {"score": 1}, config, schema)
    assert result.values == {"label_a": "other", "label_b": 0}
    assert result.matched_rule_ids == ()


def test_selected_cluster_requires_every_frozen_label_value(schema):
    with pytest.raises(StrategyConfigError) as error:
        validate_strategy_config(
            AutomaticAnnotationConfig(
                clustering=True,
                strategy="cluster",
                selected_clusters=["2"],
                cluster_labels={"2": {"label_a": "a"}},
                other_values={"label_a": "other", "label_b": 0},
            ),
            schema,
        )
    assert error.value.code == "CLUSTER_MAPPING_REQUIRED"


def test_cluster_discovery_is_a_separate_incomplete_configuration(schema):
    validate_strategy_config(
        AutomaticAnnotationConfig(
            clustering=True,
            cluster_discovery=True,
        ),
        schema,
    )


def test_rule_configuration_rejects_string_number_for_numeric_source(schema):
    with pytest.raises(StrategyConfigError) as error:
        validate_strategy_config(
            AutomaticAnnotationConfig(
                clustering=True,
                strategy="rule",
                rules=[{"id": "r1", "when": {"score": {"gte": "0.5"}}, "values": {"label_a": "a"}}],
                other_values={"label_a": "other", "label_b": 0},
            ),
            schema,
            source_column_types={"score": "float64"},
        )
    assert error.value.code == "RULE_VALUE_TYPE_INVALID"

    validate_strategy_config(
        AutomaticAnnotationConfig(
            clustering=True,
            strategy="rule",
            rules=[{"id": "r1", "when": {"score": {"gte": 0.5}}, "values": {"label_a": "a"}}],
            other_values={"label_a": "other", "label_b": 0},
        ),
        schema,
        source_column_types={"score": "float64"},
    )


def test_model_output_must_match_the_frozen_contract(schema):
    with pytest.raises(StrategyConfigError) as error:
        apply_annotation_strategy(
            {"label_a": "a"},
            cluster_id=None,
            frame_row={},
            config=AutomaticAnnotationConfig(clustering=False),
            schema=schema,
        )
    assert error.value.code == "MODEL_OUTPUT_INVALID"


@pytest.mark.parametrize("predictions", [
    np.array(["a"]),
    np.array(["a", "b", "a"]),
    np.array([["a", "b"], ["b", "a"]]),
    np.array("a"),
])
def test_model_prediction_shape_must_match_sample_and_target_counts(predictions):
    class Model:
        def predict(self, frame):
            return predictions

    schema = LabelSchemaContract([LabelColumnContract("label", "string", required=True)])
    with pytest.raises(StrategyConfigError) as error:
        _model_outputs_from_package(
            {"model": Model(), "input_contract": {"feature_columns": ["x"]}},
            {"s-1": {"x": 1}, "s-2": {"x": 2}},
            schema,
        )
    assert error.value.code == "MODEL_OUTPUT_INVALID"


def test_single_target_column_matrix_preserves_sample_order_and_values():
    class Model:
        def predict(self, frame):
            return np.array([["b"], ["a"]])

    schema = LabelSchemaContract([LabelColumnContract("label", "string", required=True)])
    result = _model_outputs_from_package(
        {"model": Model(), "input_contract": {"feature_columns": ["x"]}},
        {"s-2": {"x": 2}, "s-1": {"x": 1}},
        schema,
    )
    assert list(result) == ["s-2", "s-1"]
    assert result == {"s-2": {"label": "b"}, "s-1": {"label": "a"}}


def test_rule_dsl_supports_typed_comparisons_and_rejects_unknown_operator():
    assert evaluate_rule({"score": {"gte": 0.5, "lt": 1}}, {"score": 0.75}) is True
    with pytest.raises(RuleEvaluationError):
        evaluate_rule({"score": {"contains": "x"}}, {"score": "x"})


def test_aggregate_model_importance_restores_one_hot_and_averages_targets():
    feature_map = FeatureMap(("age", "color"), {"color": (1, 2)})
    result = aggregate_model_importance(
        {"target_a": [1.0, 0.0, 1.0], "target_b": [0.0, 1.0, 1.0]}, feature_map
    )
    assert result.values == pytest.approx({"age": 0.25, "color": 0.75})
    assert result.source == "model"


def test_weighted_kmeans_scores_k_2_to_8_and_assigns_all_rows():
    frame = pd.DataFrame({"x": np.r_[np.zeros(12), np.ones(12)], "y": np.r_[np.zeros(12), np.ones(12)]})
    contract = InputContract(feature_columns=("x", "y"))

    class Model:
        feature_importances_ = np.array([3.0, 1.0])

    artifact = build_weighted_clusters(frame, Model(), contract, seed=7)
    assert set(artifact.k_scores) <= set(range(2, 9))
    assert len(artifact.labels) == len(frame)
    assert artifact.sample_count_evaluated <= 50000
    assert artifact.seed == 7


def test_streaming_weighted_kmeans_fits_frozen_artifact_without_a_full_input_frame():
    frame = pd.DataFrame({
        "x": [0.0, 0.1, 0.2, 5.0, 5.1, 5.2],
        "y": [0.0, 0.2, 0.1, 5.0, 5.2, 5.1],
    })
    sample_ids = tuple(f"sample-{index}" for index in range(len(frame)))
    calls = []

    def batches():
        calls.append(True)
        for start in range(0, len(frame), 2):
            yield sample_ids[start:start + 2], frame.iloc[start:start + 2].copy()

    class Model:
        feature_importances_ = np.array([3.0, 1.0])

    builder = getattr(weighted_clustering, "build_weighted_clusters_streaming", None)
    assert callable(builder)
    artifact = builder(
        batches,
        Model(),
        InputContract(feature_columns=("x", "y")),
        seed=7,
        task_revision=2,
        total_sample_count=len(frame),
    )

    assert len(calls) >= 2
    assert artifact.labels == ()
    assert artifact.total_sample_count == len(frame)
    assert artifact.sample_count_evaluated == len(frame)
    assert artifact.preprocessing["fit_scope"] == "frozen_task_sample_scope"
    assert len(assign_clusters_from_artifact(frame, artifact)) == len(frame)


def test_large_streaming_kmeans_scans_full_scope_after_deterministic_k_evaluation(monkeypatch):
    row_count = 100_001
    frame = pd.DataFrame({
        "x": np.arange(row_count, dtype=float),
        "y": np.arange(row_count, dtype=float) % 5,
    })
    sample_ids = tuple(f"sample-{index}" for index in range(row_count))
    source_passes = []
    fitted_sizes = []

    def batches():
        source_passes.append(True)
        for start in range(0, row_count, 20_000):
            yield sample_ids[start:start + 20_000], frame.iloc[start:start + 20_000].copy()

    class Model:
        feature_importances_ = np.array([3.0, 1.0])

    class FastKMeans:
        def __init__(self, n_clusters, random_state, n_init):
            self.n_clusters = n_clusters

        def fit_predict(self, values):
            return np.arange(len(values)) % self.n_clusters

        def fit(self, values):
            fitted_sizes.append(len(values))
            positions = np.linspace(0, len(values) - 1, self.n_clusters, dtype=int)
            if self.n_clusters == 2:
                positions = np.array([np.argmin(values[:, 0]), np.argmax(values[:, 0])])
            self.cluster_centers_ = np.asarray(values)[positions].copy()
            return self

    monkeypatch.setattr(weighted_clustering, "KMeans", FastKMeans)
    monkeypatch.setattr(weighted_clustering, "silhouette_score", lambda _values, _labels: 0.5)

    artifact = weighted_clustering.build_weighted_clusters_streaming(
        batches,
        Model(),
        InputContract(feature_columns=("x", "y")),
        seed=13,
        task_revision=5,
        total_sample_count=row_count,
    )

    assert artifact.sampling_mode == "deterministic_hash_sample"
    assert artifact.sample_count_evaluated == 50_000
    assert artifact.preprocessing["fit_algorithm"] == "streaming_full_batch_lloyd_kmeans"
    assert fitted_sizes == [50_000]
    assert len(source_passes) >= 3
    assert len(assign_clusters_from_artifact(frame.iloc[:10], artifact)) == 10


def test_large_cluster_evaluation_sampling_is_stable_by_sample_id_revision_and_seed():
    sample_ids = ("sample-c", "sample-a", "sample-d", "sample-b")
    first_indices, first_hash = deterministic_sample_indices(sample_ids, task_revision=3, seed=7, limit=2)
    second_indices, second_hash = deterministic_sample_indices(sample_ids, task_revision=3, seed=7, limit=2)
    reordered = ("sample-b", "sample-d", "sample-a", "sample-c")
    reordered_indices, reordered_hash = deterministic_sample_indices(reordered, task_revision=3, seed=7, limit=2)

    assert tuple(first_indices) == tuple(second_indices)
    assert first_hash == second_hash
    assert {sample_ids[index] for index in first_indices} == {reordered[index] for index in reordered_indices}
    assert first_hash == reordered_hash
    assert deterministic_sample_indices(sample_ids, task_revision=4, seed=7, limit=2)[1] != first_hash


def test_large_cluster_evaluation_uses_supplied_sample_ids_and_records_metadata(monkeypatch):
    row_count = 100_001
    frame = pd.DataFrame(
        {
            "x": np.arange(row_count, dtype=float),
            "y": np.arange(row_count, dtype=float) % 7,
        },
        index=tuple(f"row-{index}" for index in range(row_count)),
    )
    sample_ids = tuple(f"sample-{index}" for index in range(row_count))

    class Model:
        feature_importances_ = np.array([3.0, 1.0])

    class FastKMeans:
        def __init__(self, n_clusters, random_state, n_init):
            self.n_clusters = n_clusters

        def fit_predict(self, values):
            return np.arange(len(values)) % self.n_clusters

        def fit(self, values):
            self.labels_ = np.arange(len(values)) % self.n_clusters
            self.cluster_centers_ = np.zeros((self.n_clusters, values.shape[1]))
            return self

    monkeypatch.setattr(weighted_clustering, "KMeans", FastKMeans)
    monkeypatch.setattr(weighted_clustering, "silhouette_score", lambda _values, _labels: 0.5)

    _, expected_hash = deterministic_sample_indices(sample_ids, task_revision=5, seed=13)
    artifact = build_weighted_clusters(
        frame,
        Model(),
        InputContract(feature_columns=("x", "y")),
        seed=13,
        task_revision=5,
        sample_ids=sample_ids,
    )

    assert artifact.sampling_mode == "deterministic_hash_sample"
    assert artifact.sample_count_evaluated == 50_000
    assert artifact.total_sample_count == row_count
    assert artifact.sampling_hash == expected_hash


def test_unavailable_model_importance_marks_review_instead_of_fabricating_weights():
    frame = pd.DataFrame({"x": np.arange(8), "y": np.arange(8)})
    contract = InputContract(feature_columns=("x", "y"))

    class Model:
        feature_importances_ = np.array([0.0, 0.0])

    with pytest.raises(ValueError, match="FEATURE_IMPORTANCE_UNAVAILABLE"):
        build_weighted_clusters(frame, Model(), contract, seed=3)


def test_missing_model_importance_is_explicitly_unavailable():
    result = aggregate_model_importance({}, FeatureMap(("x", "y"), {}))
    assert result.source == "unavailable"
    assert result.values == {"x": 0.0, "y": 0.0}


def test_weighted_kmeans_reads_feature_importance_from_a_fitted_pipeline():
    from sklearn.ensemble import RandomForestClassifier
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler

    frame = pd.DataFrame({"x": [0.0, 0.1, 0.2, 5.0, 5.1, 5.2], "y": [0.0, 0.2, 0.1, 5.0, 5.2, 5.1]})
    model = make_pipeline(StandardScaler(), RandomForestClassifier(n_estimators=8, random_state=7)).fit(frame, [0, 0, 0, 1, 1, 1])
    artifact = build_weighted_clusters(frame, model, InputContract(feature_columns=("x", "y")), seed=7)
    assert len(artifact.labels) == len(frame)
    assert sum(artifact.weights.values()) == pytest.approx(1.0)


def test_frozen_cluster_artifact_reuses_preprocessing_and_centers_for_assignment():
    frame = pd.DataFrame({
        "x": [0.0, 0.1, 0.2, 5.0, 5.1, 5.2],
        "y": [0.0, 0.2, 0.1, 5.0, 5.2, 5.1],
    })

    class Model:
        feature_importances_ = np.array([3.0, 1.0])

    artifact = build_weighted_clusters(frame, Model(), InputContract(feature_columns=("x", "y")), seed=7)

    assert artifact.preprocessing["fit_scope"] == "frozen_task_sample_scope"
    assert artifact.preprocessing["feature_columns"] == ("x", "y")
    assert tuple(assign_clusters_from_artifact(frame, artifact)) == artifact.labels


def test_weighted_kmeans_uses_frozen_importance_when_model_has_no_native_vector():
    frame = pd.DataFrame({
        "x": [0.0, 0.1, 0.2, 5.0, 5.1, 5.2],
        "y": [0.0, 0.2, 0.1, 5.0, 5.2, 5.1],
    })

    artifact = build_weighted_clusters(
        frame,
        object(),
        InputContract(feature_columns=("x", "y")),
        seed=7,
        feature_importance={"x": 3.0, "y": 1.0},
    )

    assert artifact.weights == pytest.approx({"x": 0.75, "y": 0.25})
