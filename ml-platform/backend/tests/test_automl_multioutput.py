import numpy as np
import pandas as pd
import pytest

from app.models.model_library import ModelLibrary
from app.services.automl_execution import execute_automl_job
from app.services.automl_search import (
    AutoMLContract,
    CandidateSummary,
    SearchConfig,
    aggregate_feature_importance,
    normalize_task_type,
    rank_candidates,
    run_family_search,
    run_automl_search,
    validate_target_columns,
    classification_metrics,
    normalize_search_controls,
    iterative_stratified_splits,
    auc_tier,
)
from app.services.automl_execution import normalize_evaluation_config, resolve_automl_feature_columns
from sklearn.base import BaseEstimator, ClassifierMixin
from sklearn.impute import SimpleImputer
from sklearn.multioutput import MultiOutputClassifier
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler


def _frame():
    rng = np.random.default_rng(42)
    x = rng.normal(size=(40, 3))
    return pd.DataFrame({"x1": x[:, 0], "x2": x[:, 1], "x3": x[:, 2],
                         "label_a": (x[:, 0] > 0).astype(int),
                         "label_b": (x[:, 1] > 0).astype(int)})


def test_only_four_task_types_are_persisted():
    assert normalize_task_type("multilabel_classification") == "multioutput_classification"
    assert normalize_task_type("multiregression") == "multioutput_regression"
    with pytest.raises(Exception):
        normalize_task_type("industry_quality")


def test_multioutput_classification_uses_independent_targets_and_iterative_stratification():
    frame = _frame()
    contract = AutoMLContract(
        task_type="multioutput_classification", target_columns=["label_a", "label_b"],
        input_columns=["x1", "x2", "x3"], cross_validation_folds=5,
    )
    result = run_automl_search(frame, contract)
    assert result.per_target["label_a"].macro_f1 is not None
    assert result.per_target["label_b"].auc is not None
    assert result.cv_strategy == "iterative_stratified"

def test_two_fold_cv_is_supported_and_multioutput_worker_contract_is_real():
    frame = _frame()
    contract = AutoMLContract(task_type="multioutput_classification", target_columns=["label_a", "label_b"], input_columns=["x1", "x2", "x3"], cross_validation_folds=2)
    result = run_automl_search(frame, contract)
    assert result.cv_strategy == "iterative_stratified"
    assert normalize_evaluation_config(True, 2)["cross_validation_folds"] == 2


def test_multioutput_regression_search_reports_r2_rmse_and_mae():
    frame = _frame().assign(
        target_a=lambda data: data["x1"] * 1.5 + data["x2"],
        target_b=lambda data: data["x2"] * 2.0 - data["x3"],
    )
    contract = AutoMLContract(
        task_type="multioutput_regression",
        target_columns=["target_a", "target_b"],
        input_columns=["x1", "x2", "x3"],
        cross_validation_folds=3,
    )
    result = run_automl_search(frame, contract)
    for report in result.per_target.values():
        assert report.r2 is not None
        assert report.rmse is not None
        assert report.mae is not None


def test_candidate_ranking_is_auc_then_f1_then_accuracy_then_runtime():
    ranked = rank_candidates([
        CandidateSummary("a", auc=0.90, macro_f1=0.60, accuracy=0.80, runtime_s=20),
        CandidateSummary("b", auc=0.90, macro_f1=0.60, accuracy=0.80, runtime_s=10),
    ], "classification")
    assert [item.algorithm_id for item in ranked] == ["b", "a"]


def test_regression_candidate_ranking_is_r2_then_rmse_then_mae_then_runtime():
    ranked = rank_candidates([
        CandidateSummary("higher_r2", runtime_s=20, r2=0.90, rmse=0.8, mae=0.5),
        CandidateSummary("lower_rmse", runtime_s=10, r2=0.90, rmse=0.7, mae=0.9),
        CandidateSummary("faster_tie", runtime_s=5, r2=0.90, rmse=0.8, mae=0.5),
    ], "regression")
    assert [item.algorithm_id for item in ranked] == ["lower_rmse", "faster_tie", "higher_r2"]


def test_target_validation_rejects_missing_nonfinite_and_leakage():
    frame = _frame()
    with pytest.raises(Exception):
        validate_target_columns(frame.assign(label_a=np.nan), "multioutput_classification", ["label_a", "label_b"])
    with pytest.raises(Exception):
        validate_target_columns(frame.assign(label_a=np.inf), "multioutput_regression", ["label_a", "label_b"])
    with pytest.raises(Exception):
        validate_target_columns(frame, "multioutput_classification", ["label_a", "label_a"])
    with pytest.raises(Exception):
        validate_target_columns(frame.assign(label_a=np.linspace(0.0, 1.0, len(frame))), "classification", ["label_a"])
    with pytest.raises(Exception):
        validate_target_columns(frame.assign(label_a=["a"] * len(frame)), "regression", ["label_a"])


def test_default_features_exclude_every_target_column():
    frame = _frame().assign(label_c=np.arange(40))
    assert resolve_automl_feature_columns(frame, None, None, target_columns=["label_a", "label_b", "label_c"]) == ["x1", "x2", "x3"]


class DecisionOnlyClassifier(ClassifierMixin, BaseEstimator):
    def fit(self, X, y):
        self.classes_ = np.array([0, 1])
        return self

    def predict(self, X):
        return np.zeros(len(X), dtype=int)

    def decision_function(self, X):
        return np.linspace(-1.0, 1.0, len(X))


def test_auc_falls_back_to_decision_function_when_predict_proba_missing():
    frame = _frame()
    auc, f1 = classification_metrics(
        DecisionOnlyClassifier(),
        features=frame[["x1", "x2", "x3"]],
        target=frame["label_a"].to_numpy(),
        evaluation={"cross_validation_enabled": False, "cross_validation_folds": None},
    )
    assert auc is not None
    assert f1 is not None


def test_search_controls_expose_four_strengths_and_time_budgets():
    for strength in ("light", "medium", "high", "ultra"):
        config = normalize_search_controls(strength=strength, time_budget=3600, class_weight=True)
        assert config["strength"] == strength
        assert config["class_weight"] is True
    for budget in (1800, 3600, 7200, 14400):
        assert normalize_search_controls(strength="medium", time_budget=budget)["time_budget"] == budget


def test_search_controls_enable_class_weight_by_default():
    assert normalize_search_controls(time_budget=3600)["class_weight"] is True


def test_multioutput_fold_assignments_use_joint_labels():
    frame = _frame()
    splits = iterative_stratified_splits(frame[["label_a", "label_b"]], n_splits=2, random_seed=42)
    assert len(splits) == 2
    assert set(np.concatenate([test for _, test in splits])) == set(range(len(frame)))
    assert all(len(train) + len(test) == len(frame) for train, test in splits)


def test_iterative_stratification_balances_each_target_label():
    targets = pd.DataFrame({"a": [1] * 8 + [0] * 12, "b": [1, 0] * 10, "c": [1, 0, 0, 0, 0] * 4})
    splits = iterative_stratified_splits(targets, n_splits=2, random_seed=42)
    for column in targets.columns:
        positives = [int(targets.iloc[test][column].sum()) for _train, test in splits]
        assert max(positives) - min(positives) <= 1


def test_auc_tier_marks_incomplete_when_any_target_has_no_continuous_score():
    assert auc_tier({"label_a": 0.8, "label_b": 0.7}) == "complete"
    assert auc_tier({"label_a": 0.8, "label_b": None}) == "incomplete"


def test_fold_auc_aligns_score_columns_to_global_class_order():
    from app.services.automl_execution import _aggregate_fold_classification_metrics

    target = np.array(["a", "b", "c", "a", "b", "c"])
    predictions = target.copy()
    fold_scores = [
        (np.array([0, 1, 2]), np.eye(3), np.array(["a", "b", "c"])),
        (
            np.array([3, 4, 5]),
            np.array([[0.0, 1.0, 0.0], [0.0, 0.0, 1.0], [1.0, 0.0, 0.0]]),
            np.array(["c", "a", "b"]),
        ),
    ]

    report = _aggregate_fold_classification_metrics(target, predictions, fold_scores)

    assert report["auc"] == 1.0


def test_feature_importance_aggregates_per_target():
    report = aggregate_feature_importance({"a": [1.0, 3.0], "b": [3.0, 1.0]}, ["x1", "x2"])
    assert report.by_feature["x1"] == 2.0
    assert report.by_feature["x2"] == 2.0


def test_grid_family_search_suggests_only_cartesian_grid_parameters():
    from app.services.automl_catalog import resolve_algorithm_families

    family = resolve_algorithm_families(["random_forest"])[0]
    result = run_family_search(
        family=family,
        task="classification",
        features=np.array([[0.0, 0.0], [1.0, 1.0]] * 10),
        target=np.array([0, 1] * 10),
        evaluation={"cross_validation_enabled": False, "cross_validation_folds": None},
        config=SearchConfig(method="grid", max_trials=3, timeout_seconds=10),
        catalog_index=0,
        estimator_evaluator=lambda estimator, **_kwargs: float(estimator.get_params()["n_estimators"]),
    )

    assert result.completed_trials == 3
    assert all(set(trial.params).issubset(family.grid) for trial in result.trials)


def test_family_search_supports_an_explicit_multioutput_estimator_builder():
    from app.services.automl_catalog import resolve_algorithm_families

    frame = _frame()
    family = resolve_algorithm_families(["random_forest"])[0]
    result = run_family_search(
        family=family,
        task="multioutput_classification",
        features=frame[["x1", "x2", "x3"]].to_numpy(),
        target=frame[["label_a", "label_b"]].to_numpy(),
        evaluation={"cross_validation_enabled": False, "cross_validation_folds": None},
        config=SearchConfig(method="random", max_trials=1, timeout_seconds=10),
        catalog_index=0,
        estimator_builder=lambda current_family, task, params: MultiOutputClassifier(
            make_pipeline(
                SimpleImputer(strategy="median"),
                StandardScaler(),
                current_family.build(task, params),
            ),
        ),
        estimator_evaluator=lambda _estimator, **_kwargs: 0.8,
    )

    assert result.status == "completed"
    assert isinstance(result.best_estimator, MultiOutputClassifier)


def test_worker_does_not_create_model_library_record():
    import inspect
    source = inspect.getsource(execute_automl_job)
    assert "db.add(model_entry)" not in source

def test_registry_result_accepts_candidate_artifact_identity():
    from app.services.model_registry import ModelRegistryService, ModelRegistryError
    from types import SimpleNamespace
    job = SimpleNamespace(status="completed", metrics={"algorithm_results":[{"algorithm_id":"rf", "status":"completed", "model_artifact_id":"abc"}]})
    result = ModelRegistryService._automl_result(job, "rf")
    assert result["model_artifact_id"] == "abc"
