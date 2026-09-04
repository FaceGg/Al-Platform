import numpy as np
import pandas as pd
import pytest

from app.models.model_library import ModelLibrary
from app.services.automl_execution import execute_automl_job
from app.services.automl_search import (
    AutoMLContract,
    CandidateSummary,
    aggregate_feature_importance,
    normalize_task_type,
    rank_candidates,
    run_automl_search,
    validate_target_columns,
)


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


def test_candidate_ranking_is_auc_then_f1_then_accuracy_then_runtime():
    ranked = rank_candidates([
        CandidateSummary("a", auc=0.90, macro_f1=0.60, accuracy=0.80, runtime_s=20),
        CandidateSummary("b", auc=0.90, macro_f1=0.60, accuracy=0.80, runtime_s=10),
    ], "classification")
    assert [item.algorithm_id for item in ranked] == ["b", "a"]


def test_target_validation_rejects_missing_nonfinite_and_leakage():
    frame = _frame()
    with pytest.raises(Exception):
        validate_target_columns(frame.assign(label_a=np.nan), "multioutput_classification", ["label_a", "label_b"])
    with pytest.raises(Exception):
        validate_target_columns(frame.assign(label_a=np.inf), "multioutput_regression", ["label_a", "label_b"])
    with pytest.raises(Exception):
        validate_target_columns(frame, "multioutput_classification", ["label_a", "label_a"])


def test_feature_importance_aggregates_per_target():
    report = aggregate_feature_importance({"a": [1.0, 3.0], "b": [3.0, 1.0]}, ["x1", "x2"])
    assert report.by_feature["x1"] == 2.0
    assert report.by_feature["x2"] == 2.0


def test_worker_does_not_create_model_library_record():
    import inspect
    source = inspect.getsource(execute_automl_job)
    assert "db.add(model_entry)" not in source
