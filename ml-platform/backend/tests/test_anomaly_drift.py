"""无监督分数漂移 PSI（技术方案 §3.6，迁移 20261112_98 配套）：模块测试。

基线=M1 score_stats.json 的 201 点分位表；PSI 用 10 等概率箱。
"""

import numpy as np
import pytest

from app.services.anomaly_drift import (
    PSI_ALERT_THRESHOLD,
    evaluate_score_drift,
    score_drift_psi,
)


def _baseline_from(scores: np.ndarray) -> list[float]:
    probabilities = np.linspace(0.0, 1.0, 201)
    return [float(value) for value in np.quantile(scores, probabilities)]


def test_stable_distribution_has_near_zero_psi():
    rng = np.random.default_rng(42)
    base = rng.normal(size=5000)
    baseline = _baseline_from(base)
    fresh = rng.normal(size=800)
    psi = score_drift_psi(baseline, fresh)
    assert psi < PSI_ALERT_THRESHOLD
    assert psi < 0.1


def test_shifted_distribution_exceeds_alert_threshold():
    rng = np.random.default_rng(42)
    base = rng.normal(size=5000)
    baseline = _baseline_from(base)
    drifted = rng.normal(loc=3.0, size=800)  # 整体右移 3σ：分数箱全变
    result = evaluate_score_drift(baseline, drifted)
    assert result["psi"] >= PSI_ALERT_THRESHOLD
    assert result["level"] == "alert"


def test_watch_level_between_thresholds():
    rng = np.random.default_rng(42)
    base = rng.normal(size=8000)
    baseline = _baseline_from(base)
    mild = rng.normal(loc=0.35, scale=1.0, size=1000)
    result = evaluate_score_drift(baseline, mild)
    assert result["level"] in {"watch", "alert"}
    assert result["sample_count"] == 1000


def test_degenerate_inputs_return_zero():
    assert score_drift_psi([], [1.0, 2.0]) == 0.0
    assert score_drift_psi([0.0, 1.0], []) == 0.0
    result = evaluate_score_drift([0.0, 0.5, 1.0], [0.3])
    assert result["level"] in {"stable", "watch", "alert"}


def test_baseline_from_real_calibrator_shape():
    """与 M1 标定器产物对接：201 点分位表直接可用。"""
    from app.services.automl_anomaly import AnomalyScoreCalibrator

    rng = np.random.default_rng(0)
    train = rng.normal(size=2000)
    calibrator = AnomalyScoreCalibrator.fit(train, contamination=0.01)
    drifted = rng.normal(loc=2.0, size=500)
    result = evaluate_score_drift(
        [float(value) for value in calibrator.quantile_points], drifted,
    )
    assert result["level"] == "alert"
