"""点焊真实数据实验（判据①点焊域补跑 + 真实异常检出三族对照）。

数据：栈内点焊项目 train_features.csv（2,072 行真实特征工程数据，73 数值
特征列 + fault 标签列；fault=0 正常 1,836 行 / fault=1 真实异常 236 行）。

口径（如实标注）：
- 正常行 1,836 < 方案判据①门槛 10,000——**行数门槛不满足**，本实验为
  「小样本真实数据的机制复证 + 真实异常检出对照」，非判据①正式达标；
  正式达标待真实点焊历史数据（≥1 万行）接入。
- 与合成基准对照（uniform/perturbation/combinatorial 三类注入）并行给出，
  真实异常检出率是比合成基准更强的证据（真实劣化形态 vs 人工构造）。

用法（在 ml-platform/backend 下）::

    .venv/Scripts/python.exe tools/acceptance/run_spot_weld_real_experiment.py \
        --data <train_features.csv 路径> --output ../../docs/验收-点焊真实数据.json
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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", required=True)
    parser.add_argument("--label-column", default="fault")
    parser.add_argument("--normal-label", type=float, default=0.0)
    parser.add_argument("--contamination", type=float, default=0.01)
    parser.add_argument("--seed", type=int, default=42)
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
        "total_rows": int(len(frame)),
        "normal_rows": int(len(normal_matrix)),
        "real_anomaly_rows": int(len(anomaly_matrix)),
        "feature_count": len(feature_columns),
        "contamination": args.contamination,
        "calibration_note": "行数口径：正常行 1,836 < 判据①门槛 10,000——小样本真实数据机制复证，非正式达标",
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
            "real_anomaly_recall": round(real_recall, 4),
            "real_anomaly_detected": int(np.sum(real_scores >= threshold)),
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
