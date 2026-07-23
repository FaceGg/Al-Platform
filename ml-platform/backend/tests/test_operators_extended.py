"""Extended Operator tests: IO, ML, DL, Visualization, and Evaluation operators."""
import sys, os, unittest, json, inspect
import pandas as pd
sys.path.insert(0, ".")

# Import via app.main to trigger operator registration
from app.main import app
from app.engine.registry import OperatorRegistry
from tests.operator_test_utils import execute_operator


class TestIOOperators(unittest.TestCase):
    """Test Input/Output operators."""

    def test_csv_import_exists(self):
        self.assertIsNotNone(OperatorRegistry.get("csv_import"))

    def test_csv_import_has_params(self):
        op = OperatorRegistry.get("csv_import")
        self.assertIsNotNone(op)
        self.assertGreaterEqual(len(op.parameters), 1)

    def test_csv_import_has_no_inputs(self):
        op = OperatorRegistry.get("csv_import")
        self.assertEqual(len(op.inputs), 0)

    def test_csv_import_has_outputs(self):
        op = OperatorRegistry.get("csv_import")
        self.assertGreater(len(op.outputs), 0)

    def test_duplicate_read_excel_operator_is_not_registered(self):
        self.assertIsNone(OperatorRegistry.get("read_excel"))


class TestProcessingOperators(unittest.TestCase):
    """Test Data Processing operators."""

    def test_scaler_exists(self):
        self.assertIsNotNone(OperatorRegistry.get("scaler"))

    def test_train_test_split_exists(self):
        self.assertIsNotNone(OperatorRegistry.get("train_test_split"))

    def test_label_encoder_exists(self):
        self.assertIsNotNone(OperatorRegistry.get("label_encoder"))

    def test_missing_value_handler_exists(self):
        self.assertIsNotNone(OperatorRegistry.get("missing_value_handler"))

    def test_auto_feature_engineering_exists(self):
        self.assertIsNotNone(OperatorRegistry.get("auto_feature_engineering"))

    def test_train_test_split_stratifies_fault_target(self):
        operator = OperatorRegistry.get("train_test_split")
        records = [
            {"feature": float(index), "Fault": 0 if index < 90 else 1}
            for index in range(100)
        ]

        outputs = execute_operator(operator, {"data": records}, {
            "test_size": 0.2, "random_seed": 42,
            "target_column": "Fault", "stratify": True,
        })

        self.assertEqual({row["Fault"] for row in outputs["train"]}, {0, 1})
        self.assertEqual({row["Fault"] for row in outputs["test"]}, {0, 1})
        self.assertEqual(sum(row["Fault"] for row in outputs["test"]), 2)

    def test_outlier_detection_can_exclude_fault_target(self):
        operator = OperatorRegistry.get("detect_outliers")
        parameter_names = {parameter.name for parameter in operator.parameters}
        self.assertIn("exclude_columns", parameter_names)
        records = [
            {"feature": value, "Fault": fault}
            for value, fault in [(0.0, 0), (0.1, 0), (0.2, 1), (9.0, 0)]
        ]

        outputs = execute_operator(operator, {"data": records}, {
            "method": "zscore", "contamination": 0.1, "exclude_columns": "Fault",
        })

        self.assertTrue(all("Fault" in row for row in outputs["data"]))
        self.assertTrue(all("outlier" in row for row in outputs["data"]))


class TestMLOperators(unittest.TestCase):
    """Test Machine Learning operators."""

    def test_xgboost_train_exists(self):
        self.assertIsNotNone(OperatorRegistry.get("xgboost_train"))

    def test_xgboost_classifier_does_not_use_removed_label_encoder_option(self):
        operator = OperatorRegistry.get("xgboost_train")
        self.assertNotIn("use_label_encoder", inspect.getsource(operator.execute))

    def test_random_forest_train_exists(self):
        self.assertIsNotNone(OperatorRegistry.get("random_forest_train"))

    def test_linear_model_train_exists(self):
        self.assertIsNotNone(OperatorRegistry.get("linear_model_train"))

    def test_classifiers_expose_imbalance_parameters(self):
        random_forest = {
            parameter.name for parameter in OperatorRegistry.get("random_forest_train").parameters
        }
        xgboost = {
            parameter.name for parameter in OperatorRegistry.get("xgboost_train").parameters
        }
        self.assertIn("class_weight", random_forest)
        self.assertIn("scale_pos_weight", xgboost)


class TestEvaluationOperators(unittest.TestCase):
    """Test Evaluation operators."""

    def test_classification_eval_exists(self):
        self.assertIsNotNone(OperatorRegistry.get("classification_eval"))

    def test_classification_eval_detailed_exists(self):
        self.assertIsNotNone(OperatorRegistry.get("classification_eval_detailed"))

    def test_regression_eval_exists(self):
        self.assertIsNotNone(OperatorRegistry.get("regression_eval"))

    def test_model_comparison_exists(self):
        self.assertIsNotNone(OperatorRegistry.get("model_comparison"))

    def test_anomaly_eval_reports_fault_class_metrics(self):
        operator = OperatorRegistry.get("anomaly_eval")
        self.assertIsNotNone(operator)
        records = [
            {"Fault": 0, "outlier": False},
            {"Fault": 0, "outlier": True},
            {"Fault": 1, "outlier": True},
            {"Fault": 1, "outlier": False},
        ]

        outputs = execute_operator(operator, {"data": records}, {
            "target_column": "Fault", "flag_column": "outlier",
        })

        self.assertEqual(outputs["metrics"]["anomaly_rate"], 0.5)
        self.assertEqual(outputs["metrics"]["fault_recall"], 0.5)
        self.assertEqual(outputs["metrics"]["confusion_matrix"], [[1, 1], [1, 1]])


class TestVisualizationOperators(unittest.TestCase):
    """Test Visualization operators."""

    def test_data_table_exists(self):
        self.assertIsNotNone(OperatorRegistry.get("data_table"))

    def test_data_stats_exists(self):
        self.assertIsNotNone(OperatorRegistry.get("data_stats"))

    def test_roc_curve_exists(self):
        self.assertIsNotNone(OperatorRegistry.get("roc_curve"))

    def test_feature_importance_exists(self):
        self.assertIsNotNone(OperatorRegistry.get("feature_importance"))

    def test_distribution_plot_exists(self):
        self.assertIsNotNone(OperatorRegistry.get("distribution_plot"))


class TestDLAndMechanismOperators(unittest.TestCase):
    """Test Deep Learning operators."""

    def test_dl_operators_category_exists(self):
        dl_ops = OperatorRegistry.list_by_category("dl")
        self.assertIsInstance(dl_ops, list)

    def test_mlp_classifier_exists(self):
        self.assertIsNotNone(OperatorRegistry.get("mlp_classifier"))

    def test_mlp_regressor_exists(self):
        self.assertIsNotNone(OperatorRegistry.get("mlp_regressor"))

    def test_cnn1d_classifier_exists(self):
        self.assertIsNotNone(OperatorRegistry.get("cnn1d_classifier"))


class TestControlOperators(unittest.TestCase):
    """Test Control flow operators."""

    def test_condition_operator(self):
        self.assertIsNotNone(OperatorRegistry.get("condition"))

    def test_merge_operator(self):
        self.assertIsNotNone(OperatorRegistry.get("merge"))

    def test_loop_operator(self):
        self.assertIsNotNone(OperatorRegistry.get("loop"))


class TestBlendingOperators(unittest.TestCase):
    def test_join_accepts_empty_dataframe_input(self):
        op = OperatorRegistry.get("join")
        left = pd.DataFrame()
        right = [{"id": 1}]

        result = execute_operator(op,
            {"left": left, "right": right},
            {"left_keys": "id", "right_keys": "id"},
        )

        self.assertEqual(result["data"], [{"id": 1}])
        pd.testing.assert_frame_equal(result["raw_left"], left)
        self.assertEqual(result["raw_right"], right)

    def test_join_matches_composite_keys_in_one_merge(self):
        op = OperatorRegistry.get("join")
        left = [
            {"plant": "A", "part": 1, "left_value": "match"},
            {"plant": "A", "part": 2, "left_value": "different-part"},
        ]
        right = [
            {"site": "A", "part_id": 1, "right_value": "joined"},
            {"site": "B", "part_id": 2, "right_value": "wrong-plant"},
        ]

        result = execute_operator(op,
            {"left": left, "right": right},
            {
                "join_type": "inner",
                "left_keys": "plant,part",
                "right_keys": "site,part_id",
            },
        )

        self.assertEqual(len(result["data"]), 1)
        self.assertEqual(result["data"][0]["left_value"], "match")
        self.assertEqual(result["data"][0]["right_value"], "joined")

    def test_join_rejects_unpaired_key_lists(self):
        op = OperatorRegistry.get("join")
        with self.assertRaisesRegex(ValueError, "count mismatch"):
            execute_operator(
                op,
                {
                    "left": [{"plant": "A", "part": 1}],
                    "right": [{"site": "A", "part_id": 1}],
                },
                {"left_keys": "plant", "right_keys": "site,part_id"},
            )


class TestOperatorCategories(unittest.TestCase):
    """Test operator categorization."""

    def test_all_categories_present(self):
        categories = set()
        for op in OperatorRegistry.list_all():
            categories.add(op.category)
        expected = {"data_io", "processing", "ml", "evaluation", "visualization", "control", "dl"}
        found = categories & expected
        self.assertGreaterEqual(len(found), 6)

    def test_total_operator_count(self):
        ops = OperatorRegistry.list_all()
        self.assertGreaterEqual(len(ops), 20)

    def test_each_operator_has_id_and_name(self):
        for op in OperatorRegistry.list_all():
            self.assertTrue(op.id.strip(), f"Operator has empty id")
            self.assertTrue(op.name.strip(), f"Operator {op.id} has empty name")


if __name__ == "__main__":
    unittest.main()
