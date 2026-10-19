"""Tests for utility operators (python_script, collect, macro, write_as_text).

These operators had no dedicated tests previously.
"""
import os
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest import mock

import pandas as pd

sys.path.insert(0, ".")

# Import via app.main to trigger operator registration
from app.main import app  # noqa: F401
from app.engine.registry import OperatorRegistry
from app.operators.utility_operators import (
    PYTHON_SCRIPT_FOOTER,
    PYTHON_SCRIPT_HEADER,
    PYTHON_SCRIPT_TEMPLATE,
)
from tests.operator_test_utils import execute_operator, operator_context


class TestExecutePythonRemoved(unittest.TestCase):
    """execute_python 是无沙箱的历史算子，已下线（安全：画布可执行任意代码）。
    存量工作流未使用（nodes/workflow_versions 均为 0），删除注册。"""

    def test_not_registered_anymore(self):
        self.assertIsNone(OperatorRegistry.get("execute_python"))


class TestPythonScriptOperator(unittest.TestCase):
    def test_registered_with_fixed_contract(self):
        op = OperatorRegistry.get("python_script")
        self.assertIsNotNone(op)
        self.assertEqual([port.name for port in op.inputs], ["data"])
        self.assertEqual([port.name for port in op.outputs], ["data"])
        self.assertEqual([param.name for param in op.parameters],
                         ["auto_install", "script"])
        auto_install = next(p for p in op.parameters if p.name == "auto_install")
        self.assertEqual(auto_install.type, "boolean")
        self.assertTrue(auto_install.default)

    def test_uses_df_and_result_without_configurable_variable_names(self):
        op = OperatorRegistry.get("python_script")
        outputs = execute_operator(
            op,
            {"data": [{"a": 1}, {"a": 2}]},
            {"script": "result = df.copy()\nresult['b'] = result['a'] * 2"},
        )
        self.assertEqual(outputs["data"], [{"a": 1, "b": 2}, {"a": 2, "b": 4}])

    def test_accepts_record_list_output(self):
        op = OperatorRegistry.get("python_script")
        outputs = execute_operator(
            op,
            {"data": [{"a": 1}]},
            {"script": "result = [{'b': df['a'].iloc[0] + 1}]"},
        )
        self.assertEqual(outputs["data"], [{"b": 2}])

    def test_template_is_the_script_default_and_is_runnable_shape(self):
        op = OperatorRegistry.get("python_script")
        script_param = next(p for p in op.parameters if p.name == "script")
        self.assertEqual(script_param.default, PYTHON_SCRIPT_TEMPLATE)
        self.assertTrue(PYTHON_SCRIPT_TEMPLATE.startswith(PYTHON_SCRIPT_HEADER))
        self.assertTrue(PYTHON_SCRIPT_TEMPLATE.rstrip().endswith(PYTHON_SCRIPT_FOOTER.rstrip()))

    def test_unmodified_template_passes_interface_check(self):
        """模板未改但功能区未写 result：接口校验通过，运行期提示补齐 result。"""
        op = OperatorRegistry.get("python_script")
        with self.assertRaises(RuntimeError) as ctx:
            execute_operator(op, {"data": [{"a": 1}]}, {"script": PYTHON_SCRIPT_TEMPLATE})
        self.assertIn("must assign output to 'result'", str(ctx.exception))

    def test_template_with_implementation_runs(self):
        script = (
            PYTHON_SCRIPT_HEADER + "\n"
            "result = df.copy()\n"
            "result['b'] = result['a'] * 2\n"
            + PYTHON_SCRIPT_FOOTER
        )
        op = OperatorRegistry.get("python_script")
        outputs = execute_operator(op, {"data": [{"a": 1}, {"a": 2}]}, {"script": script})
        self.assertEqual(outputs["data"], [{"a": 1, "b": 2}, {"a": 2, "b": 4}])

    def test_modified_input_interface_rejected(self):
        script = PYTHON_SCRIPT_TEMPLATE.replace("上游节点的输入数据表", "被我改掉的说明")
        op = OperatorRegistry.get("python_script")
        with self.assertRaises(RuntimeError) as ctx:
            execute_operator(op, {"data": [{"a": 1}]}, {"script": script})
        self.assertIn("输入/输出接口", str(ctx.exception))

    def test_modified_output_interface_rejected(self):
        script = PYTHON_SCRIPT_TEMPLATE.replace("平台自动传给下游", "随手一改")
        op = OperatorRegistry.get("python_script")
        with self.assertRaises(RuntimeError) as ctx:
            execute_operator(op, {"data": [{"a": 1}]}, {"script": script})
        self.assertIn("输入/输出接口", str(ctx.exception))

    def test_interface_only_touched_spaces_tolerated(self):
        """首尾空白不视为修改接口（模板尾部多敲回车不应拒绝运行）。"""
        script = PYTHON_SCRIPT_TEMPLATE + "\n\n"
        script = script.replace(
            "# TODO: 在此编写你的处理逻辑，例如：\n",
            "# TODO: 在此编写你的处理逻辑，例如：\nresult = df.copy()\n",
        )
        op = OperatorRegistry.get("python_script")
        outputs = execute_operator(op, {"data": [{"a": 1}]}, {"script": script})
        self.assertEqual(outputs["data"], [{"a": 1}])

    def test_auto_install_param_forwarded_to_runtime(self):
        op = OperatorRegistry.get("python_script")
        runtime = mock.Mock()
        runtime.execute.return_value = pd.DataFrame({"a": [1]})
        from app.operators import utility_operators as uo

        with mock.patch.object(uo, "_RUNTIME", runtime):
            outputs = execute_operator(
                op,
                {"data": [{"a": 1}]},
                {"script": "result = df.copy()", "auto_install": False},
            )
        self.assertEqual(outputs["data"], [{"a": 1}])
        _, kwargs = runtime.execute.call_args
        self.assertIs(kwargs.get("auto_install"), False)

    def test_allows_imports_in_subprocess(self):
        """子进程隔离后 import 放开：stdlib 直接可用，缺失库由运行时自动安装。"""
        op = OperatorRegistry.get("python_script")
        outputs = execute_operator(
            op,
            {"data": [{"a": 1}]},
            {"script": "import json\nimport math\nresult = df.copy()\n"
                       "result['b'] = float(json.loads(json.dumps(math.floor(3.9))))"},
        )
        self.assertEqual(outputs["data"], [{"a": 1.0, "b": 3.0}])

    def test_rejects_invalid_result_type(self):
        op = OperatorRegistry.get("python_script")
        with self.assertRaises(RuntimeError) as ctx:
            execute_operator(op, {"data": [{"a": 1}]}, {"script": "result = 123"})
        self.assertIn("result must be a pandas.DataFrame or a list of records",
                      str(ctx.exception))

    def test_propagates_script_exception_message(self):
        op = OperatorRegistry.get("python_script")
        with self.assertRaises(RuntimeError) as ctx:
            execute_operator(
                op,
                {"data": [{"a": 1}]},
                {"script": "result = df.copy()\nraise ValueError('boom')"},
            )
        self.assertIn("ValueError: boom", str(ctx.exception))

    def test_rejects_oversized_script_parameter(self):
        op = OperatorRegistry.get("python_script")
        with self.assertRaises(ValueError):
            execute_operator(op, {"data": [{"a": 1}]}, {"script": "x" * 100_001})


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
