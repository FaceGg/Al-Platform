"""Model-port loading, feature-hint prediction, and override installer tests."""
import io
import sys
import unittest

import joblib
import pandas as pd
from sklearn.linear_model import LinearRegression

sys.path.insert(0, ".")

from app.services.apply_model_override import install_apply_model_override  # noqa: E402
from app.services.model_port import load_model_port  # noqa: E402
from app.engine.registry import OperatorRegistry  # noqa: E402
import app.operators  # noqa: F401,E402  (populates the registry)


def _trained_port_bytes():
    """A model-library-style artifact: dict with model + feature_schema."""
    df = pd.DataFrame({"current": [8.0, 9.0, 10.0, 11.0], "force": [2.0, 2.5, 3.0, 3.5]})
    model = LinearRegression().fit(df, [1.0, 2.0, 3.0, 4.0])
    buf = io.BytesIO()
    joblib.dump({"model": model, "feature_schema": ["current", "force"]}, buf)
    return buf.getvalue()


class TestLoadModelPort(unittest.TestCase):
    def test_loads_dict_package_transparently(self):
        # load_model_port returns the package as-is; the apply_model override
        # performs the estimator unwrap (duties are split that way).
        model, pkg = load_model_port(_trained_port_bytes())
        self.assertIsNone(pkg)
        self.assertIsInstance(model, dict)

    def test_load_failure_carries_clear_message(self):
        with self.assertRaises(RuntimeError) as ctx:
            load_model_port(b"\x06not-a-model")
        self.assertIn("模型端口数据无法加载", str(ctx.exception))


class TestOverrideInstaller(unittest.TestCase):
    def setUp(self):
        install_apply_model_override()
        self.op = OperatorRegistry.get("apply_model")
        self.assertIsNotNone(self.op)

    def test_predict_failure_names_expected_features(self):
        # A pytorch-free sklearn model trained on named columns raises a
        # feature-name error for unknown columns; the override must surface it
        # with the expected feature list instead of a load-key error.
        df = pd.DataFrame({"a": [1, 2], "b": [2, 4]})
        model = LinearRegression().fit(df, [1.0, 2.0])
        buf = io.BytesIO()
        joblib.dump(model, buf)
        with self.assertRaises(RuntimeError) as ctx:
            self.op.execute(
                context=None,
                inputs={"model": buf.getvalue(), "data": [{"x": 1, "y": 2}]},
                params={},
            )
        msg = str(ctx.exception)
        self.assertIn("模型预测失败", msg)
        self.assertIn("模型期望 2 个特征", msg)

    def test_mismatched_record_surfaces_feature_hint(self):
        # A pytorch-free sklearn model trained on named columns raises a
        # feature-name error for unknown columns; the override must surface it
        # with the expected feature list instead of a load-key error.
        df = pd.DataFrame({"a": [1, 2], "b": [2, 4]})
        model = LinearRegression().fit(df, [1.0, 2.0])
        buf = io.BytesIO()
        joblib.dump(model, buf)
        with self.assertRaises(RuntimeError) as ctx:
            self.op.execute(
                context=None,
                inputs={"model": buf.getvalue(), "data": [{"x": 1, "y": 2}]},
                params={},
            )
        msg = str(ctx.exception)
        self.assertIn("模型预测失败", msg)
        self.assertIn("模型期望 2 个特征", msg)

    def test_matching_record_predicts_with_prediction_column(self):
        result = self.op.execute(
            context=None,
            inputs={"model": _trained_port_bytes(),
                    "data": [{"current": 10.0, "force": 3.0}]},
            params={},
        )
        rows = result.outputs["data"]
        self.assertEqual(len(rows), 1)
        self.assertIn("prediction", rows[0])


if __name__ == "__main__":
    unittest.main()
