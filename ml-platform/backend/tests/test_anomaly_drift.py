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


def test_refit_restores_false_positive_rate_after_drift():
    """判据⑤量化闭环（技术方案 §3.6/§4.2）：工况漂移 → 误报率飙升 →
    仅正常数据重拟合 → 误报率回落到 ≈污染率。

    三个阶段同一批「新工况正常数据」上量化对比：
    1. 旧模型+旧阈值：误报率远高于 contamination（漂移未治理）
    2. 重拟合剔除策略：按漂移数据自身分数剔除 top contamination（仅正常样本）
    3. 新模型+新阈值：误报率回落到 ≈contamination
    """
    from app.services.automl_anomaly import pipeline_anomaly_scores
    from app.services.automl_catalog import get_algorithm_family

    rng = np.random.default_rng(7)
    old_normal = rng.normal(size=(2000, 3))          # 训练期工况
    drifted_normal = rng.normal(loc=1.5, size=(1500, 3))  # 漂移后的新工况正常数据
    contamination = 0.01

    old_model = get_algorithm_family("iforest").build(
        "anomaly_detection", {"n_estimators": 100, "max_samples": 512},
    ).fit(old_normal)
    old_threshold = float(np.quantile(
        pipeline_anomaly_scores(old_model, old_normal), 1 - contamination,
    ))

    # 阶段 1：漂移数据打旧模型 → 误报率飙升
    drifted_scores_old = pipeline_anomaly_scores(old_model, drifted_normal)
    fpr_before = float(np.mean(drifted_scores_old >= old_threshold))
    assert fpr_before > contamination * 5, f"漂移应推高误报率，实测 {fpr_before}"

    # 阶段 2：仅正常数据重拟合（按漂移数据自身分数剔除 top contamination）
    ranked = np.sort(drifted_scores_old)
    cutoff = float(np.quantile(ranked, 1 - contamination))
    keep = drifted_normal[drifted_scores_old < cutoff]
    new_model = get_algorithm_family("iforest").build(
        "anomaly_detection", {"n_estimators": 100, "max_samples": 512},
    ).fit(keep)
    new_threshold = float(np.quantile(
        pipeline_anomaly_scores(new_model, keep), 1 - contamination,
    ))

    # 阶段 3：误报率回落——新模型+新阈值在「另一批新工况正常数据」上
    fresh_drifted_normal = rng.normal(loc=1.5, size=(1500, 3))
    fresh_scores_new = pipeline_anomaly_scores(new_model, fresh_drifted_normal)
    fpr_after = float(np.mean(fresh_scores_new >= new_threshold))
    assert fpr_after <= contamination * 3, f"重拟合后误报率应回落，实测 {fpr_after}"
    # 回落幅度：显著低于漂移未治理时的误报率
    assert fpr_after < fpr_before / 3
