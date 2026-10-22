"""profile_data tool tests (AutoML Agent plan, Task A1.4).

Contract under test (spec v0.9 §S1/§17.1): deterministic column-level profile
with Chinese-annotation splitting, target semantics, mutual-information Top-K,
high-correlation pairs, time-column detection and the egress-gated row samples
(off by default, masked sensitive columns when enabled).
"""

import json
import os
import unittest
from uuid import uuid4

os.environ.setdefault("LLM_MASTER_KEY", __import__(
    "cryptography.fernet", fromlist=["Fernet"]
).Fernet.generate_key().decode("ascii"))

import pandas as pd  # noqa: E402

import numpy as np  # noqa: E402

from app.services.agent.profile_data import profile_data  # noqa: E402


def _tightening_frame(n: int = 200) -> pd.DataFrame:
    torque = np.random.default_rng(42).normal(25.0, 1.5, n)
    target_torque = np.random.default_rng(7).normal(26.8, 0.3, n)
    margin_low = target_torque - 2.0
    # ~19% defective: torque drifting near/over the lower margin.
    defective = ((torque - margin_low) > -0.5).astype(int)
    frame = pd.DataFrame(
        {
            "ORDER_ID": [f"ORD-{i:05d}" for i in range(n)],
            "ACTUAL_TORQUE(实际扭矩)": torque,
            "TARGET_TORQUE(目标扭矩)": target_torque,
            "LOWER_MARGIN(下裕度)": margin_low,
            "TIGHTEN_TIME(拧紧时间)": pd.date_range("2026-01-01", periods=n, freq="min"),
            "STATION(工位)": np.random.default_rng(11).choice(["S1", "S2", "S3"], n),
        }
    )
    frame["CONSTANT_FLAG"] = 1
    frame.loc[frame.index[:10], "ACTUAL_TORQUE(实际扭矩)"] = None
    frame["DECIDE(判定结果)"] = defective
    frame["TORQUE_COPY"] = frame["ACTUAL_TORQUE(实际扭矩)"] * 2.0
    return frame


class TestProfileData(unittest.TestCase):
    def test_column_profile_with_annotation_split(self):
        report = profile_data(_tightening_frame(), target="DECIDE(判定结果)")
        by_name = {col["name"]: col for col in report["columns"]}
        torque = by_name["ACTUAL_TORQUE(实际扭矩)"]
        self.assertEqual(torque["base_name"], "ACTUAL_TORQUE")
        self.assertEqual(torque["semantic"], "实际扭矩")
        self.assertAlmostEqual(torque["missing_rate"], 10 / 200, places=3)
        self.assertTrue(by_name["CONSTANT_FLAG"]["constant"])
        self.assertFalse(torque["constant"])
        self.assertIn("quantiles", torque)
        station = by_name["STATION(工位)"]
        self.assertEqual(station["cardinality"], 3)

    def test_target_distribution_and_imbalance(self):
        report = profile_data(_tightening_frame(), target="DECIDE(判定结果)")
        target = report["target"]
        self.assertEqual(set(target["distribution"]), {"0", "1"})
        self.assertTrue(target["imbalance_ratio"] >= 1)
        self.assertIn("minority_label", target)
        self.assertIn("majority_label", target)

    def test_mutual_info_ranks_signal_column_first(self):
        report = profile_data(_tightening_frame(), target="DECIDE(判定结果)")
        top_columns = [item["column"] for item in report["mutual_info_top"][:3]]
        self.assertIn("ACTUAL_TORQUE(实际扭矩)", top_columns)
        self.assertNotIn(
            "ORDER_ID", [item["column"] for item in report["mutual_info_top"][:3]]
        )

    def test_high_correlation_pair_detected(self):
        report = profile_data(_tightening_frame(), target="DECIDE(判定结果)")
        pair_columns = {
            frozenset((pair["a"], pair["b"]))
            for pair in report["high_correlation_pairs"]
        }
        self.assertIn(
            frozenset(("ACTUAL_TORQUE(实际扭矩)", "TORQUE_COPY")), pair_columns
        )
        for pair in report["high_correlation_pairs"]:
            self.assertGreater(pair["corr"], 0.95)

    def test_time_column_detection(self):
        report = profile_data(_tightening_frame(), target="DECIDE(判定结果)")
        self.assertIn("TIGHTEN_TIME(拧紧时间)", report["time_columns"])

    def test_deterministic_two_runs_identical(self):
        frame = _tightening_frame()
        first = profile_data(frame, target="DECIDE(判定结果)")
        second = profile_data(frame, target="DECIDE(判定结果)")
        self.assertEqual(json.dumps(first, sort_keys=True), json.dumps(second, sort_keys=True))

    def test_row_samples_default_off_and_masked_when_enabled(self):
        frame = _tightening_frame()
        report = profile_data(frame, target="DECIDE(判定结果)")
        self.assertNotIn("row_samples", report)
        enabled = profile_data(
            frame,
            target="DECIDE(判定结果)",
            row_samples=True,
            sensitive_columns={"ORDER_ID"},
            sample_limit=5,
        )
        samples = enabled["row_samples"]
        self.assertEqual(len(samples), 5)
        self.assertEqual(samples[0]["ORDER_ID"], "***")

    def test_fullwidth_annotation_split(self):
        frame = pd.DataFrame(
            {
                "TORQUE（实际扭矩）": [1.0, 2.0, 3.0, 4.0],
                "OK(判定)": [0, 1, 0, 1],
            }
        )
        report = profile_data(frame, target="OK(判定)")
        by_name = {col["name"]: col for col in report["columns"]}
        self.assertEqual(by_name["TORQUE（实际扭矩）"]["base_name"], "TORQUE")
        self.assertEqual(by_name["TORQUE（实际扭矩）"]["semantic"], "实际扭矩")
