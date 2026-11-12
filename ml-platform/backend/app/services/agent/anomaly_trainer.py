"""智能体 S3 无监督训练器（task_type="anomaly" 专用）。

与 executor.lightweight_trainer 同构的返回形状（metrics / topk_metrics /
importance / data_fidelity / champion_*），内部复用 M1 引擎核心
（automl_anomaly 的合成异常基准 + 评估器 + 稳定性）在 iforest/ocsvm
两族间轻量搜索。S4 门禁按 synthetic_auc 主键判定（hard_gates 的
REVERSE_GATE_KEYS 对 normal_fpr 做反向比较）。
"""

from __future__ import annotations

import numpy as np

from app.services.automl_anomaly import (
    ANOMALY_DEFAULT_CONTAMINATION,
    build_synthetic_benchmark,
    evaluate_anomaly_candidate,
    normalize_anomaly_contamination,
)
from app.services.automl_catalog import resolve_algorithm_families

# 目录族 id 与无监督白名单天然一致（M1 目录层互斥保证监督族不可见）。
_ANOMALY_HYPERPARAMS = {
    "iforest": {"n_estimators": 200, "max_samples": 512},
    "ocsvm": {"nu": 0.05, "kernel": "rbf", "gamma": "scale"},
}


def anomaly_trainer(feature_frame, _y, hints: dict) -> dict:
    """无监督 S3 验收训练：两族同台 + 合成异常基准评估，synthetic_auc 选优。

    签名与 lightweight_trainer 对齐（feature_frame, y, hints）——y 恒为
    None（无监督无标签），保留参数位只为调用点形状统一。
    hints：algorithm_whitelist（目录族 id 白名单，硬约束同监督侧）、
    contamination（guidance.modeling.contamination）、condition_column
    （分工况建模 §3.6：指定后按工况值切分数据分别建模，冠军取各工况
    最差检出能力——保证每个工况都可用；路由部署拓扑二期）。
    """
    import pandas as pd

    hints = dict(hints or {})
    contamination = normalize_anomaly_contamination(hints.get("contamination"))
    full_data = bool(hints.get("full_data", True))
    frame = feature_frame if isinstance(feature_frame, pd.DataFrame) else pd.DataFrame(feature_frame)
    condition_column = str(hints.get("condition_column") or "").strip() or None
    if condition_column and condition_column not in frame.columns:
        raise ValueError(f"condition column {condition_column} not in features")
    if condition_column:
        # 分工况切分（§3.6）：每工况独立走完整训练评估，冠军取「最差工况」
        # ——任何一个工况不达标即整体不达标（保守）。
        segments = []
        for value, segment in frame.groupby(condition_column, sort=True):
            feature_only = segment.drop(columns=[condition_column])
            if len(feature_only) >= 60:
                segments.append((f"{condition_column}={value}", feature_only))
        if not segments:
            raise ValueError("condition column produced no usable segments (each needs ≥60 rows)")
        segment_results = []
        for label, segment_frame in segments:
            result = _train_single(segment_frame, hints, contamination, full_data)
            result["segment"] = label
            result["data_fidelity"]["rows"] = int(len(segment_frame))
            segment_results.append(result)
        # 汇总冠军 = 各工况同一族配置下按最差 synthetic_auc 的族（各工况独立训练，
        # 输出每工况最佳与整体最差，验收按最差口径——任一工况不可用即整体不可用）
        worst = min(segment_results, key=lambda item: item["metrics"]["synthetic_auc"])
        aggregated = {
            "metrics": worst["metrics"],
            "topk_metrics": [
                {"synthetic_auc": item["metrics"]["synthetic_auc"]} for item in segment_results
            ],
            "importance": [],
            "minority_test_count": None,
            "data_fidelity": {
                "full_data": full_data, "paradigm": "unsupervised",
                "total_rows": int(len(frame)),
                "condition_column": condition_column,
                "segments": [item["segment"] for item in segment_results],
            },
            "contamination": contamination,
            "evaluation": {
                **(segment_results[0].get("evaluation") or {}),
                "per_condition": [
                    {"segment": item["segment"], "synthetic_auc": item["metrics"]["synthetic_auc"],
                     "normal_fpr": item["metrics"]["normal_fpr"]}
                    for item in segment_results
                ],
                "worst_segment": worst["segment"],
            },
            "champion_model": worst["champion_model"],
            "champion_features": worst["champion_features"],
            "champion_algorithm": worst["champion_algorithm"],
        }
        return aggregated
    return _train_single(frame, hints, contamination, full_data)


def _train_single(frame, hints: dict, contamination: float, full_data: bool) -> dict:
    """单段（全量或单工况）训练评估。"""
    import numpy as np
    import pandas as pd

    matrix = frame.to_numpy(dtype=float)
    fidelity: dict = {
        "full_data": full_data,
        "total_rows": int(len(matrix)),
        "paradigm": "unsupervised",
    }
    # 保护上限与监督侧同语义：关闭全量时 2 万行抽样（正常数据海量，
    # 抽样评估的合成基准统计量依然稳定）。
    if not full_data and len(matrix) > 20000:
        rng = np.random.default_rng(7)
        rows = np.sort(rng.choice(len(matrix), size=20000, replace=False))
        matrix = matrix[rows]
        fidelity["sampled_rows"] = int(len(matrix))
        fidelity["note"] = "non-full-data sampled training (20000 cap)"
    if len(matrix) < 40:
        raise ValueError("AutoML anomaly trainer requires at least 40 rows")

    families = resolve_algorithm_families(
        [str(x) for x in hints.get("algorithm_whitelist") or []] or None,
        task="anomaly_detection",
    )
    holdout_size = max(1, int(len(matrix) * 0.2))
    train_matrix, holdout_matrix = matrix[:-holdout_size], matrix[-holdout_size:]
    benchmark = build_synthetic_benchmark(train_matrix, holdout_matrix, random_seed=42)

    scored: list[dict] = []
    champion_result: dict | None = None
    for family in families:
        params = dict(_ANOMALY_HYPERPARAMS.get(family.id, {}))
        metrics = evaluate_anomaly_candidate(
            family.build("anomaly_detection", params),
            train_matrix,
            holdout_matrix,
            benchmark,
            contamination=contamination,
            random_seed=42,
            compute_stability=True,
        )
        scored.append({"algorithm": family.id, "synthetic_auc": float(metrics["synthetic_auc"])})
        if champion_result is None or float(metrics["synthetic_auc"]) > float(champion_result["synthetic_auc"]):
            champion_result = metrics
            champion_family = family
            champion_params = params

    assert champion_result is not None and champion_family is not None
    champion_model = champion_family.build("anomaly_detection", champion_params)
    champion_model.fit(train_matrix)
    metrics = {
        "synthetic_auc": round(float(champion_result["synthetic_auc"]), 4),
        "perturbation_recall": round(float(champion_result["perturbation_recall"]), 4),
        "normal_fpr": round(float(champion_result["normal_fpr"]), 4),
        "stability": round(float(champion_result.get("stability") or 0.0), 4),
    }
    result = {
        "metrics": metrics,
        "topk_metrics": [
            {"synthetic_auc": item["synthetic_auc"]} for item in scored
        ],
        # 无监督无传统重要性：M2 置空（泄漏进 top10 检查对空列表安全跳过），
        # 逐特征归因 top_contributors 在 M3 接线。
        "importance": [],
        "minority_test_count": None,
        "data_fidelity": fidelity,
        "contamination": contamination,
        "evaluation": {
            "acceptance_gates": champion_result.get("acceptance_gates"),
            "detection_recall_per_class": champion_result.get("detection_recall_per_class"),
            "threshold_score": champion_result.get("threshold_score"),
            "score_histograms": champion_result.get("score_histograms"),
            "synthetic_class_sizes": champion_result.get("synthetic_class_sizes"),
            "candidates": scored,
        },
        # 冠军模型运行时对象（进程内传给 runner；验收通过时物化为
        # anomaly joblib 工件——与监督侧 champion_model 同合同）
        "champion_model": champion_model,
        "champion_features": [str(name) for name in frame.columns],
        "champion_algorithm": champion_family.id,
    }
    return result
