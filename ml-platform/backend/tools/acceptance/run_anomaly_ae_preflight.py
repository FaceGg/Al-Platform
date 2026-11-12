"""AE ONNX 先决实测（技术方案 §6.1/§6.6 B/C/D，二期 M5-0）。

动 autoencoder 实现前必做的先决验证，全部实测不猜：

1. torch.onnx.export 对封装 AE 的导出 + ORT 1.24.4 载入 + scores 方向实测
   （M3 坑①教训：不猜方向）；
2. joblib 管线 vs ONNX 融合单图的一致性容差（CPU 确定性：
   ``torch.set_num_threads(1)`` + 固定种子）；
3. stability_check 成本实测（5 次 80% 子采样重训，§6.1 先决 3）；
4. 单 trial 训练时长实测（§6.6D：决定 AE 出场强度/降级判定）；
5. sklearn clone 协议（§6.6C：stability_check 依赖 ``clone(estimator)``）；
6. AE 分数方向断言（§6.6B：正常样本 anomaly_score < 异常样本）。

模型实现：``app.services.automl_anomaly_ae``（M5 正式模块，本脚本是它的
验收载体）。M5-0 核心实测结论已固化在模块文档：AE 的 ONNX 融合图输出
``scores = −MSE``（正=正常），与一期 decision_function 端口合同对齐，
enrich/runtime 取负逻辑零改动。

用法::

    python tools/acceptance/run_anomaly_ae_preflight.py [--rows 10000] [--epochs 100]

输出 JSON 结论（stdout 末行），退出码 0=全部先决通过。
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np

BACKEND_ROOT = Path(__file__).resolve().parents[2]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

import torch  # noqa: E402
from sklearn.metrics import roc_auc_score  # noqa: E402

from app.services.automl_anomaly import pipeline_anomaly_scores  # noqa: E402
from app.services.automl_anomaly_ae import (  # noqa: E402
    TorchAutoencoder,
    export_pipeline_autoencoder_onnx,
)


def _direction_report(scores_normal, scores_anomaly):
    return {
        "normal_mean": round(float(np.mean(scores_normal)), 6),
        "anomaly_mean": round(float(np.mean(scores_anomaly)), 6),
        "direction_ok": bool(np.mean(scores_normal) < np.mean(scores_anomaly)),
    }


def run_preflight(rows: int, epochs: int) -> dict:
    import onnxruntime as ort
    from sklearn.base import clone
    from sklearn.impute import SimpleImputer
    from sklearn.pipeline import Pipeline
    from sklearn.preprocessing import StandardScaler

    report: dict = {"torch": torch.__version__}
    torch.set_num_threads(1)
    torch.manual_seed(42)
    np.random.seed(42)

    # 合成数据：正常 N(0,1)，异常=大偏移（方向断言与一致性断言共用）
    n_features = 20
    X_normal = np.random.randn(rows // 2, n_features).astype(np.float32)
    X_anomaly = np.random.randn(rows // 10, n_features).astype(np.float32)
    X_anomaly[:, :4] += 8.0

    ae = TorchAutoencoder(hidden_units=64, hidden_layers=2, bottleneck_ratio=0.25,
                          epochs=epochs, learning_rate=1e-3, noise_sigma=0.05)
    started = time.perf_counter()
    ae.fit(X_normal)
    single_fit_seconds = time.perf_counter() - started
    report["single_fit_seconds"] = round(single_fit_seconds, 3)

    # §6.6B 方向断言：anomaly_score（=+重构误差，越高越异常）正常 < 异常；
    # AUC 以 anomaly_score 为分数（异常类=1 对应高分）。
    scores_normal = ae.decision_function(X_normal)
    scores_anomaly = ae.decision_function(X_anomaly)
    report["direction"] = _direction_report(-scores_normal, -scores_anomaly)
    report["direction"]["auc"] = round(float(roc_auc_score(
        np.r_[np.zeros(len(scores_normal)), np.ones(len(scores_anomaly))],
        np.r_[-scores_normal, -scores_anomaly],
    )), 4)

    # §6.6C clone 协议
    cloned = clone(ae)
    report["clone_ok"] = bool(
        cloned.get_params() == ae.get_params() and not hasattr(cloned, "network_")
    )

    # 管线 joblib vs ONNX 融合单图一致性（§6.1 先决 2）：
    # pipeline_anomaly_scores 对 decision_function 取负（sklearn 惯例正=正常）
    # → AE anomaly_score=+MSE；ONNX 融合图 scores=−MSE（正=正常）——按推理
    # 侧同款取负（anomaly_score=−scores）后同口径可比。
    pipeline = Pipeline([
        ("imputer", SimpleImputer(strategy="median")),
        ("scaler", StandardScaler()),
        ("detector", ae),
    ])
    pipeline.fit(X_normal)
    joblib_scores = pipeline_anomaly_scores(pipeline, X_anomaly)
    onnx_path = Path("temp_test") / "ae_preflight.onnx"
    onnx_path.parent.mkdir(parents=True, exist_ok=True)
    export_pipeline_autoencoder_onnx(pipeline, onnx_path)
    session = ort.InferenceSession(str(onnx_path), providers=["CPUExecutionProvider"])
    onnx_label, onnx_scores = session.run(
        ["label", "scores"], {"features": X_anomaly.astype(np.float32)},
    )
    onnx_anomaly_scores = -np.asarray(onnx_scores)
    max_abs_diff = float(np.max(np.abs(joblib_scores - onnx_anomaly_scores)))
    report["onnx_max_abs_diff"] = round(max_abs_diff, 8)
    report["onnx_consistency_ok"] = bool(max_abs_diff <= 1e-4)
    # label 端口占位全 1（一期合同：平台判定走 threshold_score，label 仅回退）
    report["onnx_label_placeholder_ok"] = bool(np.all(np.asarray(onnx_label) == 1))

    # stability_check 成本（§6.1 先决 3）：5 次 80% 子采样重训
    started = time.perf_counter()
    for _ in range(5):
        sub = X_normal[np.random.choice(len(X_normal), int(len(X_normal) * 0.8), replace=False)]
        TorchAutoencoder(epochs=epochs).fit(sub)
    report["stability_5x_seconds"] = round(time.perf_counter() - started, 3)

    # 单 trial 时长（§6.6D）：拟合即 trial 主体 + 管线评估开销估计 20%
    report["trial_estimate_seconds"] = round(single_fit_seconds * 1.2, 3)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rows", type=int, default=10000)
    parser.add_argument("--epochs", type=int, default=100)
    args = parser.parse_args()
    report = run_preflight(rows=args.rows, epochs=args.epochs)
    verdict = {
        "export_and_ort_load": True,
        "direction_ok": report["direction"]["direction_ok"],
        "onnx_consistency_ok": report["onnx_consistency_ok"],
        "onnx_label_placeholder_ok": report["onnx_label_placeholder_ok"],
        "clone_ok": report["clone_ok"],
    }
    report["verdict"] = verdict
    report["all_pass"] = all(verdict.values())
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["all_pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
