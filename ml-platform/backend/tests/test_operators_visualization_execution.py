"""Execution tests for visualization operators.

Existing tests only verify these operators exist. Here we exercise their
execute() paths (chart generation, stats, preview helpers).
"""
import base64
import io
import sys
import unittest

import joblib
import pandas as pd
from sklearn.ensemble import RandomForestClassifier

sys.path.insert(0, ".")

from app.main import app  # noqa: F401
from app.engine.registry import OperatorRegistry
from tests.operator_test_utils import execute_operator


def _numeric_records():
    return [
        {"a": 1.0, "b": 10.0, "c": 100.0},
        {"a": 2.0, "b": 20.0, "c": 200.0},
        {"a": 3.0, "b": 30.0, "c": 300.0},
        {"a": 4.0, "b": 40.0, "c": 400.0},
    ]


def _trained_model_bytes():
    df = pd.DataFrame([
        {"f1": 0.0, "f2": 1.0, "target": 0},
        {"f1": 1.0, "f2": 0.0, "target": 1},
        {"f1": 0.5, "f2": 0.5, "target": 0},
        {"f1": 0.9, "f2": 0.1, "target": 1},
    ])
    model = RandomForestClassifier(n_estimators=5, random_state=0)
    model.fit(df[["f1", "f2"]], df["target"])
    buf = io.BytesIO()
    joblib.dump(model, buf)
    return buf.getvalue()


class TestDataTableOperator(unittest.TestCase):
    def test_execute_passes_data_through(self):
        op = OperatorRegistry.get("data_table")
        outputs = execute_operator(op, {"data": _numeric_records()}, {})
        self.assertEqual(outputs["view"], _numeric_records())

    def test_preview_truncates_to_ten_rows(self):
        op = OperatorRegistry.get("data_table")
        outputs = execute_operator(op, {"data": list(range(12))}, {})
        preview = op.get_preview(outputs)
        self.assertEqual(preview["total_rows"], 12)
        self.assertEqual(len(preview["data"]), 10)


class TestDataStatsOperator(unittest.TestCase):
    def test_execute_returns_stats_with_counts(self):
        op = OperatorRegistry.get("data_stats")
        outputs = execute_operator(op, {"data": _numeric_records()}, {})
        stats = outputs["stats"]
        self.assertEqual(stats["row_count"], 4)
        self.assertEqual(stats["column_count"], 3)
        self.assertEqual(set(stats["columns"]), {"a", "b", "c"})

    def test_execute_on_empty_data(self):
        op = OperatorRegistry.get("data_stats")
        outputs = execute_operator(op, {"data": []}, {})
        self.assertEqual(outputs["stats"]["row_count"], 0)
        self.assertEqual(outputs["stats"]["column_count"], 0)


class TestDistributionPlotOperator(unittest.TestCase):
    def test_execute_returns_base64_chart(self):
        op = OperatorRegistry.get("distribution_plot")
        outputs = execute_operator(op, {"data": _numeric_records()}, {"columns": ""})
        self.assertIsNotNone(outputs["chart"])
        # Ensure the chart decodes as base64.
        base64.b64decode(outputs["chart"])

    def test_execute_returns_error_when_no_numeric_columns(self):
        op = OperatorRegistry.get("distribution_plot")
        outputs = execute_operator(
            op, {"data": [{"name": "x"}, {"name": "y"}]}, {"columns": ""}
        )
        self.assertIsNone(outputs["chart"])
        self.assertIn("error", outputs)


class TestHistogramOperator(unittest.TestCase):
    def test_execute_returns_chart(self):
        op = OperatorRegistry.get("histogram")
        outputs = execute_operator(op, {"data": _numeric_records()}, {"column": "a", "bins": 4})
        self.assertIsNotNone(outputs["chart"])
        base64.b64decode(outputs["chart"])

    def test_execute_uses_first_numeric_when_column_invalid(self):
        op = OperatorRegistry.get("histogram")
        outputs = execute_operator(op, {"data": _numeric_records()}, {"column": "missing", "bins": 4})
        self.assertIsNotNone(outputs["chart"])


class TestScatterPlotOperator(unittest.TestCase):
    def test_execute_returns_chart(self):
        op = OperatorRegistry.get("scatter_plot")
        outputs = execute_operator(
            op, {"data": _numeric_records()},
            {"x_column": "a", "y_column": "b", "color_column": ""},
        )
        self.assertIsNotNone(outputs["chart"])
        base64.b64decode(outputs["chart"])

    def test_execute_defaults_columns_when_missing(self):
        op = OperatorRegistry.get("scatter_plot")
        outputs = execute_operator(op, {"data": _numeric_records()}, {})
        self.assertIsNotNone(outputs["chart"])


class TestLineChartOperator(unittest.TestCase):
    def test_execute_returns_chart(self):
        op = OperatorRegistry.get("line_chart")
        outputs = execute_operator(
            op, {"data": _numeric_records()},
            {"x_column": "a", "y_columns": "b,c"},
        )
        self.assertIsNotNone(outputs["chart"])
        base64.b64decode(outputs["chart"])


class TestBoxPlotOperator(unittest.TestCase):
    def test_execute_returns_chart(self):
        op = OperatorRegistry.get("box_plot")
        outputs = execute_operator(op, {"data": _numeric_records()}, {"columns": ""})
        self.assertIsNotNone(outputs["chart"])
        base64.b64decode(outputs["chart"])

    def test_execute_returns_error_when_no_numeric(self):
        op = OperatorRegistry.get("box_plot")
        outputs = execute_operator(op, {"data": [{"name": "x"}]}, {"columns": ""})
        self.assertIsNone(outputs["chart"])
        self.assertIn("error", outputs)


class TestBarChartOperator(unittest.TestCase):
    def test_execute_returns_chart(self):
        op = OperatorRegistry.get("bar_chart")
        outputs = execute_operator(
            op, {"data": [{"cat": "x", "val": 1.0}, {"cat": "y", "val": 2.0}]},
            {"x_column": "cat", "y_column": "val", "title": "T"},
        )
        self.assertIsNotNone(outputs["chart"])
        base64.b64decode(outputs["chart"])

    def test_execute_returns_error_when_x_missing(self):
        op = OperatorRegistry.get("bar_chart")
        outputs = execute_operator(
            op, {"data": [{"cat": "x", "val": 1.0}]},
            {"x_column": "missing", "y_column": "val", "title": "T"},
        )
        self.assertIsNone(outputs["chart"])
        self.assertIn("error", outputs)


class TestROCCurveOperator(unittest.TestCase):
    def test_execute_returns_chart(self):
        op = OperatorRegistry.get("roc_curve")
        test_data = [
            {"f1": 0.0, "f2": 1.0, "target": 0},
            {"f1": 1.0, "f2": 0.0, "target": 1},
            {"f1": 0.4, "f2": 0.6, "target": 0},
            {"f1": 0.9, "f2": 0.1, "target": 1},
        ]
        outputs = execute_operator(
            op,
            {"model": _trained_model_bytes(), "test": test_data},
            {"target_column": "target", "positive_class": ""},
        )
        self.assertIsNotNone(outputs["chart"])
        base64.b64decode(outputs["chart"])


class TestFeatureImportanceOperator(unittest.TestCase):
    def test_execute_returns_chart_for_tree_model(self):
        op = OperatorRegistry.get("feature_importance")
        train_data = [
            {"f1": 0.0, "f2": 1.0, "target": 0},
            {"f1": 1.0, "f2": 0.0, "target": 1},
            {"f1": 0.4, "f2": 0.6, "target": 0},
            {"f1": 0.9, "f2": 0.1, "target": 1},
        ]
        outputs = execute_operator(
            op,
            {"model": _trained_model_bytes(), "data": train_data},
            {"target_column": "target", "top_n": 2},
        )
        self.assertIsNotNone(outputs["chart"])
        base64.b64decode(outputs["chart"])


class TestConfusionMatrixPlotOperator(unittest.TestCase):
    def test_execute_with_explicit_matrix(self):
        op = OperatorRegistry.get("confusion_matrix_plot")
        metrics = {"confusion_matrix": [[5, 1], [2, 3]], "labels": ["0", "1"]}
        outputs = execute_operator(op, {"metrics": metrics}, {"title": "CM"})
        self.assertIsNotNone(outputs["chart"])
        base64.b64decode(outputs["chart"])

    def test_execute_returns_error_when_no_data(self):
        op = OperatorRegistry.get("confusion_matrix_plot")
        outputs = execute_operator(op, {"metrics": {}}, {"title": "CM"})
        self.assertIsNone(outputs["chart"])
        self.assertIn("error", outputs)

    def test_execute_builds_from_per_label(self):
        op = OperatorRegistry.get("confusion_matrix_plot")
        # The operator builds a 2x2 matrix from per_label[0] data and derives
        # labels from all per_label entries, so we need 2 entries to match the
        # 2x2 matrix dimensions for matplotlib tick labels.
        metrics = {
            "per_label": [
                {
                    "class": 0,
                    "true_positives": 4,
                    "false_positives": 1,
                    "false_negatives": 2,
                    "true_negatives": 3,
                },
                {
                    "class": 1,
                    "true_positives": 3,
                    "false_positives": 2,
                    "false_negatives": 1,
                    "true_negatives": 4,
                },
            ],
        }
        outputs = execute_operator(op, {"metrics": metrics}, {"title": "CM"})
        self.assertIsNotNone(outputs["chart"])


if __name__ == "__main__":
    unittest.main()
