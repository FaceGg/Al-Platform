"""点焊域实验（判据①点焊域补跑 + 标签异常检出三族对照）。

数据：点焊特征工程数据集（2,072 行 × 73 数值特征列 + fault 标签列；
fault=0 正常 1,836 行 / fault=1 异常 236 行）。

**数据来源（provenance）必须显式声明，不得默认「真实」**：
本仓库历史运行所用数据集来自合成生成器
``generate_spot_weld_synthetic_v2.py``（fault 模式：under_current /
short_time / shunting / electrode_wear / spatter / pressure_instability），
即「带标签的合成数据」，**不是产线实测数据**。用 ``--data-provenance``
显式声明本次运行的数据来源，产物 JSON 随附该声明。

口径（如实标注）：
- 正常行 1,836 < 方案判据①门槛 10,000——**行数门槛不满足**，本实验为
  「小样本数据的机制复证 + 标签异常检出对照」，非判据①正式达标；
  正式达标待真实点焊历史数据（≥1 万行）接入。
- 与合成基准对照（uniform/perturbation/combinatorial 三类注入）并行给出。
  注意：本数据集的「标签异常」本身也是生成器注入的形态，与平台合成基准的
  构造形态不同族——故「合成基准检出 ≈ 0 而标签异常检出 46~76%」证明的是
  **两类合成形态不重合**，不能当产线真实劣化的证据。

用法（在 ml-platform/backend 下）::

    .venv/Scripts/python.exe tools/acceptance/run_spot_weld_real_experiment.py \
        --data <train_features.csv 路径> --data-provenance generator-synthetic \
        --output ../../docs/验收-点焊真实数据.json
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

BACKEND_ROOT = Path(__file__).resolve().parents[2]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from sklearn.model_selection import train_test_split  # noqa: E402

from app.services.automl_anomaly import (  # noqa: E402
    ANOMALY_HOLDOUT_RATIO,
    build_synthetic_benchmark,
    pipeline_anomaly_scores,
)
from app.services.automl_anomaly_ae import TorchAutoencoder  # noqa: E402
from app.services.automl_catalog import get_algorithm_family  # noqa: E402
from app.console_encoding import force_utf8_stdio  # noqa: E402


def main() -> int:
    # Windows 管道 stdout 默认用 locale 代码页（cp1252），中文 print 会抛
    # UnicodeEncodeError —— 统一切 UTF-8（见 app/console_encoding.py）。
    force_utf8_stdio()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", required=True)
    parser.add_argument("--label-column", default="fault")
    parser.add_argument("--normal-label", type=float, default=0.0)
    parser.add_argument("--contamination", type=float, default=0.01)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument(
        "--data-provenance",
        default="generator-synthetic",
        choices=["generator-synthetic", "production-real", "unknown"],
        help=(
            "数据来源声明：generator-synthetic=合成生成器产物（含生成式注入标签）；"
            "production-real=产线实测数据；unknown=来源不明（不可用于对外结论）"
        ),
    )
    parser.add_argument("--output", default="")
    args = parser.parse_args()

    import torch

    torch.set_num_threads(1)
    torch.manual_seed(args.seed)
    np.random.seed(args.seed)

    frame = pd.read_csv(args.data)
    label_values = frame[args.label_column]
    normal = frame[label_values == args.normal_label]
    real_anomalies = frame[label_values != args.normal_label]
    feature_columns = [
        column for column in frame.columns
        if column != args.label_column and pd.api.types.is_numeric_dtype(frame[column])
    ]
    normal_matrix = normal[feature_columns].dropna().to_numpy(dtype=float)
    anomaly_matrix = real_anomalies[feature_columns].dropna().to_numpy(dtype=float)
    holdout_size = max(1, int(len(normal_matrix) * ANOMALY_HOLDOUT_RATIO))
    train_matrix = normal_matrix[:-holdout_size]
    holdout_matrix = normal_matrix[-holdout_size:]
    benchmark = build_synthetic_benchmark(train_matrix, holdout_matrix, random_seed=args.seed)

    hyperparams = {
        "iforest": {"n_estimators": 200, "max_samples": 256},
        "ocsvm": {"nu": 0.05, "kernel": "rbf", "gamma": "scale"},
        "autoencoder": {"hidden_units": 64, "hidden_layers": 2,
                        "bottleneck_ratio": 0.25, "epochs": 60,
                        "learning_rate": 0.001},
    }
    results = {
        "date": date.today().isoformat(),
        "data_path": args.data,
        "data_provenance": args.data_provenance,
        "provenance_note": (
            "generator-synthetic：数据由合成生成器产出，fault 标签是生成式注入形态，"
            "不等于产线实测劣化；结论仅限「两类合成形态不重合」这一方法论命题。"
            if args.data_provenance == "generator-synthetic"
            else "production-real：产线实测数据。"
            if args.data_provenance == "production-real"
            else "unknown：来源不明，不可用于对外结论。"
        ),
        "total_rows": int(len(frame)),
        "normal_rows": int(len(normal_matrix)),
        "labeled_anomaly_rows": int(len(anomaly_matrix)),
        "feature_count": len(feature_columns),
        "contamination": args.contamination,
        "calibration_note": "行数口径：正常行 1,836 < 判据①门槛 10,000——小样本数据机制复证，非正式达标",
        "families": {},
    }
    for family_id, params in hyperparams.items():
        try:
            estimator = get_algorithm_family(family_id).build("anomaly_detection", params)
        except Exception as error:  # noqa: BLE001
            results["families"][family_id] = {"status": "skipped", "reason": str(error)[:120]}
            continue
        estimator.fit(train_matrix)
        holdout_scores = pipeline_anomaly_scores(estimator, holdout_matrix)
        from app.services.automl_anomaly import AnomalyScoreCalibrator

        calibrator = AnomalyScoreCalibrator.fit(holdout_scores, contamination=args.contamination)
        threshold = float(calibrator.threshold_score)
        real_scores = pipeline_anomaly_scores(estimator, anomaly_matrix)
        real_recall = float(np.mean(real_scores >= threshold))
        uniform_scores = pipeline_anomaly_scores(estimator, benchmark.uniform_outliers)
        perturbation_scores = pipeline_anomaly_scores(estimator, benchmark.perturbations)
        combinatorial_scores = pipeline_anomaly_scores(estimator, benchmark.combinatorial)
        synthetic_recall = {
            "uniform_outlier": round(float(np.mean(uniform_scores >= threshold)), 4),
            "local_perturbation": round(float(np.mean(perturbation_scores >= threshold)), 4),
            "combinatorial_anomaly": round(float(np.mean(combinatorial_scores >= threshold)), 4),
        }
        results["families"][family_id] = {
            "threshold_score": round(threshold, 6),
            "labeled_anomaly_recall": round(real_recall, 4),
            "labeled_anomaly_detected": int(np.sum(real_scores >= threshold)),
            "holdout_fpr": round(float(np.mean(holdout_scores >= threshold)), 4),
            "synthetic_recall": synthetic_recall,
        }

    print(json.dumps(results, ensure_ascii=False, indent=2))
    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"saved: {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
