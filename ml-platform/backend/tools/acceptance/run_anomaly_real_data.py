"""无监督异常检测真实数据验收（技术方案 §4.2 判据①，2026-11-12 M1 收官）。

对历史正常数据（≥1 万行）做引擎级评估：合成异常基准门禁
（synthetic_auc ≥ 0.85、normal_fpr ≤ contamination×1.5、stability ≥ 0.8）。

用法（在 ml-platform/backend 下）：
    .venv/Scripts/python.exe -I tools/acceptance/run_anomaly_real_data.py \
        --data "C:/Users/17723/Desktop/拧紧/tighten_train_clean.csv" \
        --label-column DECIDE_ONE --normal-label 1 \
        --features TARGET_TORQUE,UPPER_LIMIT,LOWER_LIMIT,ACTUAL_TORQUE,PROGRAM_NO \
        --rows 12000 --output ../../docs/验收-无监督异常检测-真实数据.json

数据路径不在仓库内（现场数据），换机器跑需同步提供同口径 CSV。
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", required=True, help="历史数据 CSV 路径")
    parser.add_argument("--label-column", default="DECIDE_ONE", help="判定列（用于筛正常样本）")
    parser.add_argument("--normal-label", default="1", help="判定列中代表「正常」的取值")
    parser.add_argument("--features", required=True, help="逗号分隔的特征列名")
    parser.add_argument("--rows", type=int, default=12000, help="采样行数（OC-SVM 上限内、评估耗时可控）")
    parser.add_argument("--contamination", type=float, default=0.01)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--output", default="", help="结果 JSON 输出路径（缺省仅打印）")
    args = parser.parse_args()

    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from app.console_encoding import force_utf8_stdio

    # Windows 管道 stdout 默认用 locale 代码页（cp1252），中文 print 会抛
    # UnicodeEncodeError —— 统一切 UTF-8（见 app/console_encoding.py）。
    force_utf8_stdio()
    from app.services.automl_anomaly import (
        ANOMALY_HOLDOUT_RATIO,
        build_synthetic_benchmark,
        evaluate_anomaly_candidate,
    )
    from app.services.automl_catalog import get_algorithm_family

    frame = pd.read_csv(args.data)
    normal = frame[frame[args.label_column] == type(frame[args.label_column].iloc[0])(args.normal_label)]
    feature_columns = [column.strip() for column in args.features.split(",") if column.strip()]
    matrix = normal[feature_columns].dropna().to_numpy(dtype=float)
    if len(matrix) > args.rows:
        rng = np.random.default_rng(args.seed)
        matrix = matrix[np.sort(rng.choice(len(matrix), size=args.rows, replace=False))]
    holdout_size = max(1, int(len(matrix) * ANOMALY_HOLDOUT_RATIO))
    train, holdout = matrix[:-holdout_size], matrix[-holdout_size:]
    benchmark = build_synthetic_benchmark(train, holdout, random_seed=args.seed)

    results = {
        "date": date.today().isoformat(),
        "data_path": args.data,
        "label_column": args.label_column,
        "normal_label": args.normal_label,
        "normal_rows_total": int(len(normal)),
        "eval_rows": int(len(matrix)),
        "features": feature_columns,
        "contamination": args.contamination,
        "train_rows": int(len(train)),
        "holdout_rows": int(len(holdout)),
        "gates": {"synthetic_auc": 0.85, "normal_fpr": args.contamination * 1.5, "stability": 0.8},
        "families": {},
    }
    hyperparams = {
        "iforest": {"n_estimators": 200, "max_samples": 512},
        "ocsvm": {"nu": 0.05, "kernel": "rbf", "gamma": "scale"},
        # AE 第三族对照（§6.1 二期 M5 立项门槛）：comb 检出率 ≥ ocsvm 基线
        # （一期实测 0.79）+0.05 才采纳为可选族，否则如实记录「本域无边际
        # 收益」并保留族位（torch 缺失时自动跳过，不影响双族）。
        "autoencoder": {"hidden_units": 64, "hidden_layers": 2,
                        "bottleneck_ratio": 0.25, "epochs": 100,
                        "learning_rate": 0.001},
    }
    for family_id, params in hyperparams.items():
        try:
            estimator = get_algorithm_family(family_id).build("anomaly_detection", params)
        except Exception as error:  # noqa: BLE001 - torch 缺失等环境级缺席如实记录
            results["families"][family_id] = {
                "status": "skipped",
                "reason": f"{type(error).__name__}: {error}",
            }
            continue
        metrics = evaluate_anomaly_candidate(
            get_algorithm_family(family_id).build("anomaly_detection", params),
            train,
            holdout,
            benchmark,
            contamination=args.contamination,
            random_seed=args.seed,
            compute_stability=True,
        )
        results["families"][family_id] = {
            key: metrics.get(key)
            for key in ("synthetic_auc", "perturbation_recall", "normal_fpr", "stability", "gates_passed")
        } | {
            "detection_recall_per_class": metrics.get("detection_recall_per_class"),
            "threshold_score": metrics.get("threshold_score"),
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
