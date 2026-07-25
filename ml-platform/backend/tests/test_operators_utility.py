"""Tests for utility operators (execute_python, collect, macro, write_as_text).

These operators had no dedicated tests previously.
"""
import os
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, ".")

# Import via app.main to trigger operator registration
from app.main import app  # noqa: F401
from app.engine.registry import OperatorRegistry
from tests.operator_test_utils import execute_operator, operator_context


class TestExecutePythonOperator(unittest.TestCase):
    """Tests for the execute_python operator."""

    def test_registered(self):
        op = OperatorRegistry.get("execute_python")
        self.assertIsNotNone(op)
        self.assertEqual(op.category, "utility")

    def test_runs_script_and_returns_dataframe_output(self):
        op = OperatorRegistry.get("execute_python")
        inputs = {"data": [{"a": 1}, {"a": 2}]}
        params = {
            "script": "result = data.copy()\nresult['b'] = result['a'] * 2",
            "input_var": "data",
            "output_var": "result",
        }
        outputs = execute_operator(op, inputs, params)
        self.assertEqual(outputs["data"], [{"a": 1, "b": 2}, {"a": 2, "b": 4}])

    def test_custom_variable_names(self):
        op = OperatorRegistry.get("execute_python")
        inputs = {"data": [{"x": 10}]}
        params = {
            # input_var is exposed as a DataFrame, so use DataFrame operations.
            "script": "out = inp.copy(); out['x'] = out['x'] + 5",
            "input_var": "inp",
            "output_var": "out",
        }
        outputs = execute_operator(op, inputs, params)
        self.assertEqual(outputs["data"], [{"x": 15}])

    def test_falls_back_to_input_when_output_var_missing(self):
        op = OperatorRegistry.get("execute_python")
        # output_var defaults to "result"; if script doesn't define it, falls back to df
        inputs = {"data": [{"a": 1}]}
        params = {"script": "pass", "input_var": "data", "output_var": "result"}
        outputs = execute_operator(op, inputs, params)
        self.assertEqual(outputs["data"], [{"a": 1}])

    def test_script_error_wrapped_as_runtime_error(self):
        op = OperatorRegistry.get("execute_python")
        inputs = {"data": [{"a": 1}]}
        params = {"script": "raise ValueError('boom')"}
        with self.assertRaises(RuntimeError) as ctx:
            execute_operator(op, inputs, params)
        self.assertIn("ExecutePython script error", str(ctx.exception))

    def test_invalid_output_type_raises_type_error(self):
        op = OperatorRegistry.get("execute_python")
        inputs = {"data": [{"a": 1}]}
        params = {"script": "result = 123"}
        with self.assertRaises(TypeError):
            execute_operator(op, inputs, params)


class TestCollectOperator(unittest.TestCase):
    """Tests for the collect operator."""

    def test_registered(self):
        op = OperatorRegistry.get("collect")
        self.assertIsNotNone(op)
        self.assertEqual(op.category, "utility")

    def test_concatenates_multiple_inputs(self):
        op = OperatorRegistry.get("collect")
        inputs = {
            "data1": [{"a": 1}, {"a": 2}],
            "data2": [{"a": 3}],
            "data3": [],
            "data4": [{"a": 4}],
        }
        outputs = execute_operator(op, inputs, {})
        self.assertEqual(outputs["collection"], [{"a": 1}, {"a": 2}, {"a": 3}, {"a": 4}])

    def test_returns_empty_when_no_inputs(self):
        op = OperatorRegistry.get("collect")
        outputs = execute_operator(op, {"data1": [], "data2": []}, {})
        self.assertEqual(outputs["collection"], [])


class TestMacroOperator(unittest.TestCase):
    """Tests for the macro operator."""

    def test_registered(self):
        op = OperatorRegistry.get("macro")
        self.assertIsNotNone(op)
        self.assertEqual(op.category, "utility")

    def test_passthrough_data(self):
        op = OperatorRegistry.get("macro")
        inputs = {"input": [{"x": 1}]}
        params = {"macro_name": "rate", "macro_value": "0.95"}
        outputs = execute_operator(op, inputs, params)
        self.assertEqual(outputs["output"], [{"x": 1}])
        self.assertEqual(outputs["macro_name"], "rate")
        self.assertEqual(outputs["macro_value"], "0.95")
        # The macro name/value pair is also added under the macro name.
        self.assertEqual(outputs["rate"], "0.95")

    def test_empty_macro_name(self):
        op = OperatorRegistry.get("macro")
        inputs = {"input": [{"x": 1}]}
        params = {"macro_name": "", "macro_value": ""}
        outputs = execute_operator(op, inputs, params)
        self.assertEqual(outputs["output"], [{"x": 1}])
        self.assertNotIn("rate", outputs)


class TestWriteAsTextOperator(unittest.TestCase):
    """Tests for the write_as_text operator."""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_registered(self):
        op = OperatorRegistry.get("write_as_text")
        self.assertIsNotNone(op)
        self.assertEqual(op.category, "utility")

    def test_writes_text_file_and_passes_data_through(self):
        op = OperatorRegistry.get("write_as_text")
        path = os.path.join(self.tmpdir.name, "out.txt")
        inputs = {"data": [{"a": 1}, {"a": 2}]}
        params = {"file_path": path, "format": "text"}
        outputs = execute_operator(op, inputs, params)
        self.assertEqual(outputs["data"], [{"a": 1}, {"a": 2}])
        self.assertTrue(Path(path).is_file())
        content = Path(path).read_text(encoding="utf-8")
        self.assertIn("Rows: 2", content)

    def test_writes_json_file(self):
        op = OperatorRegistry.get("write_as_text")
        path = os.path.join(self.tmpdir.name, "sub", "out.json")
        inputs = {"data": [{"a": 1}]}
        params = {"file_path": path, "format": "json"}
        execute_operator(op, inputs, params)
        self.assertTrue(Path(path).is_file())
        # pandas to_json(orient="records", indent=2) emits "a":1 with no space
        self.assertIn('"a":1', Path(path).read_text(encoding="utf-8"))

    def test_writes_csv_file(self):
        op = OperatorRegistry.get("write_as_text")
        path = os.path.join(self.tmpdir.name, "out.csv")
        inputs = {"data": [{"a": 1, "b": 2}]}
        params = {"file_path": path, "format": "csv"}
        execute_operator(op, inputs, params)
        content = Path(path).read_text(encoding="utf-8")
        self.assertIn("a,b", content)

    def test_empty_file_path_uses_workspace_export_default(self):
        op = OperatorRegistry.get("write_as_text")
        context = replace(operator_context(), workspace_dir=Path(self.tmpdir.name))
        op.execute(context, {"data": [{"a": 1}]}, {"file_path": "", "format": "text"})

        path = Path(self.tmpdir.name) / "exports" / "write_as_text_test-node.txt"
        self.assertTrue(path.is_file())
        self.assertIn("Rows: 1", path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
