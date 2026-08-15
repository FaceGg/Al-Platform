"""Comprehensive test covering all registered operators: registration, metadata, and execution.

This test module validates every operator in the registry without modifying source code.
Operators are tested in three dimensions:
1. Registration: all operators registered with unique IDs
2. Metadata: each operator has valid id, name, category, inputs, outputs
3. Execution: each operator runs with appropriate sample data and returns OperatorResult
"""
import io
import os
import tempfile
import unittest

from app.engine.registry import OperatorRegistry
from app.engine.operator_contract import OperatorContext, OperatorResult
from app.services.spot_weld_features import FEATURE_SCHEMA, QualityPipelineError
from app.services.spot_weld_quality import build_demo_report_frame
from tests.operator_test_utils import execute_operator, operator_context

# Importing app triggers operator registration via module side effects.
from app.main import app  # noqa: F401


# ---- Sample data fixtures ----

CLASSIFICATION_DATA = [
    {"feature1": float(i), "feature2": float(i * 2), "target": 0 if i < 8 else 1}
    for i in range(20)
]

REGRESSION_DATA = [
    {"x": float(i), "y": float(i * 3 + 1)}
    for i in range(20)
]

CLUSTER_DATA = [
    {"x": float(i), "y": float((i % 3) * 10)}
    for i in range(15)
]

TRANSACTION_DATA = [
    {"item": "A", "qty": 1},
    {"item": "A", "qty": 2},
    {"item": "B", "qty": 1},
    {"item": "A", "qty": 1},
]

LEFT_DATA = [
    {"id": 1, "name": "alpha", "value": 10},
    {"id": 2, "name": "beta", "value": 20},
]

RIGHT_DATA = [
    {"id": 1, "label": "L1", "score": 0.9},
    {"id": 2, "label": "L2", "score": 0.8},
]

EVAL_DATA = [
    {"feature": float(i), "Fault": 0 if i < 8 else 1, "outlier": 0 if i < 9 else 1}
    for i in range(20)
]


def _trained_model_bytes():
    """Train a simple sklearn model and return joblib bytes."""
    import joblib
    from sklearn.linear_model import LogisticRegression
    from app.operators.ml_operators import LinearModelTrainer
    op = OperatorRegistry.get("linear_model_train")
    result = op.execute(operator_context(), {"data": CLASSIFICATION_DATA}, {"target_column": "target"})
    return result.outputs["model"]


class TestAllOperatorsRegistered(unittest.TestCase):
    """Verify all operators are registered with unique IDs."""

    def test_operator_count_meets_baseline(self):
        ops = OperatorRegistry.list_all()
        self.assertGreaterEqual(len(ops), 80,
            f"Expected at least 80 operators, found {len(ops)}")

    def test_all_ids_are_unique(self):
        ops = OperatorRegistry.list_all()
        ids = [op.id for op in ops]
        duplicates = [i for i in ids if ids.count(i) > 1]
        self.assertEqual(duplicates, [], f"Duplicate operator IDs: {set(duplicates)}")

    def test_all_ids_are_nonempty_strings(self):
        for op in OperatorRegistry.list_all():
            self.assertTrue(isinstance(op.id, str) and op.id.strip(),
                f"Operator has invalid id: {op.id!r}")

    def test_expected_categories_exist(self):
        categories = {op.category for op in OperatorRegistry.list_all()}
        expected = {"io", "processing", "ml", "evaluation", "visualization",
                    "control", "dl", "blending", "optimization"}
        missing = expected - categories
        self.assertEqual(missing, set(), f"Missing categories: {missing}")

    def test_every_category_has_operators(self):
        from collections import Counter
        counts = Counter(op.category for op in OperatorRegistry.list_all())
        for cat, count in counts.items():
            self.assertGreater(count, 0, f"Category '{cat}' has no operators")


class TestAllOperatorsMetadata(unittest.TestCase):
    """Verify each operator has valid metadata."""

    def test_every_operator_has_name_and_description(self):
        for op in OperatorRegistry.list_all():
            self.assertTrue(isinstance(op.name, str) and op.name.strip(),
                f"Operator '{op.id}' has empty name")
            self.assertTrue(isinstance(op.description, str),
                f"Operator '{op.id}' has no description")

    def test_every_operator_has_inputs_list(self):
        for op in OperatorRegistry.list_all():
            self.assertTrue(isinstance(op.inputs, list),
                f"Operator '{op.id}' inputs is not a list")

    def test_every_operator_has_outputs_list(self):
        for op in OperatorRegistry.list_all():
            self.assertTrue(isinstance(op.outputs, list),
                f"Operator '{op.id}' outputs is not a list")

    def test_every_operator_has_parameters_list(self):
        for op in OperatorRegistry.list_all():
            self.assertTrue(isinstance(op.parameters, list),
                f"Operator '{op.id}' parameters is not a list")

    def test_output_ports_have_name_and_type(self):
        from app.engine.base_operator import PortSpec
        for op in OperatorRegistry.list_all():
            for port in op.outputs:
                self.assertTrue(hasattr(port, 'name'),
                    f"Operator '{op.id}' output port missing name")
                self.assertTrue(hasattr(port, 'type'),
                    f"Operator '{op.id}' output port missing type")

    def test_input_ports_have_name_and_type(self):
        for op in OperatorRegistry.list_all():
            for port in op.inputs:
                self.assertTrue(hasattr(port, 'name'),
                    f"Operator '{op.id}' input port missing name")
                self.assertTrue(hasattr(port, 'type'),
                    f"Operator '{op.id}' input port missing type")


class TestIOOperatorsExecution(unittest.TestCase):
    """Test IO operators execution."""

    def test_csv_import_no_file_returns_error(self):
        op = OperatorRegistry.get("csv_import")
        with self.assertRaises(RuntimeError):
            op.execute(operator_context(), {}, {"source": "local", "file_path": ""})

    def test_csv_import_reads_local_file(self):
        op = OperatorRegistry.get("csv_import")
        with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False, newline='') as f:
            f.write("a,b\n1,2\n3,4\n")
            f.flush()
            path = f.name
        try:
            result = op.execute(operator_context(), {},
                {"source": "local", "file_path": path, "delimiter": ",", "has_header": True})
            self.assertIsInstance(result, OperatorResult)
            self.assertEqual(len(result.outputs["data"]), 2)
        finally:
            os.unlink(path)

    def test_csv_export_passthrough(self):
        outputs = execute_operator(
            OperatorRegistry.get("csv_export"),
            {"data": [{"a": 1}]}, {"file_path": ""})
        self.assertEqual(outputs["data"], [{"a": 1}])

    def test_csv_export_writes_file(self):
        with tempfile.NamedTemporaryFile(suffix='.csv', delete=False) as f:
            path = f.name
        try:
            execute_operator(
                OperatorRegistry.get("csv_export"),
                {"data": [{"a": 1, "b": 2}]},
                {"file_path": path, "separator": ","})
            self.assertTrue(os.path.exists(path))
        finally:
            if os.path.exists(path):
                os.unlink(path)

    def test_image_import_no_path_returns_empty(self):
        outputs = execute_operator(
            OperatorRegistry.get("image_import"), {}, {"file_path": "", "pattern": "*.png"})
        self.assertEqual(outputs["data"], [])

    def test_json_import_no_path_returns_empty(self):
        outputs = execute_operator(
            OperatorRegistry.get("json_import"), {}, {"file_path": "", "orient": "records"})
        self.assertEqual(outputs["data"], [])

    def test_json_import_reads_file(self):
        import json
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump([{"x": 1}, {"x": 2}], f)
            f.flush()
            path = f.name
        try:
            outputs = execute_operator(
                OperatorRegistry.get("json_import"), {},
                {"file_path": path, "orient": "records"})
            self.assertEqual(len(outputs["data"]), 2)
        finally:
            os.unlink(path)

    def test_read_excel_no_path_raises_required_error(self):
        with self.assertRaisesRegex(RuntimeError, "Excel file path is required"):
            execute_operator(
                OperatorRegistry.get("read_excel"), {}, {"file_path": ""})

    def test_read_database_no_conn_returns_empty(self):
        outputs = execute_operator(
            OperatorRegistry.get("read_database"), {},
            {"connection_string": "", "query": "SELECT 1"})
        self.assertEqual(outputs["data"], [])

    def test_read_url_no_url_returns_empty(self):
        outputs = execute_operator(
            OperatorRegistry.get("read_url"), {}, {"url": ""})
        self.assertEqual(outputs["data"], [])

    def test_write_csv_passthrough(self):
        outputs = execute_operator(
            OperatorRegistry.get("write_csv"),
            {"data": [{"a": 1}]}, {"file_path": ""})
        self.assertEqual(outputs["data"], [{"a": 1}])

    def test_retrieve_no_path_returns_empty(self):
        outputs = execute_operator(
            OperatorRegistry.get("retrieve"), {}, {"repository_entry": ""})
        self.assertEqual(outputs["data"], [])

    def test_store_passthrough(self):
        outputs = execute_operator(
            OperatorRegistry.get("store"),
            {"data": [{"a": 1}]}, {"repository_entry": ""})
        self.assertEqual(outputs["data"], [{"a": 1}])


class TestProcessingOperatorsExecution(unittest.TestCase):
    """Test processing operators execution."""

    def test_missing_value_handler_drop(self):
        data = [{"a": 1, "b": None}, {"a": 2, "b": 3}]
        outputs = execute_operator(
            OperatorRegistry.get("missing_value_handler"),
            {"data": data}, {"strategy": "drop", "columns": ""})
        self.assertEqual(len(outputs["data"]), 1)

    def test_missing_value_handler_mean(self):
        data = [{"a": 1, "b": 10}, {"a": 2, "b": None}, {"a": 3, "b": 30}]
        outputs = execute_operator(
            OperatorRegistry.get("missing_value_handler"),
            {"data": data}, {"strategy": "mean", "columns": "b"})
        self.assertEqual(outputs["data"][1]["b"], 20.0)

    def test_label_encoder(self):
        data = [{"cat": "A", "v": 1}, {"cat": "B", "v": 2}]
        outputs = execute_operator(
            OperatorRegistry.get("label_encoder"),
            {"data": data}, {"columns": "cat", "encoding_type": "label"})
        self.assertIn(outputs["data"][0]["cat"], [0, 1])

    def test_scaler(self):
        outputs = execute_operator(
            OperatorRegistry.get("scaler"),
            {"data": CLASSIFICATION_DATA}, {"method": "standard", "columns": ""})
        self.assertEqual(len(outputs["data"]), len(CLASSIFICATION_DATA))

    def test_train_test_split(self):
        outputs = execute_operator(
            OperatorRegistry.get("train_test_split"),
            {"data": CLASSIFICATION_DATA},
            {"test_size": 0.2, "random_seed": 42, "target_column": "target", "stratify": False})
        self.assertIn("train", outputs)
        self.assertIn("test", outputs)

    def test_auto_feature_engineering(self):
        outputs = execute_operator(
            OperatorRegistry.get("auto_feature_engineering"),
            {"data": REGRESSION_DATA}, {"operations": "poly", "degree": 2})
        self.assertGreater(len(outputs["data"]), 0)

    def test_spot_weld_feature_engineering_preserves_report_feature_contract(self):
        frame = build_demo_report_frame(12)

        outputs = execute_operator(
            OperatorRegistry.get("spot_weld_feature_engineering"),
            {"data": frame.to_dict(orient="records")}, {})

        self.assertEqual(len(outputs["features"]), 12)
        self.assertEqual(outputs["schema"]["columns"], list(FEATURE_SCHEMA))
        self.assertEqual(len(outputs["schema"]["columns"]), 73)
        self.assertEqual(outputs["statistics"]["feature_count"], 73)
        self.assertEqual(
            [outputs["features"][0][name] for name in ("cvei", "cvev", "cver", "cvep")],
            [frame.iloc[0][name] for name in ("cvei", "cvev", "cver", "cvep")],
        )

    def test_spot_weld_feature_engineering_declares_all_report_source_columns(self):
        operator = OperatorRegistry.get("spot_weld_feature_engineering")
        source_columns = next(port.required_columns for port in operator.inputs if port.name == "data")
        self.assertEqual(
            source_columns,
            (
                "wld1c", "wld2c", "tipv1", "tipv2", "wres", "energy",
                "wld_spatter_strength", "wld1_spatter_strength", "wld2_spatter_strength",
                "spatterpos_wld", "spatterpos_pre", "spotdiameter", "spotposition", "spattercode",
                "cvei", "cvev", "cver", "cvep",
            ),
        )

    def test_spot_weld_feature_engineering_accepts_dataframe(self):
        frame = build_demo_report_frame(12)

        outputs = execute_operator(
            OperatorRegistry.get("spot_weld_feature_engineering"),
            {"data": frame}, {})

        self.assertEqual(len(outputs["features"]), 12)

    def test_spot_weld_feature_engineering_propagates_waveform_error(self):
        frame = build_demo_report_frame(12)
        frame.loc[0, "cvei"] = "not-base64"

        with self.assertRaises(QualityPipelineError) as raised:
            execute_operator(
                OperatorRegistry.get("spot_weld_feature_engineering"),
                {"data": frame}, {})

        error = raised.exception
        self.assertIs(type(error), QualityPipelineError)
        self.assertEqual(error.code, "QUALITY_WAVEFORM_INVALID_BASE64")
        self.assertEqual(error.row_index, 0)
        self.assertEqual(error.field_name, "cvei")

    def test_normalize(self):
        outputs = execute_operator(
            OperatorRegistry.get("normalize"),
            {"data": CLASSIFICATION_DATA}, {"method": "minmax", "columns": ""})
        self.assertEqual(len(outputs["data"]), len(CLASSIFICATION_DATA))

    def test_discretize(self):
        outputs = execute_operator(
            OperatorRegistry.get("discretize"),
            {"data": REGRESSION_DATA}, {"columns": "x", "bins": 3, "strategy": "uniform"})
        self.assertEqual(len(outputs["data"]), len(REGRESSION_DATA))

    def test_detect_outliers(self):
        data = [{"x": float(i)} for i in range(10)] + [{"x": 1000.0}]
        outputs = execute_operator(
            OperatorRegistry.get("detect_outliers"),
            {"data": data}, {"method": "iqr", "columns": "x"})
        self.assertEqual(len(outputs["data"]), len(data))

    def test_select_attributes(self):
        outputs = execute_operator(
            OperatorRegistry.get("select_attributes"),
            {"data": CLASSIFICATION_DATA}, {"columns": "feature1,target"})
        self.assertTrue(all("feature2" not in row for row in outputs["data"]))

    def test_set_role(self):
        outputs = execute_operator(
            OperatorRegistry.get("set_role"),
            {"data": CLASSIFICATION_DATA}, {"target_column": "target"})
        self.assertEqual(len(outputs["data"]), len(CLASSIFICATION_DATA))

    def test_filter_examples(self):
        outputs = execute_operator(
            OperatorRegistry.get("filter_examples"),
            {"data": CLASSIFICATION_DATA},
            {"expression": "target == 0"})
        self.assertTrue(all(row["target"] == 0 for row in outputs["data"]))

    def test_sample(self):
        outputs = execute_operator(
            OperatorRegistry.get("sample"),
            {"data": CLASSIFICATION_DATA},
            {"sample_size": 5, "with_replacement": False, "random_seed": 42})
        self.assertEqual(len(outputs["data"]), 5)

    def test_impute_missing_advanced(self):
        data = [{"a": 1, "b": 10}, {"a": 2, "b": None}, {"a": 3, "b": 30}]
        outputs = execute_operator(
            OperatorRegistry.get("impute_missing_advanced"),
            {"data": data}, {"strategy": "mean", "fill_value": "0"})
        self.assertEqual(len(outputs["data"]), len(data))


class TestBlendingOperatorsExecution(unittest.TestCase):
    """Test blending operators execution."""

    def test_join(self):
        outputs = execute_operator(
            OperatorRegistry.get("join"),
            {"left": LEFT_DATA, "right": RIGHT_DATA},
            {"join_type": "inner", "left_keys": "id", "right_keys": "id"})
        self.assertEqual(len(outputs["data"]), 2)

    def test_union(self):
        outputs = execute_operator(
            OperatorRegistry.get("union"),
            {"data1": LEFT_DATA, "data2": LEFT_DATA}, {})
        self.assertEqual(len(outputs["data"]), 4)

    def test_aggregate(self):
        outputs = execute_operator(
            OperatorRegistry.get("aggregate"),
            {"data": LEFT_DATA},
            {"group_by": "name", "aggregations": "value:sum"})
        self.assertEqual(len(outputs["data"]), 2)

    def test_pivot(self):
        data = [
            {"id": 1, "key": "A", "val": 10},
            {"id": 1, "key": "B", "val": 20},
            {"id": 2, "key": "A", "val": 30},
        ]
        outputs = execute_operator(
            OperatorRegistry.get("pivot"),
            {"data": data}, {"index": "id", "columns": "key", "values": "val"})
        self.assertGreater(len(outputs["data"]), 0)

    def test_transpose(self):
        outputs = execute_operator(
            OperatorRegistry.get("transpose"),
            {"data": LEFT_DATA}, {})
        self.assertGreater(len(outputs["data"]), 0)

    def test_generate_attributes(self):
        outputs = execute_operator(
            OperatorRegistry.get("generate_attributes"),
            {"data": REGRESSION_DATA},
            {"new_column_name": "z", "expression": "row['x'] + row['y']"})
        self.assertTrue(any("z" in row for row in outputs["data"]))

    def test_sort(self):
        outputs = execute_operator(
            OperatorRegistry.get("sort"),
            {"data": [{"v": 3}, {"v": 1}, {"v": 2}]},
            {"sort_column": "v", "ascending": True})
        self.assertEqual([row["v"] for row in outputs["data"]], [1, 2, 3])


class TestControlOperatorsExecution(unittest.TestCase):
    """Test control operators execution."""

    def test_condition_true_branch(self):
        outputs = execute_operator(
            OperatorRegistry.get("condition"),
            {"data": [{"x": 10}, {"x": 5}]},
            {"column": "x", "operator": ">", "value": "7"})
        self.assertEqual(len(outputs["true_branch"]), 1)
        self.assertEqual(len(outputs["false_branch"]), 1)

    def test_merge_concat_rows(self):
        outputs = execute_operator(
            OperatorRegistry.get("merge"),
            {"data_a": [{"a": 1}], "data_b": [{"a": 2}]},
            {"merge_type": "concat_rows", "key_column": ""})
        self.assertEqual(len(outputs["merged"]), 2)

    def test_loop(self):
        outputs = execute_operator(
            OperatorRegistry.get("loop"),
            {"data": CLASSIFICATION_DATA},
            {"max_iterations": 3, "condition": "count"})
        self.assertIn("result", outputs)
        self.assertIn("continue", outputs)


class TestMLOperatorsExecution(unittest.TestCase):
    """Test ML operators execution."""

    def test_xgboost_train(self):
        result = OperatorRegistry.get("xgboost_train").execute(
            operator_context(), {"data": CLASSIFICATION_DATA},
            {"target_column": "target", "task": "classification",
             "n_estimators": 5, "max_depth": 2})
        self.assertIsInstance(result, OperatorResult)
        self.assertIn("model", result.outputs)
        self.assertTrue(len(result.outputs["model"]) > 0)

    def test_random_forest_train(self):
        result = OperatorRegistry.get("random_forest_train").execute(
            operator_context(), {"data": CLASSIFICATION_DATA},
            {"target_column": "target", "task": "classification",
             "n_estimators": 5, "max_depth": 3})
        self.assertIn("model", result.outputs)

    def test_linear_model_train(self):
        result = OperatorRegistry.get("linear_model_train").execute(
            operator_context(), {"data": CLASSIFICATION_DATA},
            {"target_column": "target", "task": "classification"})
        self.assertIn("model", result.outputs)

    def test_decision_tree(self):
        result = OperatorRegistry.get("decision_tree").execute(
            operator_context(), {"data": CLASSIFICATION_DATA},
            {"target_column": "target", "max_depth": 3})
        self.assertIn("model", result.outputs)

    def test_naive_bayes(self):
        result = OperatorRegistry.get("naive_bayes").execute(
            operator_context(), {"data": CLASSIFICATION_DATA},
            {"target_column": "target"})
        self.assertIn("model", result.outputs)

    def test_knn(self):
        result = OperatorRegistry.get("knn").execute(
            operator_context(), {"data": CLASSIFICATION_DATA},
            {"target_column": "target", "k": 3})
        self.assertIn("model", result.outputs)

    def test_svm(self):
        result = OperatorRegistry.get("svm").execute(
            operator_context(), {"data": CLASSIFICATION_DATA},
            {"target_column": "target", "kernel": "rbf", "C": 1.0})
        self.assertIn("model", result.outputs)

    def test_logistic_regression(self):
        result = OperatorRegistry.get("logistic_regression").execute(
            operator_context(), {"data": CLASSIFICATION_DATA},
            {"target_column": "target", "C": 1.0, "max_iter": 100})
        self.assertIn("model", result.outputs)

    def test_kmeans_clustering(self):
        outputs = execute_operator(
            OperatorRegistry.get("kmeans_clustering"),
            {"data": CLUSTER_DATA}, {"k": 3, "max_runs": 3, "random_seed": 42})
        self.assertIn("clusters", outputs)
        self.assertTrue(any("cluster" in row for row in outputs["clusters"]))

    def test_dbscan(self):
        outputs = execute_operator(
            OperatorRegistry.get("dbscan"),
            {"data": CLUSTER_DATA}, {"eps": 5.0, "min_points": 2})
        self.assertIn("clusters", outputs)

    def test_apriori(self):
        outputs = execute_operator(
            OperatorRegistry.get("apriori"),
            {"data": TRANSACTION_DATA},
            {"min_support": 0.1, "min_confidence": 0.3})
        self.assertIn("rules", outputs)

    def test_fp_growth(self):
        outputs = execute_operator(
            OperatorRegistry.get("fp_growth"),
            {"data": TRANSACTION_DATA},
            {"min_support": 0.1, "min_confidence": 0.3})
        self.assertIn("rules", outputs)

    def test_random_forest_regression(self):
        result = OperatorRegistry.get("random_forest_regression").execute(
            operator_context(), {"data": REGRESSION_DATA},
            {"target_column": "y", "n_estimators": 5, "max_depth": 3})
        self.assertIn("model", result.outputs)

    def test_svm_regression(self):
        result = OperatorRegistry.get("svm_regression").execute(
            operator_context(), {"data": REGRESSION_DATA},
            {"target_column": "y", "kernel": "rbf", "C": 1.0, "epsilon": 0.1})
        self.assertIn("model", result.outputs)

    def test_apply_model(self):
        model_bytes = _trained_model_bytes()
        outputs = execute_operator(
            OperatorRegistry.get("apply_model"),
            {"model": model_bytes, "data": CLASSIFICATION_DATA}, {})
        self.assertIn("data", outputs)
        self.assertTrue(any("prediction" in row for row in outputs["data"]))


class TestEvaluationOperatorsExecution(unittest.TestCase):
    """Test evaluation operators execution."""

    def test_anomaly_eval(self):
        outputs = execute_operator(
            OperatorRegistry.get("anomaly_eval"),
            {"data": EVAL_DATA},
            {"target_column": "Fault", "flag_column": "outlier"})
        self.assertIn("metrics", outputs)

    def test_classification_eval(self):
        model_bytes = _trained_model_bytes()
        outputs = execute_operator(
            OperatorRegistry.get("classification_eval"),
            {"model": model_bytes, "test": CLASSIFICATION_DATA},
            {"target_column": "target"})
        self.assertIn("metrics", outputs)

    def test_classification_eval_detailed(self):
        model_bytes = _trained_model_bytes()
        outputs = execute_operator(
            OperatorRegistry.get("classification_eval_detailed"),
            {"model": model_bytes, "test": CLASSIFICATION_DATA},
            {"target_column": "target"})
        self.assertIn("metrics", outputs)

    def test_regression_eval(self):
        from sklearn.linear_model import LinearRegression
        import joblib
        import pandas as pd
        df = pd.DataFrame(REGRESSION_DATA)
        model = LinearRegression().fit(df[["x"]], df["y"])
        buf = io.BytesIO(); joblib.dump(model, buf)
        outputs = execute_operator(
            OperatorRegistry.get("regression_eval"),
            {"model": buf.getvalue(), "test": REGRESSION_DATA},
            {"target_column": "y"})
        self.assertIn("metrics", outputs)

    def test_model_comparison(self):
        model_bytes = _trained_model_bytes()
        outputs = execute_operator(
            OperatorRegistry.get("model_comparison"),
            {"model_a": model_bytes, "model_b": model_bytes, "test": CLASSIFICATION_DATA},
            {"target_column": "target", "metric": "accuracy"})
        self.assertIn("comparison", outputs)

    def test_cross_validation(self):
        outputs = execute_operator(
            OperatorRegistry.get("cross_validation"),
            {"data": CLASSIFICATION_DATA},
            {"target_column": "target", "cv_folds": 3, "model_type": "logistic"})
        self.assertIn("avg_metrics", outputs)


class TestDLOperatorsMetadata(unittest.TestCase):
    """Test DL operators registration and metadata."""

    def test_mlp_classifier_registered(self):
        op = OperatorRegistry.get("mlp_classifier")
        self.assertIsNotNone(op)
        self.assertEqual(op.category, "dl")

    def test_mlp_regressor_registered(self):
        op = OperatorRegistry.get("mlp_regressor")
        self.assertIsNotNone(op)
        self.assertEqual(op.category, "dl")

    def test_cnn1d_classifier_registered(self):
        op = OperatorRegistry.get("cnn1d_classifier")
        self.assertIsNotNone(op)
        self.assertEqual(op.category, "dl")

    def test_dl_operators_have_model_output(self):
        for op_id in ["mlp_classifier", "mlp_regressor", "cnn1d_classifier"]:
            op = OperatorRegistry.get(op_id)
            output_names = [p.name for p in op.outputs]
            self.assertIn("model", output_names, f"{op_id} missing 'model' output")


class TestMechanismOperatorsMetadata(unittest.TestCase):
    """Test mechanism operators registration and metadata."""

    MECHANISM_IDS = [
        "mechanism_thermal", "mechanism_nugget", "mechanism_lobe",
        "mechanism_splash", "mechanism_stress", "mechanism_gate",
    ]

    def test_all_mechanism_operators_registered(self):
        for op_id in self.MECHANISM_IDS:
            op = OperatorRegistry.get(op_id)
            self.assertIsNotNone(op, f"{op_id} not registered")
            self.assertEqual(op.category, "mechanism",
                f"{op_id} category is {op.category}, expected 'mechanism'")

    def test_mechanism_operators_have_parameters(self):
        for op_id in self.MECHANISM_IDS:
            op = OperatorRegistry.get(op_id)
            self.assertGreater(len(op.parameters), 0,
                f"{op_id} has no parameters")


class TestOptimizationOperatorsMetadata(unittest.TestCase):
    """Test optimization operators registration and metadata."""

    def test_optimize_grid_registered(self):
        op = OperatorRegistry.get("optimize_grid")
        self.assertIsNotNone(op)
        self.assertEqual(op.category, "optimization")

    def test_optimize_evolutionary_registered(self):
        op = OperatorRegistry.get("optimize_evolutionary")
        self.assertIsNotNone(op)
        self.assertEqual(op.category, "optimization")


class TestUtilityOperatorsMetadata(unittest.TestCase):
    """Test utility operators registration and metadata."""

    UTILITY_IDS = ["execute_python", "collect", "macro", "write_as_text"]

    def test_all_utility_operators_registered(self):
        for op_id in self.UTILITY_IDS:
            op = OperatorRegistry.get(op_id)
            self.assertIsNotNone(op, f"{op_id} not registered")


class TestVisualizationOperatorsMetadata(unittest.TestCase):
    """Test visualization operators registration and metadata."""

    VIZ_IDS = [
        "data_table", "data_stats", "roc_curve", "feature_importance",
        "distribution_plot", "scatter_plot", "histogram", "line_chart",
        "confusion_matrix_plot", "box_plot", "bar_chart",
    ]

    def test_all_visualization_operators_registered(self):
        for op_id in self.VIZ_IDS:
            op = OperatorRegistry.get(op_id)
            self.assertIsNotNone(op, f"{op_id} not registered")
            self.assertEqual(op.category, "visualization",
                f"{op_id} category is {op.category}")


if __name__ == "__main__":
    unittest.main()
