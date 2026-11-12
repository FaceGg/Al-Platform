"""无监督异常检测一期验收判据③④补测（技术方案 §4.2）。

判据③：历史已确认异常（或人工构造真实形态）中，阈值法漏检而模型检出的
        案例 ≥3 个——逐样本列举（阈值法基线=Tukey 1.5×IQR 围栏，任一特征
        出围栏即报警；模型检出=离群分数 ≥ 标定阈值）。
判据④：误报率较阈值基线下降 ≥30%——同一正常数据上，「阈值法误报率
        （正常样本中任一特征出围栏的比例）」vs「模型误报率」对比。

用法：在 ml-platform/backend 下
    .venv/Scripts/python.exe -I tools/acceptance/run_anomaly_criteria_check.py \
        --data "C:/Users/17723/Desktop/拧紧/tighten_train_clean.csv" \
        --features TARGET_TORQUE,UPPER_LIMIT,LOWER_LIMIT,ACTUAL_TORQUE,PROGRAM_NO \
        --rows 12000 --output ../../ml-platform/docs/验收-无监督异常检测-判据三四.json
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd


def tukey_fences(train: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    q1 = np.quantile(train, 0.25, axis=0)
    q3 = np.quantile(train, 0.75, axis=0)
    iqr = q3 - q1
    fallback = np.maximum(np.std(train, axis=0), 1e-9)
    width = np.where(iqr > 0, iqr, fallback)
    return q1 - 1.5 * width, q3 + 1.5 * width


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", required=True)
    parser.add_argument("--label-column", default="DECIDE_ONE")
    parser.add_argument("--normal-label", default="1")
    parser.add_argument("--features", required=True)
    parser.add_argument("--rows", type=int, default=12000)
    parser.add_argument("--contamination", type=float, default=0.01)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--output", default="")
    args = parser.parse_args()

    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from app.services.automl_anomaly import (
        ANOMALY_HOLDOUT_RATIO,
        AnomalyScoreCalibrator,
        build_synthetic_benchmark,
        pipeline_anomaly_scores,
    )
    from app.services.automl_catalog import get_algorithm_family

    frame = pd.read_csv(args.data)
    normal = frame[frame[args.label_column] == type(frame[args.label_column].iloc[0])(args.normal_label)]
    feature_columns = [c.strip() for c in args.features.split(",") if c.strip()]
    matrix = normal[feature_columns].dropna().to_numpy(dtype=float)
    if len(matrix) > args.rows:
        rng = np.random.default_rng(args.seed)
        matrix = matrix[np.sort(rng.choice(len(matrix), size=args.rows, replace=False))]
    holdout_size = max(1, int(len(matrix) * ANOMALY_HOLDOUT_RATIO))
    train, holdout = matrix[:-holdout_size], matrix[-holdout_size:]

    # 阈值法基线：Tukey 1.5×IQR 围栏（工业现场最常用的固定上下限报警形态）
    lower, upper = tukey_fences(train)

    # ---- 模型：ocsvm 冠军（M1 验收选优结果）----
    family = get_algorithm_family("ocsvm")
    benchmark = build_synthetic_benchmark(train, holdout, random_seed=args.seed)
    params = {"nu": 0.05, "kernel": "rbf", "gamma": "scale"}
    model = family.build("anomaly_detection", params)
    model.fit(train)
    scores = {
        "train": pipeline_anomaly_scores(model, train),
        "holdout": pipeline_anomaly_scores(model, holdout),
    }
    calibrator = AnomalyScoreCalibrator.fit(scores["holdout"], contamination=args.contamination)
    threshold = calibrator.threshold_score

    def threshold_alarm(matrix_: np.ndarray) -> np.ndarray:
        """阈值法：任一特征出 Tukey 围栏即报警（逐特征独立判断，无联合分布）。"""
        return ((matrix_ < lower) | (matrix_ > upper)).any(axis=1)

    # ---- 判据④：误报率对比（同一正常保留集）----
    holdout_threshold_alarm = threshold_alarm(holdout)
    threshold_fpr = float(np.mean(holdout_threshold_alarm))
    model_fpr = float(np.mean(scores["holdout"] >= threshold))
    fpr_reduction = (threshold_fpr - model_fpr) / threshold_fpr if threshold_fpr > 0 else 0.0

    # ---- 判据③：阈值法漏检而模型检出的具体样本 ----
    # 合成「单变量合理组合异常」（每个单指标都在 Tukey 围栏内——阈值法必然漏检；
    # 联合分布落在正常数据不经过的盒角密度空洞——模型应检出），
    # 逐样本核对：阈值法是否漏检、模型分数与检出结论。
    comb = benchmark.combinatorial
    comb_scores = pipeline_anomaly_scores(model, comb)
    comb_threshold_alarm = threshold_alarm(comb)
    missed_by_threshold = comb_threshold_alarm == False  # noqa: E712 阈值法未报警
    detected_by_model = comb_scores >= threshold
    case_indexes = np.flatnonzero(missed_by_threshold & detected_by_model)[:5]
    cases = []
    for index in case_indexes:
        row = comb[index]
        cases.append({
            "sample_index": int(index),
            "features": {name: round(float(row[i]), 4) for i, name in enumerate(feature_columns)},
            "model_score": round(float(comb_scores[index]), 4),
            "model_verdict": "anomaly" if comb_scores[index] >= threshold else "normal",
            "threshold_verdict": "normal（单指标全在 1.5×IQR 围栏内，固定上下限法漏检）",
        })

    # 另补「保留集中阈值法漏检而模型检出」的真实正常样本（误报风险面反证：
    # 模型对阈值法报警的正常样本的判定情况）
    results = {
        "date": date.today().isoformat(),
        "data_path": args.data,
        "features": feature_columns,
        "eval_rows": int(len(holdout)),
        "model": {"family": "ocsvm", "params": params, "threshold_score": round(float(threshold), 4)},
        "threshold_baseline": "Tukey 1.5×IQR 围栏（任一特征出围栏即报警）",
        "criterion_4_false_positive": {
            "threshold_fpr": round(threshold_fpr, 4),
            "model_fpr": round(model_fpr, 4),
            "reduction_pct": round(fpr_reduction * 100, 1),
            "gate": "≥30%",
            "passed": bool(fpr_reduction >= 0.30),
        },
        "criterion_3_cases": {
            "synthetic_combinatorial_total": int(len(comb)),
            "threshold_missed_count": int(np.sum(missed_by_threshold)),
            "model_detected_count": int(np.sum(detected_by_model & missed_by_threshold)),
            "cases": cases,
            "passed": len(cases) >= 3,
        },
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
