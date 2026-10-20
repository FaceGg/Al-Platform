"""Registration, contract, and execution regressions for evaluation operators."""

from __future__ import annotations

import inspect
import io
import sys
import unittest

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LinearRegression, LogisticRegression

sys.path.insert(0, ".")

from app.engine.operator_contract import OperatorContext, validate_operator_result
from app.engine.registry import OperatorRegistry
from app.main import app  # noqa: F401 - imports all built-in operators
from tests.operator_test_utils import TestLogger, operator_context


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


class TestEvaluationFeatureColumnAlignment(unittest.TestCase):
    """评估算子按模型 feature_names_in_ 对齐特征列。

    场景：拧紧测试 CSV 含 ID/原始列等多余列（24 列），而模型只有 15 个
    训练特征列——旧行为全列喂入报 "X has 24 features, but ... expecting 15"。
    """

    def setUp(self):
        rng = np.random.RandomState(42)
        self.feature_names = [f"f{i}" for i in range(15)]
        X = pd.DataFrame(rng.randn(60, 15), columns=self.feature_names)
        y = (X["f0"] + X["f1"] > 0).astype(int)
        self.classifier_bytes = _model_bytes(
            RandomForestClassifier(n_estimators=10, random_state=42).fit(X, y)
        )
        self.regressor_bytes = _model_bytes(
            LinearRegression().fit(X, X.sum(axis=1))
        )
        wide = pd.concat([X.copy(), pd.DataFrame(rng.randn(60, 9), columns=[f"extra_{i}" for i in range(9)])], axis=1)
        wide["target"] = y.values
        self.wide_records = wide.to_dict("records")
        # 缺失一个模型特征列的坏数据
        self.missing_feature_records = wide.drop(columns=["f0"]).to_dict("records")

    def _execute(self, operator_id, inputs, params):
        operator = OperatorRegistry.get(operator_id)
        result = operator.execute(operator_context(), inputs, params)
        validate_operator_result(operator.outputs, result)
        return result.outputs

    def test_detailed_eval_aligns_extra_columns_to_model_features(self):
        outputs = self._execute(
            "classification_eval_detailed",
            {"model": self.classifier_bytes, "test": self.wide_records},
            {"target_column": "target"},
        )
        self.assertEqual(outputs["metrics"]["total_samples"], 60)
        self.assertIn("accuracy", outputs["metrics"])

    def test_basic_eval_and_regression_align_extra_columns(self):
        basic = self._execute(
            "classification_eval", {"model": self.classifier_bytes, "test": self.wide_records},
            {"target_column": "target"},
        )
        self.assertIn("accuracy", basic["metrics"])

        regression = self._execute(
            "regression_eval",
            {"model": self.regressor_bytes, "test": self.wide_records},
            {"target_column": "target"},
        )
        self.assertIn("r2", regression["metrics"])

    def test_model_comparison_aligns_each_models_features(self):
        outputs = self._execute(
            "model_comparison",
            {
                "model_a": self.classifier_bytes,
                "model_b": self.classifier_bytes,
                "test": self.wide_records,
            },
            {"target_column": "target", "metric": "accuracy"},
        )
        self.assertIn("winner", outputs["comparison"])

    def test_missing_model_feature_column_raises_readable_error(self):
        with self.assertRaises(ValueError) as ctx:
            self._execute(
                "classification_eval_detailed",
                {"model": self.classifier_bytes, "test": self.missing_feature_records},
                {"target_column": "target"},
            )
        self.assertIn("缺少模型特征列", str(ctx.exception))
        self.assertIn("f0", str(ctx.exception))

    def test_missing_target_column_raises_readable_error(self):
        with self.assertRaises(ValueError) as ctx:
            self._execute(
                "classification_eval_detailed",
                {"model": self.classifier_bytes, "test": self.wide_records},
                {"target_column": "not_exist"},
            )
        self.assertIn("目标列", str(ctx.exception))


class _FakeArtifact:
    def __init__(self, storage_uri, fmt):
        self.storage_uri = storage_uri
        self.format = fmt


class _FakeStorage:
    def __init__(self, payload):
        self._payload = payload

    def open(self, uri):
        return io.BytesIO(self._payload)


class _FakeArtifactService:
    def __init__(self, artifact, payload):
        self._artifact = artifact
        self.storage = _FakeStorage(payload)

    def resolve(self, artifact_id, project_id, expected_type=None):
        return self._artifact


class TestLoadModelArtifactFormatGuard(unittest.TestCase):
    """load_model_artifact 对非 joblib 工件（如 ONNX）给出可读错误。

    旧行为把 ONNX 字节流当 pickle 读，报裸 "KeyError: 8" 无法定位。
    """

    def _execute_load(self, artifact, payload):
        operator = OperatorRegistry.get("load_model_artifact")
        context = OperatorContext(
            run_id="test-run", node_id="test-node", project_id="p",
            artifact_service=_FakeArtifactService(artifact, payload),
            cancel_requested=lambda: False, logger=TestLogger(),
        )
        return operator.execute(context, {}, {"model_artifact_id": "a"}).outputs

    def test_onnx_artifact_is_rejected_with_readable_message(self):
        with self.assertRaises(RuntimeError) as ctx:
            self._execute_load(_FakeArtifact("mem://m.onnx", "onnx"), b"not-a-pickle")
        self.assertIn("ONNX", str(ctx.exception))
        self.assertIn("joblib", str(ctx.exception))

    def test_joblib_artifact_still_loads(self):
        classifier = LogisticRegression(max_iter=1000).fit(
            pd.DataFrame({"feature": [0.0, 1.0, 2.0, 3.0]}), [0, 0, 1, 1]
        )
        outputs = self._execute_load(
            _FakeArtifact("mem://m.joblib", "joblib"), _model_bytes(classifier)
        )
        reloaded = joblib.load(io.BytesIO(outputs["model"]))
        self.assertTrue(hasattr(reloaded, "predict"))

    def test_packaged_artifact_injects_feature_names_from_schema(self):
        """numpy 拟合的 AutoML 打包工件：从 feature_schema 补 feature_names_in_。"""
        rng = np.random.RandomState(0)
        names = [f"c{i}" for i in range(4)]
        X = pd.DataFrame(rng.randn(30, 4), columns=names).to_numpy()  # numpy 拟合 → 无 feature_names_in_
        classifier = LogisticRegression(max_iter=1000).fit(X, [0, 1] * 15)
        self.assertFalse(hasattr(classifier, "feature_names_in_"))
        package = {
            "model": classifier,
            "feature_schema": [{"name": name, "dtype": "float64"} for name in names],
            "input_contract": {"input_columns": list(names)},
        }
        outputs = self._execute_load(
            _FakeArtifact("mem://m.joblib", "joblib"), _model_bytes(package)
        )
        reloaded = joblib.load(io.BytesIO(outputs["model"]))
        self.assertEqual([str(name) for name in reloaded.feature_names_in_], names)
        # 注入后按列名选列即可 predict（评估算子对齐路径）
        frame = pd.DataFrame(rng.randn(5, 4), columns=names)
        frame["extra"] = 1.0
        predictions = reloaded.predict(frame[names])
        self.assertEqual(len(predictions), 5)

    def test_xgboost_packaged_artifact_injects_via_booster(self):
        """xgboost 的 feature_names_in_ 是只读 property——经 booster.feature_names 注入。"""
        try:
            from xgboost import XGBClassifier
        except ImportError:
            self.skipTest("xgboost not installed")
        rng = np.random.RandomState(1)
        names = ["x1", "x2", "x3"]
        classifier = XGBClassifier(n_estimators=4, max_depth=2).fit(
            pd.DataFrame(rng.randn(30, 3), columns=names).to_numpy(), [0, 1] * 15
        )
        package = {
            "model": classifier,
            "feature_schema": [{"name": name, "dtype": "float64"} for name in names],
        }
        outputs = self._execute_load(
            _FakeArtifact("mem://m.joblib", "joblib"), _model_bytes(package)
        )
        reloaded = joblib.load(io.BytesIO(outputs["model"]))
        # joblib 往返后 property 仍返回注入的列名
        self.assertEqual([str(name) for name in reloaded.feature_names_in_], names)
        frame = pd.DataFrame(rng.randn(5, 3), columns=names)
        self.assertEqual(len(reloaded.predict(frame)), 5)

    def test_lightgbm_unsupported_injection_does_not_crash_load(self):
        """lightgbm 无公开特征名写入口——加载节点降级告警而不是抛 no setter。"""
        try:
            from lightgbm import LGBMClassifier
        except ImportError:
            self.skipTest("lightgbm not installed")
        rng = np.random.RandomState(2)
        names = ["l1", "l2"]
        classifier = LGBMClassifier(n_estimators=2, verbose=-1).fit(
            pd.DataFrame(rng.randn(30, 2), columns=names).to_numpy(), [0, 1] * 15
        )
        package = {
            "model": classifier,
            "feature_schema": [{"name": name, "dtype": "float64"} for name in names],
        }
        outputs = self._execute_load(
            _FakeArtifact("mem://m.joblib", "joblib"), _model_bytes(package)
        )
        reloaded = joblib.load(io.BytesIO(outputs["model"]))
        self.assertTrue(hasattr(reloaded, "predict"))


if __name__ == "__main__":
    unittest.main()
