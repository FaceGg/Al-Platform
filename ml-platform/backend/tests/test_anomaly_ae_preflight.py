"""AE ONNX 先决测试（技术方案 §6.1/§6.6 B/C/D，二期 M5-0）。

tools/acceptance/run_anomaly_ae_preflight.py 的可回归测试切片（小数据快速
断言；全量数据实测走脚本落档）。CI 无 torch 时整类 skip（torch 进引擎依赖
是 M5 立项决策的一部分，采纳时同步改 CI 环境）。
"""

import os
import unittest

os.environ.setdefault("LLM_MASTER_KEY", __import__(
    "cryptography.fernet", fromlist=["Fernet"]
).Fernet.generate_key().decode("ascii"))

import numpy as np  # noqa: E402

try:
    import torch  # noqa: F401
except ImportError:
    torch = None

if torch is None:
    raise unittest.SkipTest("torch not installed (AE preflight is opt-in until M5 lands)")

from app.services.automl_anomaly import pipeline_anomaly_scores  # noqa: E402
from app.services.automl_anomaly_ae import (  # noqa: E402
    TorchAutoencoder,
    export_pipeline_autoencoder_onnx,
)


class TestTorchAutoencoderPreflight(unittest.TestCase):
    """先决合同：接口约束（§6.6B/C）+ ONNX 路径（§6.1 先决 1/2）+ 方向。"""

    def setUp(self):
        import torch as _torch

        _torch.manual_seed(42)
        np.random.seed(42)
        self.ae = TorchAutoencoder(hidden_units=32, hidden_layers=2,
                                   bottleneck_ratio=0.25, epochs=30)
        self.rng = np.random.RandomState(42)
        self.X_normal = self.rng.randn(2000, 10).astype(np.float32)
        self.X_anomaly = self.rng.randn(200, 10).astype(np.float32)
        self.X_anomaly[:, :2] += 8.0
        self.ae.fit(self.X_normal)

    def test_direction_higher_is_anomaly(self):
        """§6.6B 方向断言（decision_function=sklearn 惯例「越高越正常」）：
        正常样本 decision_function > 异常样本；anomaly score（=取负）反之。"""
        scores_normal = self.ae.decision_function(self.X_normal)
        scores_anomaly = self.ae.decision_function(self.X_anomaly)
        self.assertGreater(
            float(np.mean(scores_normal)), float(np.mean(scores_anomaly)),
        )
        # anomaly score 口径（+重构误差，越高越异常）方向正确
        self.assertLess(
            float(np.mean(-scores_normal)), float(np.mean(-scores_anomaly)),
        )

    def test_no_score_samples_interface(self):
        """§6.6B 接口约束：AE 不实现 score_samples（防分派先命中再取负翻转方向）。"""
        self.assertFalse(hasattr(self.ae, "score_samples"))

    def test_clone_protocol(self):
        """§6.6C clone 协议：stability_check 依赖 clone(fitted_estimator)。"""
        from sklearn.base import clone

        cloned = clone(self.ae)
        self.assertEqual(cloned.get_params(), self.ae.get_params())
        self.assertFalse(hasattr(cloned, "network_"))
        cloned.fit(self.X_normal[:500])
        self.assertTrue(hasattr(cloned, "network_"))

    def test_pipeline_anomaly_scores_positive_reconstruction(self):
        """管线口径：anomaly_score = -decision_function = +重构误差（越高越异常）。"""
        from sklearn.impute import SimpleImputer
        from sklearn.pipeline import Pipeline
        from sklearn.preprocessing import StandardScaler

        pipeline = Pipeline([
            ("imputer", SimpleImputer(strategy="median")),
            ("scaler", StandardScaler()),
            ("detector", self.ae),
        ])
        pipeline.fit(self.X_normal)
        scores = pipeline_anomaly_scores(pipeline, self.X_anomaly)
        scores_normal = pipeline_anomaly_scores(pipeline, self.X_normal)
        self.assertLess(float(np.mean(scores_normal)), float(np.mean(scores)))

    def test_onnx_export_and_consistency(self):
        """§6.1 先决 1/2：融合单图导出 + ORT 载入 + anomaly_score 一致性容差。

        融合图 scores=−MSE（正=正常）——enrich 取负后 anomaly_score=+MSE，
        与 sklearn 管线 pipeline_anomaly_scores（decision_function 取负）同
        口径；label 端口全 1 占位（判定走 threshold_score）。
        """
        import onnxruntime as ort
        from sklearn.impute import SimpleImputer
        from sklearn.pipeline import Pipeline
        from sklearn.preprocessing import StandardScaler

        pipeline = Pipeline([
            ("imputer", SimpleImputer(strategy="median")),
            ("scaler", StandardScaler()),
            ("detector", self.ae),
        ])
        pipeline.fit(self.X_normal)
        path = os.path.join("temp_test", "ae_preflight_test.onnx")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        export_pipeline_autoencoder_onnx(pipeline, path)
        session = ort.InferenceSession(path, providers=["CPUExecutionProvider"])
        onnx_label, onnx_scores = session.run(
            ["label", "scores"], {"features": self.X_anomaly.astype(np.float32)},
        )
        joblib_scores = pipeline_anomaly_scores(pipeline, self.X_anomaly)
        # 推理侧同款取负（anomaly_score = −scores 端口）后与 joblib 同口径
        onnx_anomaly_scores = -np.asarray(onnx_scores)
        max_abs_diff = float(np.max(np.abs(joblib_scores - onnx_anomaly_scores)))
        self.assertLessEqual(max_abs_diff, 1e-4)
        self.assertTrue(np.all(np.asarray(onnx_label) == 1))
        # 方向：ONNX scores（正=正常）正常样本 > 异常样本
        normal_scores = session.run(
            ["scores"], {"features": self.X_normal[:500].astype(np.float32)},
        )[0]
        self.assertGreater(float(np.mean(normal_scores)), float(np.mean(onnx_scores)))


if __name__ == "__main__":
    unittest.main()
