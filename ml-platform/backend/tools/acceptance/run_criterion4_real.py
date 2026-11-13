"""判据④真实口径（拧紧 28 万行）：阈值基线 vs 异常检测误报率对比。

口径（方案 §4.2 判据④，替换此前的合成越界点代测）：
- 数据：拧紧 train_features.csv 全量（280,373 行真实历史数据，DECIDE 判定列）
- 正常行 = DECIDE==1（现场判定合格）
- 阈值基线报警 = ACTUAL_TORQUE 超出 [LOWER_LIMIT, UPPER_LIMIT]（现场固定
  阈值规则的单轴口径；二轴同规则并集计入敏感性检验）
- 模型报警 = anomaly_score ≥ 该模型标定阈值（contamination=0.01 保留集分位）
- 误报率 = 正常行上的报警占比；判据④ = 模型误报率较阈值基线下降 ≥30%
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
    ANOMALY_HOLDOUT_RATIO,
    AnomalyScoreCalibrator,
    pipeline_anomaly_scores,
)
from app.services.automl_anomaly_ae import TorchAutoencoder  # noqa: E402
from app.services.automl_catalog import get_algorithm_family  # noqa: E402


def main() -> int:
    import torch

    torch.set_num_threads(1)
    torch.manual_seed(42)
    np.random.seed(42)

    data_path = sys.argv[1] if len(sys.argv) > 1 else "../../temp_test/tighten_full.csv"
    frame = pd.read_csv(data_path)
    total_rows = len(frame)
    normal = frame[frame["DECIDE(判定（最终判定）（0-不合格，1-合格）)"] == 1]
    feature_columns = [
        "TARGET_TORQUE(设定目标力矩（N.m）)",
        "UPPER_LIMIT(力矩上限（N.m）)",
        "LOWER_LIMIT(力矩下限（N.m）)",
        "ACTUAL_TORQUE(实际扭矩/一轴实际扭矩)",
        "ACTUAL_TORQUE_TWO(二轴实际扭矩)",
        "TIGHTEN_TORQUE_DEVIATION",
        "TIGHTEN_DEVIATION_RATIO",
        "TIGHTEN_UPPER_MARGIN",
        "TIGHTEN_LOWER_MARGIN",
        "TIGHTEN_DUAL_AXIS_DIFF",
        "TIGHTEN_MISSING_FLAG",
    ]
    normal_matrix = normal[feature_columns].apply(pd.to_numeric, errors="coerce").dropna()
    normal_matrix = normal_matrix.to_numpy(dtype=float)
    actual = pd.to_numeric(normal["ACTUAL_TORQUE(实际扭矩/一轴实际扭矩)"], errors="coerce")
    lower = pd.to_numeric(normal["LOWER_LIMIT(力矩下限（N.m）)"], errors="coerce")
    upper = pd.to_numeric(normal["UPPER_LIMIT(力矩上限（N.m）)"], errors="coerce")
    valid = actual.notna() & lower.notna() & upper.notna()
    baseline_mask = valid.to_numpy()
    baseline_actual = actual[valid].to_numpy(dtype=float)
    baseline_lower = lower[valid].to_numpy(dtype=float)
    baseline_upper = upper[valid].to_numpy(dtype=float)

    baseline_alerts = (baseline_actual < baseline_lower) | (baseline_actual > baseline_upper)
    baseline_fpr = float(np.mean(baseline_alerts))

    holdout_size = max(1, int(len(normal_matrix) * ANOMALY_HOLDOUT_RATIO))
    train_matrix, holdout_matrix = (
        normal_matrix[:-holdout_size],
        normal_matrix[-holdout_size:],
    )
    holdout_baseline = baseline_alerts[-holdout_size:]

    hyperparams = {
        "iforest": {"n_estimators": 200, "max_samples": 256},
        "ocsvm": {"nu": 0.05, "kernel": "rbf", "gamma": "scale"},
        "autoencoder": {"hidden_units": 64, "hidden_layers": 2,
                        "bottleneck_ratio": 0.25, "epochs": 60,
                        "learning_rate": 0.001},
    }
    families_result = {}
    for family_id, params in hyperparams.items():
        try:
            estimator = get_algorithm_family(family_id).build("anomaly_detection", params)
            estimator.fit(train_matrix)
            scores = pipeline_anomaly_scores(estimator, holdout_matrix)
            from app.services.automl_anomaly import AnomalyScoreCalibrator

            calibrator = AnomalyScoreCalibrator.fit(
                pipeline_anomaly_scores(estimator, train_matrix),
                contamination=args_contamination(),
            )
            threshold = float(calibrator.threshold_score)
            model_alerts = scores >= threshold
            baseline_side = holdout_baseline
            model_fpr = float(np.mean(model_alerts))
            base_fpr = float(np.mean(baseline_side))
            reduction = (1 - model_fpr / base_fpr) if base_fpr > 0 else None
            families_result[family_id] = {
                "model_fpr": round(model_fpr, 6),
                "baseline_fpr": round(base_fpr, 6),
                "reduction": round(reduction, 4) if reduction is not None else None,
                "criterion_4_pass": bool(reduction is not None and reduction >= 0.30),
            }
        except Exception as error:  # noqa: BLE001
            families_result[family_id] = {"status": "skipped", "reason": str(error)[:150]}

    output = {
        "date": date.today().isoformat(),
        "criterion": "§4.2 判据④真实口径（DECIDE 标签直接对比，替换合成越界点代测）",
        "total_rows": total_rows,
        "normal_rows_decide1": int(len(normal)),
        "eval_rows": int(len(holdout_matrix)),
        "baseline_rule": "ACTUAL_TORQUE 超出 [LOWER_LIMIT, UPPER_LIMIT]",
        "baseline_fpr_full_normal": round(baseline_fpr, 6),
        "families": families_result,
    }
    print(json.dumps(output, ensure_ascii=False, indent=2))
    # 产物落**可跟踪**的文档目录（仓库根 docs/ 被 .gitignore 排除，证据不入库
    # 会让已提交的验收文档链接失效——2026-11-13 审计同款问题）。
    out = BACKEND_ROOT.parent / "docs" / "验收-判据四真实口径.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"saved: {out}")
    return 0


def args_contamination() -> float:
    return 0.01


if __name__ == "__main__":
    raise SystemExit(main())
