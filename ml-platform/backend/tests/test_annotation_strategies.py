from dataclasses import dataclass
import uuid

import numpy as np
import pandas as pd
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models.data_version import DatasetSample, DatasetSchemaColumn, DatasetVersion
from app.models.labeling import AnnotationStrategyArtifact, AnnotationStrategyDecision, LabelColumn, LabelSchema
from app.models.platform_models import GenericAnnotationTask
from app.models.project import Project
from app.models.user import User
from app.services import weighted_clustering
from app.services.annotation_strategies import (
    AnnotationDecision,
    AutomaticAnnotationConfig,
    StrategyConfigError,
    apply_annotation_strategy,
    strategy_matched_scope_entries,
    validate_strategy_config,
    _model_outputs_from_package,
)
from app.services.annotation_scope import persist_scope_entries
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
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, expire_on_commit=False)()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


@pytest.fixture
def schema():
    return LabelSchemaContract(
        [
            LabelColumnContract("label_a", "string", required=True, enum_values=("a", "b", "other")),
            LabelColumnContract("label_b", "int", required=True, enum_values=(1, 2, 0)),
        ]
    )


def test_strategy_is_exclusive_and_selection_is_required(schema):
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
    assert error.value.code == "CLUSTER_SELECTION_REQUIRED"


def test_fallback_is_optional_and_unmatched_samples_need_review(schema):
    config = AutomaticAnnotationConfig(
        clustering=True,
        strategy="cluster",
        selected_clusters=["1"],
        cluster_labels={"1": {"label_a": "a", "label_b": 1}},
    )
    validate_strategy_config(config, schema)
    matched = apply_annotation_strategy({"label_a": "a", "label_b": 1}, 1, {"score": 0.1}, config, schema)
    assert matched.status == "ready"
    assert matched.values == {"label_a": "a", "label_b": 1}
    unmatched = apply_annotation_strategy({"label_a": "a", "label_b": 1}, 3, {"score": 0.1}, config, schema)
    assert unmatched.status == "needs_review"
    assert unmatched.values == {"label_a": None, "label_b": None}
    assert unmatched.provenance["label_a"]["source"] == "none"


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


def test_cluster_rule_requires_rule_match_for_cluster_labels(schema):
    """簇加规则：簇与规则同时命中才算命中——仅簇命中的样本不能按簇映射打标。"""
    config = AutomaticAnnotationConfig(
        clustering=True,
        strategy="cluster_rule",
        selected_clusters=["2"],
        cluster_labels={"2": {"label_a": "a", "label_b": 2}},
        rules=[{"id": "r1", "when": {"score": {"gte": 0.5}}, "values": {"label_a": "b"}}],
        other_values={"label_a": "other", "label_b": 0},
    )
    hit = apply_annotation_strategy({"label_a": "a", "label_b": 1}, 2, {"score": 0.9}, config, schema)
    assert hit.status == "ready"
    assert hit.values == {"label_a": "b", "label_b": 2}
    # 仅簇命中但规则不匹配：走兜底值，而不是簇映射
    missed = apply_annotation_strategy({"label_a": "a", "label_b": 1}, 2, {"score": 0.1}, config, schema)
    assert missed.values == {"label_a": "other", "label_b": 0}
    assert missed.provenance["label_a"]["source"] == "other"
    # 无兜底值 → needs_review（转人工）
    bare = AutomaticAnnotationConfig(
        clustering=True,
        strategy="cluster_rule",
        selected_clusters=["2"],
        cluster_labels={"2": {"label_a": "a", "label_b": 2}},
        rules=[{"id": "r1", "when": {"score": {"gte": 0.5}}, "values": {"label_a": "b"}}],
    )
    unresolved = apply_annotation_strategy({"label_a": "a", "label_b": 1}, 2, {"score": 0.1}, bare, schema)
    assert unresolved.status == "needs_review"
    assert unresolved.values == {"label_a": None, "label_b": None}


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


def test_annotation_scope_validation(schema):
    valid = dict(clustering=True, strategy="cluster", selected_clusters=["1"], cluster_labels={"1": {"label_a": "a", "label_b": 1}})
    validate_strategy_config(AutomaticAnnotationConfig(**valid, annotation_scope="strategy_hits"), schema)
    validate_strategy_config(AutomaticAnnotationConfig(**valid, annotation_scope="all"), schema)
    with pytest.raises(StrategyConfigError) as error:
        validate_strategy_config(AutomaticAnnotationConfig(**valid, annotation_scope="bogus"), schema)
    assert error.value.code == "ANNOTATION_SCOPE_INVALID"
    # 模型原始输出路径（无策略）与簇发现阶段没有「策略命中」概念
    with pytest.raises(StrategyConfigError) as error:
        validate_strategy_config(AutomaticAnnotationConfig(clustering=False, annotation_scope="strategy_hits"), schema)
    assert error.value.code == "ANNOTATION_SCOPE_INVALID"
    with pytest.raises(StrategyConfigError) as error:
        validate_strategy_config(AutomaticAnnotationConfig(clustering=True, cluster_discovery=True, annotation_scope="strategy_hits"), schema)
    assert error.value.code == "ANNOTATION_SCOPE_INVALID"


def _matched_scope_fixture(db):
    user = User(username=f"scope-{uuid.uuid4().hex}", password_hash="hash")
    db.add(user)
    db.flush()
    project = Project(name="Scope project", owner_id=user.id)
    db.add(project)
    db.flush()
    version = DatasetVersion(
        project_id=project.id, operator_id=user.id, version=1,
        row_count=5, column_count=1, content_hash="sha256:scope-data", schema_hash="sha256:scope-schema",
    )
    db.add(version)
    db.flush()
    db.add(DatasetSchemaColumn(dataset_version_id=version.id, name="score", position=0, dtype="float", nullable=False))
    db.flush()
    # s1/s2 → 簇 0；s3/s4 → 簇 1；s5 → 噪声（不属于任何簇）；score 决定规则命中
    scores = {"s-1": 1.0, "s-2": 2.0, "s-3": 3.0, "s-4": 4.0, "s-5": 5.0}
    for index, (sample_id, score) in enumerate(scores.items()):
        db.add(DatasetSample(dataset_version_id=version.id, sample_id=sample_id, row_index=index, values={"score": score}))
    db.flush()
    schema = LabelSchema(project_id=project.id, name="scope-labels", version=1, status="active")
    db.add(schema)
    db.flush()
    db.add(LabelColumn(schema_id=schema.id, machine_key="label_a", display_name="A", ordinal=0, value_type="string"))
    task = GenericAnnotationTask(
        project_id=project.id, dataset_version_id=version.id, label_schema_id=schema.id,
        owner_id=user.id, mode="automatic", status="draft", task_revision=2,
        sample_scope={"kind": "all"},
        task_snapshot={"config_hash": "sha256:scope-task", "visible_columns": ["score"]},
    )
    db.add(task)
    db.flush()
    # 初始 revision（0）冻结全量 5 条；当前 revision（2）模拟已被此前保存收窄过
    persist_scope_entries(db, task.id, 0, [(sample_id, index) for index, sample_id in enumerate(scores)])
    persist_scope_entries(db, task.id, 2, [("s-1", 0), ("s-2", 1)])
    artifact = AnnotationStrategyArtifact(
        task_id=task.id, task_revision=0, config_hash="sha256:discovery",
        strategy="cluster_discovery", created_by=user.id,
        artifact={"configuration_complete": False, "cluster_artifact": {"assignment_storage": "annotation_strategy_decisions"}},
    )
    db.add(artifact)
    db.flush()
    cluster_of = {"s-1": 0, "s-2": 0, "s-3": 1, "s-4": 1, "s-5": None}
    for sample_id, cluster_id in cluster_of.items():
        db.add(AnnotationStrategyDecision(
            strategy_artifact_id=artifact.id, sample_id=sample_id, row_index=0,
            status="pending_configuration", values={}, provenance={}, model_output={},
            cluster_id=cluster_id, matched_rule_ids=[], decision_hash=f"sha256:{sample_id}",
        ))
    db.commit()
    return task, version


def test_strategy_matched_scope_entries_follows_cluster_selection_and_rules(db):
    task, _version = _matched_scope_fixture(db)
    snapshot = {"config_hash": "sha256:scope-task", "scope": {"storage": "annotation_task_scope_samples", "sample_count": 5, "scope_hash": "sha256:x"}}
    # 簇策略：命中=属于选中簇；即便当前 revision 已被收窄，也按初始全量范围求值
    cluster_config = {
        "clustering": True, "strategy": "cluster", "selected_clusters": ["0"],
        "cluster_labels": {"0": {"label_a": "a"}}, "annotation_scope": "strategy_hits",
    }
    assert strategy_matched_scope_entries(db, task, cluster_config, snapshot=snapshot) == [("s-1", 0), ("s-2", 1)]
    # 切换选中簇 → 命中随之变化
    other = {**cluster_config, "selected_clusters": ["1"]}
    assert strategy_matched_scope_entries(db, task, other, snapshot=snapshot) == [("s-3", 2), ("s-4", 3)]
    # 规则策略：命中=任一规则在冻结源数据上匹配（score>=3 → s-3/s-4/s-5）
    rule_config = {
        "clustering": True, "strategy": "rule",
        "rules": [{"id": "r1", "when": {"score": {"gte": 3}}, "values": {"label_a": "b"}}],
        "annotation_scope": "strategy_hits",
    }
    assert strategy_matched_scope_entries(db, task, rule_config, snapshot=snapshot) == [("s-3", 2), ("s-4", 3), ("s-5", 4)]
    # 规则不命中任何样本 → 空列表（调用方以 ANNOTATION_SCOPE_EMPTY 拒绝）
    no_match = {**rule_config, "rules": [{"id": "r1", "when": {"score": {"gte": 99}}, "values": {"label_a": "b"}}]}
    assert strategy_matched_scope_entries(db, task, no_match, snapshot=snapshot) == []
    # 簇加规则：簇与规则必须同时命中——选中簇 0 的 s-1/s-2 里只有 score>=2 的 s-2 命中；
    # 仅簇命中但规则不匹配的 s-1 不算命中，不能只按簇收窄
    cluster_rule_config = {
        "clustering": True, "strategy": "cluster_rule", "selected_clusters": ["0"],
        "cluster_labels": {"0": {"label_a": "a"}},
        "rules": [{"id": "r1", "when": {"score": {"gte": 2}}, "values": {"label_a": "b"}}],
        "annotation_scope": "strategy_hits",
    }
    assert strategy_matched_scope_entries(db, task, cluster_rule_config, snapshot=snapshot) == [("s-2", 1)]
    # 规则放宽到全部命中 → 等价于按簇
    loose = {**cluster_rule_config, "rules": [{"id": "r1", "when": {"score": {"gte": 0}}, "values": {"label_a": "b"}}]}
    assert strategy_matched_scope_entries(db, task, loose, snapshot=snapshot) == [("s-1", 0), ("s-2", 1)]
    # 选中簇内无任何规则匹配 → 空
    strict = {**cluster_rule_config, "rules": [{"id": "r1", "when": {"score": {"gte": 99}}, "values": {"label_a": "b"}}]}
    assert strategy_matched_scope_entries(db, task, strict, snapshot=snapshot) == []


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


def test_degenerate_weighted_space_blocks_in_memory_clustering():
    frame = pd.DataFrame({"x": [1.0, 1.0, 1.0], "y": [2.0, 2.0, 2.0]})

    class Model:
        feature_importances_ = np.array([0.5, 0.5])

    with pytest.raises(ValueError) as error:
        build_weighted_clusters(frame, Model(), InputContract(feature_columns=("x", "y")), seed=7)
    assert str(error.value) == "CLUSTER_DEGENERATE_FEATURE_SPACE"


def test_degenerate_weighted_space_blocks_streaming_clustering():
    frame = pd.DataFrame({"x": [1.0, 1.0, 1.0, 1.0], "y": [2.0, 2.0, 2.0, 2.0]})
    sample_ids = tuple(f"s-{index}" for index in range(len(frame)))

    def batches():
        yield sample_ids[:2], frame.iloc[:2].copy()
        yield sample_ids[2:], frame.iloc[2:].copy()

    class Model:
        feature_importances_ = np.array([0.5, 0.5])

    with pytest.raises(ValueError) as error:
        weighted_clustering.build_weighted_clusters_streaming(
            batches,
            Model(),
            InputContract(feature_columns=("x", "y")),
            seed=7,
            task_revision=1,
            total_sample_count=len(frame),
        )
    assert str(error.value) == "CLUSTER_DEGENERATE_FEATURE_SPACE"


def test_aggregate_model_importance_blocks_unmapped_dimensions():
    feature_map = FeatureMap(("age", "color"), {"color": (1, 2)})
    with pytest.raises(ValueError) as error:
        aggregate_model_importance({"target_a": [0.25, 0.25, 0.25, 0.25]}, feature_map)
    assert str(error.value).startswith("FEATURE_IMPORTANCE_UNMAPPED_DIMENSIONS:3")


def test_package_feature_map_aggregates_one_hot_importance():
    from app.services.annotation_strategies import _cluster_package_contract

    package = {
        "input_contract": {"feature_columns": ["age", "color"]},
        "feature_importance_report": {
            "source": "model_native",
            "per_target": {"t": [0.4, 0.3, 0.3]},
        },
        "feature_map": {"source_columns": ["age", "color"], "one_hot_dimensions": {"color": [1, 2]}},
    }
    columns, frozen, method, report, feature_map, encoding = _cluster_package_contract(package)
    assert columns == ("age", "color")
    assert frozen == pytest.approx({"age": 0.4, "color": 0.6})
    assert method == "model_native"
    assert encoding == "one_hot_aggregated"
    assert feature_map is not None


def test_package_feature_map_blocks_unmapped_interaction_dimensions():
    from app.services.annotation_strategies import _cluster_package_contract

    package = {
        "input_contract": {"feature_columns": ["age", "color"]},
        "feature_importance_report": {
            "source": "model_native",
            "per_target": {"t": [0.25, 0.25, 0.25, 0.25]},
        },
        "feature_map": {"source_columns": ["age", "color"], "one_hot_dimensions": {"color": [1, 2]}},
    }
    with pytest.raises(StrategyConfigError) as error:
        _cluster_package_contract(package)
    assert error.value.code == "FEATURE_IMPORTANCE_UNMAPPED_DIMENSIONS"


def test_permutation_importance_fallback_ranks_features_without_native_vector():
    from sklearn.linear_model import LinearRegression

    rng = np.random.default_rng(11)
    frame = pd.DataFrame({
        "signal": rng.normal(size=40),
        "noise": rng.normal(size=40),
    })
    target = frame["signal"] * 2.0 + rng.normal(scale=0.01, size=40)
    model = LinearRegression().fit(frame, target)

    class ImportanceFree:
        def __init__(self, inner):
            self._inner = inner

        def fit(self, values, target_values):
            self._inner.fit(values, target_values)
            return self

        def predict(self, values):
            return self._inner.predict(values)

        def score(self, values, target_values):
            return self._inner.score(values, target_values)

    artifact = build_weighted_clusters(
        frame,
        ImportanceFree(model),
        InputContract(feature_columns=("signal", "noise")),
        seed=7,
    )
    assert artifact.importance_method == "permutation"
    assert artifact.weights["signal"] > artifact.weights["noise"]
    assert artifact.weights["signal"] == pytest.approx(sum(artifact.weights.values()))
