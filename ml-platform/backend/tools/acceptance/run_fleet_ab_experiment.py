"""§7.1 架构 A/B 对比实验（技术方案 §7.1 判据，数据说话决策）。

方案 A（分片独立模型，当前实现）：每工位独立训练检测器+独立标定。
方案 B（全局共享检测器+设备级标定，方案原文）：4 工位训练集合并联合
训练一个检测器，每工位仅用自己的数据标定阈值。

判据（§7.1 原文）：方案 B 各工位误报率 ≤ 方案 A ×1.2 → B 达标（省
3/4 模型资源+新设备冷启动强）；否则 A 为正式架构（B 保留在 M9 迁移流）。

双族 iforest/ocsvm；标定/评估口径与判据④真实口径一致（holdout 误报率，
阈值取训练分数 1% 分位）。
"""

from __future__ import annotations

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
    AnomalyScoreCalibrator,
    pipeline_anomaly_scores,
)
from app.services.automl_catalog import get_algorithm_family  # noqa: E402

STATIONS = ["ZZQX113", "DPQX111", "DPX07", "DPQQ02"]
FAMILIES = {
    "iforest": {"n_estimators": 200, "max_samples": 256},
    "ocsvm": {"nu": 0.05, "kernel": "rbf", "gamma": "scale"},
}
FPR_TOLERANCE = 1.2


def load_station_frames(paths: list[str]) -> dict[str, pd.DataFrame]:
    return {path.split("/")[-1].replace(".csv", ""): pd.read_csv(path) for path in paths}


def split_train_holdout(frame: pd.DataFrame, seed: int = 42):
    matrix = frame.apply(pd.to_numeric, errors="coerce").dropna().to_numpy(dtype=float)
    holdout_size = max(1, int(len(matrix) * 0.2))
    train, holdout = train_test_split(matrix, test_size=holdout_size, random_state=seed)
    return train, holdout


def run_family(family_id: str, params: dict, station_data: dict) -> dict:
    family = get_algorithm_family(family_id)
    trains: dict[str, np.ndarray] = {}
    holdouts: dict[str, np.ndarray] = {}
    for station, frame in station_data.items():
        trains[station], holdouts[station] = split_train_holdout(frame)
    global_train = np.vstack([trains[s] for s in sorted(trains)])

    # 方案 A：独立模型
    plan_a = {}
    for station, train in trains.items():
        estimator = family.build("anomaly_detection", params)
        estimator.fit(train)
        calibrator = AnomalyScoreCalibrator.fit(
            pipeline_anomaly_scores(estimator, train), contamination=0.01,
        )
        threshold = float(calibrator.threshold_score)
        holdout_scores = pipeline_anomaly_scores(estimator, holdouts[station])
        plan_a[station] = {
            "fpr": round(float(np.mean(holdout_scores >= threshold)), 6),
            "threshold": threshold,
        }

    # 方案 B：全局模型（联合训练）+ 每设备标定
    global_estimator = family.build("anomaly_detection", params)
    global_estimator.fit(global_train)
    plan_b = {}
    for station, train in trains.items():
        calibrator = AnomalyScoreCalibrator.fit(
            pipeline_anomaly_scores(global_estimator, train), contamination=0.01,
        )
        threshold = float(calibrator.threshold_score)
        holdout_scores = pipeline_anomaly_scores(global_estimator, holdouts[station])
        plan_b[station] = {
            "fpr": round(float(np.mean(holdout_scores >= threshold)), 6),
            "threshold": threshold,
        }

    per_station = {}
    b_pass = True
    for station in sorted(trains):
        fpr_a = plan_a[station]["fpr"]
        fpr_b = plan_b[station]["fpr"]
        within = fpr_b <= FPR_TOLERANCE * max(fpr_a, 1e-9)
        b_pass = b_pass and within
        per_station[station] = {
            "plan_a_fpr": fpr_a,
            "plan_b_fpr": fpr_b,
            "within_tolerance": bool(within),
        }
    return {
        "family": family_id,
        "per_station": per_station,
        "b_pass": bool(b_pass),
    }


def main() -> int:
    import torch

    torch.set_num_threads(1)
    torch.manual_seed(42)
    np.random.seed(42)

    paths = sys.argv[1:5] if len(sys.argv) > 4 else [
        "../../temp_test/" + s + "_num.csv" for s in STATIONS
    ]
    station_data = load_station_frames(paths)
    print("stations:", {k: len(v) for k, v in station_data.items()}, flush=True)

    report = {
        "date": date.today().isoformat(),
        "criterion": f"方案 B 各工位误报率 ≤ 方案 A ×{FPR_TOLERANCE}（§7.1）",
        "families": {},
    }
    all_pass = True
    for family_id, params in FAMILIES.items():
        outcome = run_family(family_id, params, station_data)
        report["families"][family_id] = outcome
        all_pass = all_pass and outcome["b_pass"]
        print(f"{family_id}: B_pass={outcome['b_pass']}", flush=True)
        for station, row in outcome["per_station"].items():
            print(
                f"  {station}: A={row['plan_a_fpr']:.6f} B={row['plan_b_fpr']:.6f} "
                f"within={row['within_tolerance']}",
                flush=True,
            )
    report["verdict"] = (
        "方案 B（全局共享检测器+设备级标定）达标——建议 B 为正式架构（A 保留为 unfit 降级路径）"
        if all_pass
        else "方案 B 未达标——分片独立模型（方案 A）为正式架构（修方案 §7.1 口径）"
    )
    report["verdict_pass"] = bool(all_pass)
    out = Path("../../docs/验收-机群架构AB对比.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print("saved:", out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
