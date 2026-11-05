"""S4 hard gates (spec v0.9 §三 S4): deterministic, one-vote-veto, and the
LLM review can never relax them — the runner consults this module's verdict
before any LLM sees the numbers, and a gate failure bypasses acceptance no
matter what the review says.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

PRIMARY_METRIC = "recall_minority"
TOPK_MAX_VARIANCE = 0.02
IMPORTANCE_TOP_N = 10
# 采样噪声底倍数：n 个少数类测试样本下同一模型的二项召回波动
# σ≈√(p̄(1-p̄)/n)，阈值随 2σ 抬升但永不低于 TOPK_MAX_VARIANCE。
NOISE_FLOOR_MULTIPLIER = 2.0


@dataclass
class GateReport:
    passed: bool
    failures: list[str] = field(default_factory=list)


def evaluate_hard_gates(
    metrics: dict,
    *,
    gates: dict,
    topk_metrics: list[dict] | None = None,
    importance: list[dict] | None = None,
    leakage_columns: list[str] | None = None,
    primary_metric: str = PRIMARY_METRIC,
    topk_max_variance: float = TOPK_MAX_VARIANCE,
    minority_test_count: int | None = None,
) -> GateReport:
    """Check minority-class gates, champion stability, and leakage leakage.

    ``metrics``  — e.g. {"recall_minority": 0.94, "f1": 0.88, "auc": 0.97}
    ``gates``    — user/recipe thresholds, same keys as metrics
    ``topk_metrics`` — per-candidate metric dicts for the variance guard
    ``importance``   — [{"feature": name, "importance": value}, ...] ranked
    ``minority_test_count`` — 测试集少数类样本数，用于方差门禁的采样噪声底：
        召回粒度是 1/n（n≈50 时一个样本即 0.02，固定 0.02 等价零容差），
        阈值抬升为 max(基线, 2σ) 且只在合格候选间衡量（见下方过滤）。
    """
    failures: list[str] = []

    for key, threshold in (gates or {}).items():
        if key not in metrics or metrics[key] is None:
            failures.append(f"metric_missing: {key}")
            continue
        value = float(metrics[key])
        if value < float(threshold):
            failures.append(f"gate_failed: {key}={value:.4f} < {threshold}")

    if topk_metrics and len(topk_metrics) >= 2:
        primary_values = [
            float(item[primary_metric])
            for item in topk_metrics
            if item.get(primary_metric) is not None
        ]
        # 冠军稳定性只在"有资格的竞争者"之间衡量：被主指标门禁淘汰的候选
        # （如不平衡数据上天然落后的线性家族）分歧是预期行为而非风险信号，
        # 不参与方差投票。
        primary_gate = (gates or {}).get(primary_metric)
        if primary_gate is not None:
            qualified = [
                value
                for value in primary_values
                if value >= float(primary_gate)
            ]
        else:
            qualified = list(primary_values)
        if len(qualified) >= 2:
            mean = sum(qualified) / len(qualified)
            variance = sum((value - mean) ** 2 for value in qualified) / len(
                qualified
            )
            limit = float(topk_max_variance)
            if minority_test_count and minority_test_count >= 2:
                noise_floor = NOISE_FLOOR_MULTIPLIER * math.sqrt(
                    max(mean * (1.0 - mean), 0.0) / minority_test_count
                )
                limit = max(limit, noise_floor)
            if variance**0.5 > limit:
                failures.append(
                    f"topk_variance_high: std={variance**0.5:.4f} > {limit:.4f}"
                    f" (qualified {len(qualified)}/{len(primary_values)},"
                    f" n_minority_test={minority_test_count})"
                )

    if importance and leakage_columns:
        leakage = {str(name) for name in leakage_columns}
        top_names = {
            str(item.get("feature"))
            for item in importance[:IMPORTANCE_TOP_N]
        }
        hits = sorted(leakage & top_names)
        if hits:
            failures.append(f"leakage_in_top{IMPORTANCE_TOP_N}: {','.join(hits)}")

    return GateReport(passed=not failures, failures=failures)
