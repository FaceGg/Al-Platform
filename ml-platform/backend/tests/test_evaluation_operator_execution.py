"""Registration, contract, and execution regressions for evaluation operators."""

from __future__ import annotations

import inspect
import io
import sys
import unittest

import joblib
import pandas as pd
from sklearn.linear_model import LinearRegression, LogisticRegression

sys.path.insert(0, ".")

from app.engine.operator_contract import validate_operator_result
from app.engine.registry import OperatorRegistry
from app.main import app  # noqa: F401 - imports all built-in operators
from tests.operator_test_utils import operator_context


EXPECTED_EVALUATION_OPERATORS = {
    "anomaly_eval": {
        "inputs": ["data"],
        "outputs": ["metrics"],
        "params": ["target_column", "flag_column"],
    },
    "classification_eval_detailed": {
        "inputs": ["model", "test"],
        "outputs": ["metrics", "per_label", "chart", "errors"],
        "params": ["target_column", "threshold"],
    },
    "model_comparison": {
        "inputs": ["model_a", "model_b", "test"],
        "outputs": ["comparison"],
        "params": ["target_column", "metric"],
    },
    "classification_eval": {
        "inputs": ["model", "test"],
        "outputs": ["metrics", "chart"],
        "params": ["target_column"],
    },
    "regression_eval": {
        "inputs": ["model", "test"],
        "outputs": ["metrics"],
        "params": ["target_column"],
    },
    "cross_validation": {
        "inputs": ["data"],
        "outputs": ["fold_metrics", "avg_metrics"],
        "params": [
            "target_column",
            "model_type",
            "task",
            "n_folds",
            "stratified",
            "random_seed",
        ],
    },
}


def _model_bytes(model) -> bytes:
    payload = io.BytesIO()
    joblib.dump(model, payload)
    return payload.getvalue()


class TestEvaluationOperatorRegistration(unittest.TestCase):
    def test_all_evaluation_operators_are_registered_once_with_contract_metadata(self):
        operators = OperatorRegistry.list_by_category("evaluation")
        operator_ids = [operator.id for operator in operators]

        self.assertEqual(set(operator_ids), set(EXPECTED_EVALUATION_OPERATORS))
        self.assertEqual(len(operator_ids), len(set(operator_ids)))

        for operator in operators:
            with self.subTest(operator=operator.id):
                expected = EXPECTED_EVALUATION_OPERATORS[operator.id]
                self.assertEqual([port.name for port in operator.inputs], expected["inputs"])
                self.assertEqual([port.name for port in operator.outputs], expected["outputs"])
                self.assertEqual([param.name for param in operator.parameters], expected["params"])
                self.assertEqual(
                    list(inspect.signature(operator.execute).parameters),
                    ["context", "inputs", "params"],
                )


class TestEvaluationOperatorExecution(unittest.TestCase):
    def setUp(self):
        self.classification_data = [
            {"feature": float(index), "target": 0 if index < 6 else 1}
            for index in range(12)
        ]
        self.regression_data = [
            {"feature": float(index), "target": float(1.25 * index + 0.5)}
            for index in range(12)
        ]
        classifier = LogisticRegression(max_iter=1000).fit(
            pd.DataFrame({"feature": [row["feature"] for row in self.classification_data]}),
            [row["target"] for row in self.classification_data],
        )
        regressor = LinearRegression().fit(
            pd.DataFrame({"feature": [row["feature"] for row in self.regression_data]}),
            [row["target"] for row in self.regression_data],
        )
        self.classifier_bytes = _model_bytes(classifier)
        self.regressor_bytes = _model_bytes(regressor)

    def _execute(self, operator_id, inputs, params):
        operator = OperatorRegistry.get(operator_id)
        self.assertIsNotNone(operator)
        result = operator.execute(operator_context(), inputs, params)
        validate_operator_result(operator.outputs, result)
        return result.outputs

    def test_anomaly_eval_executes(self):
        outputs = self._execute(
            "anomaly_eval",
            {
                "data": [
                    {"Fault": 0, "outlier": False},
                    {"Fault": 0, "outlier": True},
                    {"Fault": 1, "outlier": True},
                    {"Fault": 1, "outlier": False},
                ]
            },
            {"target_column": "Fault", "flag_column": "outlier"},
        )
        self.assertEqual(outputs["metrics"]["fault_recall"], 0.5)

    def test_classification_evaluators_execute(self):
        inputs = {
            "model": self.classifier_bytes,
            "test": self.classification_data,
        }
        detailed = self._execute(
            "classification_eval_detailed", inputs, {"target_column": "target"}
        )
        self.assertGreater(len(detailed["chart"]), 100)
        self.assertIn("f1_macro", detailed["metrics"])

        basic = self._execute(
            "classification_eval", inputs, {"target_column": "target"}
        )
        self.assertIn("accuracy", basic["metrics"])
        self.assertGreater(len(basic["chart"]), 100)

    def test_model_comparison_executes(self):
        outputs = self._execute(
            "model_comparison",
            {
                "model_a": self.classifier_bytes,
                "model_b": self.classifier_bytes,
                "test": self.classification_data,
            },
            {"target_column": "target", "metric": "f1"},
        )
        self.assertEqual(outputs["comparison"]["winner"], "A")

    def test_regression_eval_executes(self):
        outputs = self._execute(
            "regression_eval",
            {"model": self.regressor_bytes, "test": self.regression_data},
            {"target_column": "target"},
        )
        self.assertAlmostEqual(outputs["metrics"]["rmse"], 0.0, places=6)

    def test_cross_validation_executes_with_model_specific_classifiers_and_regressors(self):
        for model_type in ("random_forest", "decision_tree", "logistic_regression", "svm"):
            with self.subTest(task="classification", model_type=model_type):
                outputs = self._execute(
                    "cross_validation",
                    {"data": self.classification_data},
                    {
                        "target_column": "target",
                        "model_type": model_type,
                        "task": "classification",
                        "n_folds": 2,
                        "random_seed": 42,
                    },
                )
                self.assertEqual(len(outputs["fold_metrics"]), 2)
                self.assertIn("accuracy", outputs["avg_metrics"])

            with self.subTest(task="regression", model_type=model_type):
                outputs = self._execute(
                    "cross_validation",
                    {"data": self.regression_data},
                    {
                        "target_column": "target",
                        "model_type": model_type,
                        "task": "regression",
                        "n_folds": 2,
                        "stratified": False,
                        "random_seed": 42,
                    },
                )
                self.assertEqual(len(outputs["fold_metrics"]), 2)
                self.assertIn("rmse", outputs["avg_metrics"])


if __name__ == "__main__":
    unittest.main()
