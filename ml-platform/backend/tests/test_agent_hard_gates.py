"""S4 hard-gate tests (AutoML Agent plan, Task A2.3)."""

import os
import unittest
from uuid import uuid4

os.environ.setdefault("LLM_MASTER_KEY", __import__(
    "cryptography.fernet", fromlist=["Fernet"]
).Fernet.generate_key().decode("ascii"))

from app.services.agent.hard_gates import evaluate_hard_gates  # noqa: E402


class TestHardGates(unittest.TestCase):
    def test_all_gates_pass(self):
        report = evaluate_hard_gates(
            {"recall_minority": 0.94, "f1": 0.90},
            gates={"recall_minority": 0.90, "f1": 0.85},
            topk_metrics=[{"recall_minority": 0.94}, {"recall_minority": 0.93}],
            importance=[{"feature": "TORQUE_DEVIATION", "importance": 0.6}],
            leakage_columns=["DECIDE_ONE"],
        )
        self.assertTrue(report.passed)
        self.assertEqual(report.failures, [])

    def test_below_threshold_vetoes(self):
        report = evaluate_hard_gates(
            {"recall_minority": 0.55},
            gates={"recall_minority": 0.90},
        )
        self.assertFalse(report.passed)
        self.assertTrue(any("gate_failed" in item for item in report.failures))

    def test_missing_metric_is_a_failure(self):
        report = evaluate_hard_gates(
            {"recall_minority": 0.95},
            gates={"recall_minority": 0.90, "auc": 0.9},
        )
        self.assertFalse(report.passed)
        self.assertTrue(any("metric_missing: auc" in item for item in report.failures))

    def test_topk_variance_guard(self):
        report = evaluate_hard_gates(
            {"recall_minority": 0.95},
            gates={},
            topk_metrics=[{"recall_minority": 0.95}, {"recall_minority": 0.50}],
        )
        self.assertFalse(report.passed)
        self.assertTrue(any("topk_variance_high" in item for item in report.failures))

    def test_topk_variance_adaptive_noise_floor(self):
        # n=50 少数类测试样本：召回粒度 0.02，噪声底 2σ≈0.075；
        # 同档候选的稳定高原（std=0.025）不应被零容差基线误杀。
        report = evaluate_hard_gates(
            {"recall_minority": 0.95},
            gates={},
            topk_metrics=[{"recall_minority": 0.95}, {"recall_minority": 0.90}],
            minority_test_count=50,
        )
        self.assertTrue(report.passed)
        self.assertEqual(report.failures, [])

    def test_topk_variance_adaptive_floor_never_below_base(self):
        # 大 n 时噪声底退回 0.02 基线，自适应不放松门禁。
        report = evaluate_hard_gates(
            {"recall_minority": 0.95},
            gates={},
            topk_metrics=[{"recall_minority": 0.95}, {"recall_minority": 0.90}],
            minority_test_count=5000,
        )
        self.assertFalse(report.passed)
        self.assertTrue(any("topk_variance_high" in item for item in report.failures))

    def test_topk_variance_excludes_unqualified_candidates(self):
        # 点焊 9:1 实测场景：树家族 ~1.0、logistic ~0.7（std=0.14 必炸）；
        # 被主指标门禁淘汰的候选不参与冠军稳定性投票。
        report = evaluate_hard_gates(
            {"recall_minority": 1.0},
            gates={"recall_minority": 0.9},
            topk_metrics=[
                {"recall_minority": 1.0},
                {"recall_minority": 0.91},
                {"recall_minority": 0.70},
            ],
            minority_test_count=50,
        )
        self.assertTrue(report.passed)
        self.assertEqual(report.failures, [])

    def test_topk_variance_single_qualified_candidate_skips_guard(self):
        # 只剩冠军一个合格候选时无从衡量稳定性，跳过方差门禁；
        # 冠军自身的指标门禁仍独立生效（下一用例的 gate_failed 路径）。
        report = evaluate_hard_gates(
            {"recall_minority": 1.0},
            gates={"recall_minority": 0.9},
            topk_metrics=[
                {"recall_minority": 1.0},
                {"recall_minority": 0.70},
                {"recall_minority": 0.60},
            ],
        )
        self.assertTrue(report.passed)
        self.assertEqual(report.failures, [])

    def test_leakage_in_top_importance_vetoes(self):
        report = evaluate_hard_gates(
            {"recall_minority": 0.95},
            gates={},
            importance=[
                {"feature": "DECIDE_ONE", "importance": 0.9},
                {"feature": "ACTUAL_TORQUE", "importance": 0.1},
            ],
            leakage_columns=["DECIDE_ONE"],
        )
        self.assertFalse(report.passed)
        self.assertTrue(any("leakage_in_top10" in item for item in report.failures))

    def test_leakage_outside_top10_is_not_a_gate_failure(self):
        importance = [{"feature": f"f{i}", "importance": 0.1} for i in range(10)]
        importance.append({"feature": "DECIDE_ONE", "importance": 0.01})
        report = evaluate_hard_gates(
            {"recall_minority": 0.95},
            gates={},
            importance=importance,
            leakage_columns=["DECIDE_ONE"],
        )
        self.assertTrue(report.passed)

    def test_reverse_gate_normal_fpr_uses_lower_is_better_direction(self):
        """无监督反向门禁（技术方案 §3.3）：normal_fpr 超阈值一票否决。"""
        report = evaluate_hard_gates(
            {"synthetic_auc": 0.92, "normal_fpr": 0.30, "stability": 0.9},
            gates={"synthetic_auc": 0.85, "normal_fpr": 0.015, "stability": 0.8},
            primary_metric="synthetic_auc",
        )
        self.assertFalse(report.passed)
        self.assertTrue(any("normal_fpr=0.3000 > 0.015" in item for item in report.failures))

    def test_reverse_gate_normal_fpr_within_threshold_passes(self):
        report = evaluate_hard_gates(
            {"synthetic_auc": 0.92, "normal_fpr": 0.01, "stability": 0.9},
            gates={"synthetic_auc": 0.85, "normal_fpr": 0.015, "stability": 0.8},
            topk_metrics=[{"synthetic_auc": 0.92}, {"synthetic_auc": 0.90}],
            primary_metric="synthetic_auc",
            topk_max_variance=0.05,
        )
        self.assertTrue(report.passed, report.failures)

    def test_anomaly_default_gates_reject_low_synthetic_auc(self):
        report = evaluate_hard_gates(
            {"synthetic_auc": 0.60, "normal_fpr": 0.01, "stability": 0.9},
            gates={"synthetic_auc": 0.85, "normal_fpr": 0.015, "stability": 0.8},
            topk_metrics=[{"synthetic_auc": 0.60}, {"synthetic_auc": 0.58}],
            primary_metric="synthetic_auc",
            topk_max_variance=0.05,
        )
        self.assertFalse(report.passed)
        self.assertTrue(any("synthetic_auc" in item for item in report.failures))
