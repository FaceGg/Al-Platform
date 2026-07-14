import tempfile
import unittest
import json
import subprocess
import sys
from pathlib import Path

import pandas as pd

from app.services.weld_demo_service import WeldDemoPreparationError, WeldDemoService
from tools.prepare_weld_demo import run


class TestWeldDemoService(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.source = self.root / "source"
        self.source.mkdir()
        identities = {
            "Car Body": [0, 0, 1, 1],
            "Welding Spot": [0, 1, 0, 1],
            "Date": ["2023-06-13"] * 4,
        }
        pd.DataFrame({**identities, "Fault": [0, 1, 0, 1]}).to_csv(
            self.source / "labels.csv", index=False,
        )
        for signal, values in {
            "Current": [[0, 1, 2], [0, 0, 3], [1, 1, 1], [0, 2, 0]],
            "Voltage": [[1, 2, 3], [0, 4, 4], [2, 2, 2], [0, 1, 0]],
            "Force": [[2, 2, 0], [0, 5, 5], [3, 3, 3], [1, 0, 0]],
        }.items():
            frame = pd.DataFrame(identities)
            for index in range(3):
                frame[f"{signal} T-{index}"] = [row[index] for row in values]
            frame.to_csv(self.source / f"{signal.lower()}.csv", index=False)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_prepare_extracts_deterministic_features_and_metadata(self):
        output = self.root / "demo" / "features.csv"

        first = WeldDemoService().prepare(self.source, output)
        first_bytes = output.read_bytes()
        second = WeldDemoService().prepare(self.source, output)

        self.assertEqual(first.row_count, 4)
        self.assertEqual(first.class_distribution, {"0": 2, "1": 2})
        self.assertEqual(first.source_hashes, second.source_hashes)
        self.assertEqual(first_bytes, output.read_bytes())
        self.assertIn("current_mean", first.columns)
        self.assertIn("voltage_peak_position", first.columns)
        self.assertIn("force_non_zero_ratio", first.columns)
        self.assertEqual(first.columns[-1], "Fault")
        prepared = pd.read_csv(output)
        self.assertEqual(prepared.loc[0, "current_peak_value"], 2)
        self.assertEqual(prepared.loc[0, "current_non_zero_count"], 2)

    def test_prepare_rejects_row_identity_mismatch_without_output(self):
        current = pd.read_csv(self.source / "current.csv")
        current.loc[1, "Welding Spot"] = 99
        current.to_csv(self.source / "current.csv", index=False)
        output = self.root / "features.csv"

        with self.assertRaisesRegex(WeldDemoPreparationError, "WELD_DATA_IDENTITY_MISMATCH"):
            WeldDemoService().prepare(self.source, output)

        self.assertFalse(output.exists())

    def test_prepare_rejects_non_binary_fault(self):
        labels = pd.read_csv(self.source / "labels.csv")
        labels.loc[0, "Fault"] = 2
        labels.to_csv(self.source / "labels.csv", index=False)

        with self.assertRaisesRegex(WeldDemoPreparationError, "WELD_DATA_FAULT_INVALID"):
            WeldDemoService().prepare(self.source, self.root / "features.csv")

    def test_cli_run_returns_machine_readable_summary(self):
        output = self.root / "features.csv"

        summary = json.loads(run(["--source-dir", str(self.source), "--output", str(output)]))

        self.assertEqual(summary["row_count"], 4)
        self.assertEqual(summary["class_distribution"], {"0": 2, "1": 2})
        self.assertEqual(Path(summary["output_path"]), output.resolve())

    def test_cli_script_runs_from_backend_directory(self):
        output = self.root / "script-features.csv"
        backend_dir = Path(__file__).resolve().parents[1]

        completed = subprocess.run(
            [sys.executable, "tools/prepare_weld_demo.py", "--source-dir", str(self.source),
             "--output", str(output)],
            cwd=backend_dir, capture_output=True, text=True,
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(json.loads(completed.stdout)["row_count"], 4)


if __name__ == "__main__":
    unittest.main()
