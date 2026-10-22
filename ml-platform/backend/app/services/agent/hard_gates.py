"""S4 hard gates (spec v0.9 §三 S4): deterministic, one-vote-veto, and the
LLM review can never relax them — the runner consults this module's verdict
before any LLM sees the numbers, and a gate failure bypasses acceptance no
matter what the review says.
"""

from __future__ import annotations

from dataclasses import dataclass, field

PRIMARY_METRIC = "recall_minority"
TOPK_MAX_VARIANCE = 0.02
IMPORTANCE_TOP_N = 10


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
) -> GateReport:
    """Check minority-class gates, champion stability, and leakage leakage.

    ``metrics``  — e.g. {"recall_minority": 0.94, "f1": 0.88, "auc": 0.97}
    ``gates``    — user/recipe thresholds, same keys as metrics
    ``topk_metrics`` — per-candidate metric dicts for the variance guard
    ``importance``   — [{"feature": name, "importance": value}, ...] ranked
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
        if len(primary_values) >= 2:
            mean = sum(primary_values) / len(primary_values)
            variance = sum((value - mean) ** 2 for value in primary_values) / len(
                primary_values
            )
            if variance**0.5 > topk_max_variance:
                failures.append(
                    f"topk_variance_high: std={variance**0.5:.4f} > {topk_max_variance}"
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
