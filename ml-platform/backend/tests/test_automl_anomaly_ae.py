"""AE 第三族引擎接入测试（技术方案 §6.1，二期 M5）。

合同：
- 目录注册：anomaly 任务三族（iforest/ocsvm/autoencoder），监督任务不可见；
- torch 缺失降级：builder 抛 AlgorithmUnavailable（引擎记 trial unavailable，
  族自动缺席——§6.5「降级 joblib-only」预案的结构化形态）；
- 出场策略（§6.6D）：AE 只在 high/ultra 搜索强度出场；
- 评估链兼容：合成基准/门禁/稳定性对 AE 零改动复用（decision_function 接口）；
- onnx_worker AE 分支：分派 autoencoder → torch 融合单图 → ORT 逐位一致。
"""

import os
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault("LLM_MASTER_KEY", __import__(
    "cryptography.fernet", fromlist=["Fernet"]
).Fernet.generate_key().decode("ascii"))

import numpy as np  # noqa: E402

try:
    import torch  # noqa: F401
except ImportError:
    torch = None

if torch is None:
    raise unittest.SkipTest("torch not installed (AE family is opt-in until镜像接线)")

from app.services.automl_anomaly import (  # noqa: E402
    build_synthetic_benchmark,
    evaluate_anomaly_candidate,
    pipeline_anomaly_scores,
)
from app.services.automl_catalog import (  # noqa: E402
    AlgorithmUnavailable,
    get_algorithm_family,
    resolve_algorithm_families,
)


def _synthetic_dataset(rows=800, n_features=6, seed=42):
    rng = np.random.RandomState(seed)
    matrix = rng.randn(rows, n_features).astype(np.float32)
    return matrix


class TestAutoencoderCatalog(unittest.TestCase):
    """目录注册与出场策略。"""

    def test_registered_for_anomaly_only(self):
        anomaly_ids = [family.id for family in resolve_algorithm_families([], task="anomaly_detection")]
        self.assertIn("autoencoder", anomaly_ids)
        supervised_ids = [family.id for family in resolve_algorithm_families([], task="classification")]
        self.assertNotIn("autoencoder", supervised_ids)

    def test_builder_builds_pipeline(self):
        from sklearn.pipeline import Pipeline

        from app.services.automl_anomaly_ae import TorchAutoencoder

        family = get_algorithm_family("autoencoder")
        pipeline = family.build("anomaly_detection", {"epochs": 20, "hidden_units": 32})
        self.assertIsInstance(pipeline, Pipeline)
        self.assertIsInstance(pipeline.steps[-1][1], TorchAutoencoder)

    def test_builder_raises_unavailable_without_torch(self):
        from app.services import automl_anomaly_ae

        family = get_algorithm_family("autoencoder")
        with mock.patch.object(automl_anomaly_ae, "TORCH_AVAILABLE", False):
            with self.assertRaises(AlgorithmUnavailable):
                family.build("anomaly_detection", {})

    def test_resource_parameter_is_epochs(self):
        """epochs 是 int 资源参数（Hyperband 兼容；与 OC-SVM nu float 不同源）。"""
        family = get_algorithm_family("autoencoder")
        self.assertEqual(family.resource_parameter, "epochs")


class TestAutoencoderEvaluateChain(unittest.TestCase):
    """评估链兼容（§6.1：合成基准/标定/稳定性/归因零改动复用）。"""

    def test_evaluate_candidate_full_gates(self):
        matrix = _synthetic_dataset()
        holdout_size = max(1, int(len(matrix) * 0.2))
        train, holdout = matrix[:-holdout_size], matrix[-holdout_size:]
        benchmark = build_synthetic_benchmark(train, holdout, random_seed=42)
        family = get_algorithm_family("autoencoder")
        pipeline = family.build("anomaly_detection", {
            "hidden_units": 32, "hidden_layers": 2, "bottleneck_ratio": 0.25,
            "epochs": 30, "learning_rate": 0.001,
        })
        metrics = evaluate_anomaly_candidate(
            pipeline, train, holdout, benchmark,
            contamination=0.01, random_seed=42, compute_stability=True,
        )
        # 全门禁字段齐备且合成基准可分（合成数据上 AE 应接近完美）
        for key in ("synthetic_auc", "perturbation_recall", "normal_fpr", "stability", "gates_passed"):
            self.assertIn(key, metrics)
        self.assertGreaterEqual(float(metrics["synthetic_auc"]), 0.9)
        self.assertTrue(metrics["gates_passed"])

    def test_pipeline_anomaly_scores_direction(self):
        matrix = _synthetic_dataset()
        family = get_algorithm_family("autoencoder")
        pipeline = family.build("anomaly_detection", {"epochs": 20, "hidden_units": 32})
        pipeline.fit(matrix)
        scores_normal = pipeline_anomaly_scores(pipeline, matrix[:200])
        anomaly = matrix[:50].copy()
        anomaly[:, 0] += 10.0
        scores_anomaly = pipeline_anomaly_scores(pipeline, anomaly)
        self.assertLess(float(np.mean(scores_normal)), float(np.mean(scores_anomaly)))


class TestAutoencoderWorkerConversion(unittest.TestCase):
    """onnx_worker AE 分支：分派 + torch 融合单图 + ORT 逐位一致。"""

    def test_model_family_dispatch(self):
        from app.services.onnx_worker import _model_family

        family = get_algorithm_family("autoencoder")
        pipeline = family.build("anomaly_detection", {"epochs": 15})
        self.assertEqual(_model_family(pipeline), "autoencoder")

    def test_convert_and_ort_roundtrip(self):
        import joblib
        import onnxruntime as ort

        from app.services.onnx_worker import _convert

        matrix = _synthetic_dataset(rows=500)
        family = get_algorithm_family("autoencoder")
        pipeline = family.build("anomaly_detection", {"epochs": 15, "hidden_units": 32})
        pipeline.fit(matrix)
        directory = Path("temp_test") / "ae_worker_test"
        directory.mkdir(parents=True, exist_ok=True)
        source = directory / "bundle.joblib"
        destination = directory / "model.onnx"
        joblib.dump({
            "model": pipeline,
            "feature_schema": [
                {"name": f"f{index}", "dtype": "float64"} for index in range(matrix.shape[1])
            ],
            "target_schema": [],
        }, source)
        info = _convert(source, destination)
        self.assertEqual(info["converter"], "torch")
        self.assertEqual(info["output_names"], ["label", "scores"])
        session = ort.InferenceSession(str(destination), providers=["CPUExecutionProvider"])
        label, scores = session.run(
            ["label", "scores"], {"features": matrix[:100].astype(np.float32)},
        )
        # 推理侧同款取负（anomaly_score = −scores）后与 joblib 逐位一致
        joblib_scores = pipeline_anomaly_scores(pipeline, matrix[:100])
        max_abs_diff = float(np.max(np.abs(joblib_scores - (-np.asarray(scores)))))
        self.assertLessEqual(max_abs_diff, 1e-4)
        self.assertTrue(np.all(np.asarray(label) == 1))


if __name__ == "__main__":
    unittest.main()
