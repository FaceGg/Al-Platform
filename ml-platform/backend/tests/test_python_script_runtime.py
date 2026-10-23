"""Tests for the python_script subprocess runtime (import auto-install)."""

import os
import sys
import unittest
from unittest import mock

import pandas as pd

from app.services.python_script_runtime import (
    MODULE_TO_PACKAGE,
    PythonScriptRuntime,
    collect_import_modules,
    distribution_names,
)


class TestCollectImportModules(unittest.TestCase):
    def test_collects_top_level_modules(self):
        script = (
            "import pandas as pd\n"
            "import numpy\n"
            "from sklearn.metrics import roc_auc_score\n"
            "from x.y.z import w\n"
        )
        self.assertEqual(
            collect_import_modules(script),
            ["numpy", "pandas", "sklearn", "x"],
        )

    def test_excludes_relative_and_future_imports(self):
        script = "from __future__ import annotations\nfrom . import sibling\nresult = df"
        self.assertEqual(collect_import_modules(script), [])

    def test_collects_function_level_imports(self):
        script = "def helper():\n    import cv2\n    return cv2\nresult = df"
        self.assertEqual(collect_import_modules(script), ["cv2"])


class TestDistributionNames(unittest.TestCase):
    def test_maps_import_names_to_distributions(self):
        self.assertEqual(
            distribution_names(["cv2", "sklearn", "PIL"]),
            ["opencv-python", "pillow", "scikit-learn"],
        )

    def test_unknown_modules_pass_through(self):
        self.assertEqual(distribution_names(["umap"]), ["umap"])

    def test_every_mapping_value_is_valid_package_name(self):
        import re

        pattern = re.compile(r"^[A-Za-z][A-Za-z0-9._-]*$")
        for module, package in MODULE_TO_PACKAGE.items():
            self.assertTrue(
                pattern.match(str(package)),
                f"mapping for {module} is not a safe pip name: {package!r}",
            )

    def test_rejects_unsafe_names(self):
        with self.assertRaises(ValueError):
            distribution_names(["pkg; rm -rf /"])
        with self.assertRaises(ValueError):
            distribution_names(["pkg>=2.0"])


class TestRuntimeSubprocessExecution(unittest.TestCase):
    """Interpreter-mode runtime (empty venv_dir): tests need no venv bootstrap."""

    def setUp(self):
        self.runtime = PythonScriptRuntime(venv_dir="", auto_install=False)

    def test_dataframe_roundtrip(self):
        df = pd.DataFrame({"a": [1, 2], "b": ["x", "y"]})
        result = self.runtime.execute("result = df.copy()\nresult['c'] = result['a'] * 2", df)
        self.assertEqual(result["c"].tolist(), [2, 4])

    def test_record_list_output(self):
        df = pd.DataFrame({"a": [7]})
        result = self.runtime.execute("result = [{'v': int(df['a'].iloc[0]) + 1}]", df)
        self.assertIsInstance(result, pd.DataFrame)
        self.assertEqual(result["v"].tolist(), [8])

    def test_main_guard_style_script(self):
        """正规脚本写法（import + 函数 + if __name__ == "__main__"）受支持。"""
        df = pd.DataFrame({"a": [1, 2]})
        script = (
            "import pandas as pd\n"
            "\n"
            "def process(d: pd.DataFrame) -> pd.DataFrame:\n"
            "    out = d.copy()\n"
            "    out['b'] = out['a'] * 10\n"
            "    return out\n"
            "\n"
            "if __name__ == \"__main__\":\n"
            "    result = process(df)\n"
        )
        result = self.runtime.execute(script, df)
        self.assertEqual(result["b"].tolist(), [10, 20])

    def test_script_exception_is_wrapped(self):
        df = pd.DataFrame({"a": [1]})
        with self.assertRaises(RuntimeError) as ctx:
            self.runtime.execute("result = df.copy()\nraise ValueError('boom')", df)
        self.assertIn("ValueError: boom", str(ctx.exception))

    def test_missing_result_is_reported(self):
        df = pd.DataFrame({"a": [1]})
        with self.assertRaises(RuntimeError) as ctx:
            self.runtime.execute("x = 1", df)
        self.assertIn("must assign output to 'result'", str(ctx.exception))

    def test_invalid_result_type_is_reported(self):
        df = pd.DataFrame({"a": [1]})
        with self.assertRaises(RuntimeError) as ctx:
            self.runtime.execute("result = 123", df)
        self.assertIn("result must be a pandas.DataFrame", str(ctx.exception))

    def test_execution_timeout(self):
        runtime = PythonScriptRuntime(venv_dir="", auto_install=False, exec_timeout=1)
        df = pd.DataFrame({"a": [1]})
        with self.assertRaises(RuntimeError) as ctx:
            runtime.execute("while True:\n    pass", df)
        self.assertIn("timed out after 1s", str(ctx.exception))

    def test_missing_package_error_surfaces(self):
        df = pd.DataFrame({"a": [1]})
        with self.assertRaises(RuntimeError) as ctx:
            self.runtime.execute("import definitely_not_installed_xyz\nresult = df", df)
        self.assertIn("ModuleNotFoundError", str(ctx.exception))


class TestAutoInstallFlow(unittest.TestCase):
    """venv-mode resolution with the subprocess layer mocked out."""

    def _runtime(self, **kwargs):
        runtime = PythonScriptRuntime(venv_dir="/tmp/fake-venv", **kwargs)
        return runtime

    def test_installs_missing_mapped_packages(self):
        runtime = self._runtime()
        calls = []

        with mock.patch.object(runtime, "_ensure_venv", return_value="/tmp/fake-venv/bin/python"), \
             mock.patch.object(runtime, "_probe_missing", return_value=["cv2"]) as probe, \
             mock.patch.object(runtime, "_pip_install", side_effect=lambda _, pkgs: calls.append(pkgs)):
            interpreter = runtime._resolve_interpreter("import cv2\nimport os\nresult = df")

        self.assertEqual(interpreter, "/tmp/fake-venv/bin/python")
        # stdlib 'os' never reaches the probe; only the missing 'cv2' does.
        probe.assert_called_once_with("/tmp/fake-venv/bin/python", ["cv2"])
        self.assertEqual(calls, [["opencv-python"]])

    def test_skips_install_when_nothing_missing(self):
        runtime = self._runtime()
        with mock.patch.object(runtime, "_ensure_venv", return_value="/tmp/fake-venv/bin/python"), \
             mock.patch.object(runtime, "_probe_missing", return_value=[]), \
             mock.patch.object(runtime, "_pip_install") as install:
            runtime._resolve_interpreter("import pandas\nresult = df")
        install.assert_not_called()

    def test_skips_install_when_disabled(self):
        runtime = self._runtime(auto_install=False)
        with mock.patch.object(runtime, "_ensure_venv", return_value="/tmp/fake-venv/bin/python"), \
             mock.patch.object(runtime, "_probe_missing") as probe, \
             mock.patch.object(runtime, "_pip_install") as install:
            interpreter = runtime._resolve_interpreter("import cv2\nresult = df")
        self.assertEqual(interpreter, "/tmp/fake-venv/bin/python")
        probe.assert_not_called()
        install.assert_not_called()

    def test_interpreter_mode_never_installs(self):
        runtime = PythonScriptRuntime(venv_dir="", auto_install=True)
        with mock.patch.object(runtime, "_probe_missing") as probe, \
             mock.patch.object(runtime, "_pip_install") as install:
            self.assertEqual(runtime._resolve_interpreter("import anything\nresult = df"),
                             sys.executable)
        probe.assert_not_called()
        install.assert_not_called()


if __name__ == "__main__":
    unittest.main()
