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
