"""无监督分数漂移检测（技术方案 §3.6）：回流分数分布 PSI 对训练基线。

分数分布漂移比单特征漂移更早发现模型失配（先于误报显性化）。基线来自
M1 训练产物 ``score_stats.json``（201 点经验分位表）；PSI 用 10 等概率箱
（基线分位表插值出 11 个分位点），小样本回流下统计稳健。
"""

from __future__ import annotations

import numpy as np

# 方案 §3.6：PSI > 0.25 触发重拟合预警；0.10-0.25 观察级。
PSI_ALERT_THRESHOLD = 0.25
PSI_WATCH_THRESHOLD = 0.10
PSI_BIN_COUNT = 10


def score_drift_psi(baseline_quantile_points: list[float], scores) -> float:
    """回流分数对训练期分位表的 PSI（10 等概率箱，期望各 10%）。

    ``baseline_quantile_points`` 是 M1 标定器的 201 点分位表
    （probabilities=linspace(0,1,201)）；按等概率插值出 11 个箱边界。
    退化防御：箱占比为 0 时以 1e-6 下限参与对数（漂移记满该箱贡献），
    输入不足 1 个分数时返回 0.0（无数据=无漂移证据）。
    """
    points = np.asarray(baseline_quantile_points, dtype=float)
    values = np.asarray(scores, dtype=float)
    if points.size < 2 or values.size < 1:
        return 0.0
    probabilities = np.linspace(0.0, 1.0, points.size)
    box_edges = np.interp(
        np.linspace(0.0, 1.0, PSI_BIN_COUNT + 1),
        probabilities,
        points,
    )
    # np.histogram 的箱是左开右闭，但分数与边界相等的取整行为会抖动；
    # searchsorted 内侧归属保证「等于边界的点归更高箱」，与训练期
    # quantile 语义（>= threshold 判异常）一致。
    indexes = np.searchsorted(box_edges, values, side="right") - 1
    indexes = np.clip(indexes, 0, PSI_BIN_COUNT - 1)
    counts = np.bincount(indexes, minlength=PSI_BIN_COUNT)
    expected = 1.0 / PSI_BIN_COUNT
    total = float(values.size)
    psi = 0.0
    for count in counts:
        actual = max(count / total, 1e-6)
        psi += (actual - expected) * float(np.log(actual / expected))
    return float(psi)


def evaluate_score_drift(baseline_quantile_points: list[float], scores) -> dict[str, object]:
    """PSI 评估结果：触发/观察两级判定（重拟合预警的依据）。"""
    psi = score_drift_psi(baseline_quantile_points, scores)
    return {
        "psi": round(psi, 4),
        "level": (
            "alert" if psi >= PSI_ALERT_THRESHOLD
            else "watch" if psi >= PSI_WATCH_THRESHOLD
            else "stable"
        ),
        "alert_threshold": PSI_ALERT_THRESHOLD,
        "watch_threshold": PSI_WATCH_THRESHOLD,
        "sample_count": int(np.asarray(scores, dtype=float).size),
    }
