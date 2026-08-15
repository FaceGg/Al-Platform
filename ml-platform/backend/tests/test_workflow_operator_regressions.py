"""Regression coverage for workflow operator configuration failures."""
import sys
import tempfile
import unittest
from pathlib import Path

import pandas as pd

sys.path.insert(0, ".")

from app.main import app  # noqa: F401 - registers built-in operators
from app.engine.registry import OperatorRegistry
from app.engine.operator_contract import OperatorContext
from app.engine.export_paths import resolve_export_path
from tests.operator_test_utils import execute_operator


class TestJoinRequirements(unittest.TestCase):
    def test_join_rejects_blank_key_pairs_before_merging(self):
        join = OperatorRegistry.get("join")

        with self.assertRaisesRegex(ValueError, "Join key pairs are required"):
            execute_operator(
                join,
                {"left": [{"id": 1}], "right": [{"id": 1}]},
                {"left_keys": "", "right_keys": ""},
            )

    def test_join_rejects_persisted_blank_key_slots(self):
        join = OperatorRegistry.get("join")

        with self.assertRaisesRegex(ValueError, "Join key pairs are required"):
            execute_operator(
                join,
                {"left": [{"plant": "A"}], "right": [{"site": "A"}]},
                {"left_keys": "plant,", "right_keys": "site,"},
            )

    def test_join_rejects_different_key_pair_counts(self):
        join = OperatorRegistry.get("join")

        with self.assertRaisesRegex(ValueError, "count mismatch"):
            execute_operator(
                join,
                {"left": [{"plant": "A"}], "right": [{"site": "A", "line": "L1"}]},
                {"left_keys": "plant", "right_keys": "site,line"},
            )


class TestExcelAndExportSettings(unittest.TestCase):
    def test_read_excel_supports_sheet_row_column_and_limit_options(self):
        read_excel = OperatorRegistry.get("read_excel")
        with tempfile.TemporaryDirectory() as directory:
            workbook = Path(directory) / "input.xlsx"
            with pd.ExcelWriter(workbook) as writer:
                pd.DataFrame([
                    {"id": 1, "value": 10, "ignored": "a"},
                    {"id": 2, "value": 20, "ignored": "b"},
                ]).to_excel(writer, sheet_name="Data", index=False, startrow=1)

            result = execute_operator(read_excel, {}, {
                "file_path": str(workbook),
                "sheet_name": "Data",
                "header_row": 0,
                "skiprows": 1,
                "usecols": "A:B",
                "nrows": 1,
            })

        self.assertEqual(result["data"], [{"id": 1, "value": 10}])

    def test_unnamed_export_defaults_to_context_workspace(self):
        with tempfile.TemporaryDirectory() as directory:
            context = OperatorContext(
                run_id="run-1",
                node_id="node-1",
                project_id="project-1",
                artifact_service=None,
                cancel_requested=lambda: False,
                logger=object(),
                workspace_dir=Path(directory),
            )

            path = resolve_export_path(context, "csv_export", "", "csv")

        self.assertEqual(path.name, "csv_export_node-1.csv")
        self.assertIn("exports", path.parts)


if __name__ == "__main__":
    unittest.main()
