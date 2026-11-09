# -*- coding: utf-8 -*-
"""回归测试：apply_model 显式特征子集（feature_columns）。

背景（2026-11-09 点焊 E2E）：servitize 编排链 S2 特征变换输出 75 列，
模型为 numpy 训练（无 feature_names_in_），apply_model 整帧预测报
"X has 75 features, but ExtraTreesClassifier is expecting 36"。
修复：发布链把模型版本 feature_schema 注入 apply_model.feature_columns，
运行期按名选列后再 predict；缺列时显式报错而非笼统列数不匹配。
"""

import io
import unittest

import joblib
import pandas as pd

from app.engine.operator_contract import OperatorResult
from app.engine.registry import OperatorRegistry
from app.services.apply_model_override import install_apply_model_override

import app.operators.ml_operators  # noqa: F401  触发算子注册


class _NumpyTrainedStub:
    """无 feature_names_in_ 的 numpy 训练估计器桩：只接受 2 列输入。"""

    def predict(self, X):
        assert X.shape[1] == 2, "stub expects exactly 2 columns, got %d" % X.shape[1]
        return [1] * len(X)


class TestApplyModelFeatureColumns(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        install_apply_model_override()
        cls.op = OperatorRegistry.get("apply_model")
        assert cls.op is not None
        stub = _NumpyTrainedStub()
        cls.model_bytes = io.BytesIO()
        joblib.dump(stub, cls.model_bytes)
        cls.model_bytes = cls.model_bytes.getvalue()
        cls.frame = pd.DataFrame({
            "a": [1.0, 2.0],
            "b": [3.0, 4.0],
            "noise1": [9.0, 9.0],
            "noise2": [8.0, 8.0],
        })

    def _run(self, params, frame=None):
        return self.op.execute(
            context=None,
            inputs={"model": self.model_bytes, "data": (frame or self.frame)},
            params=params,
        )

    def test_feature_columns_param_declared(self):
        names = [p.name for p in self.op.parameters]
        self.assertIn("feature_columns", names)

    def test_subset_by_feature_columns(self):
        # 桩只接受 2 列：整帧（4 列）会失败；按 feature_columns 选列后成功
        result = self._run({"feature_columns": ["a", "b"]})
        self.assertIsInstance(result, OperatorResult)
        rows = result.outputs["data"]
        self.assertEqual(len(rows), 2)
        self.assertEqual([r["prediction"] for r in rows], [1, 1])
        # 原始列保留在输出行中（含 prediction 追加列）
        self.assertIn("a", rows[0])

    def test_missing_feature_column_raises_clear_error(self):
        with self.assertRaises(RuntimeError) as ctx:
            self._run({"feature_columns": ["a", "b", "not_in_frame"]})
        self.assertIn("缺少模型特征列", str(ctx.exception))

    def test_no_feature_columns_keeps_legacy_behavior(self):
        # 未声明 feature_columns 时维持旧行为（predict_with_hint 兜底报错）
        with self.assertRaises(RuntimeError):
            self._run({})


if __name__ == "__main__":
    unittest.main()
