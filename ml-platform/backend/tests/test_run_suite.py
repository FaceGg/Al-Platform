import contextlib
import io
import os
import subprocess
import sys
import unittest
from unittest.mock import patch

import run_suite


class TestRunSuite(unittest.TestCase):
    def test_module_timeout_covers_long_running_quality_api_suite(self):
        self.assertGreaterEqual(run_suite.MODULE_TIMEOUT_SECONDS, 180)

    def test_detects_pytest_style_modules_and_keeps_unittest_modules(self):
        self.assertEqual(
            run_suite.detect_test_framework("test_annotation_strategies"),
            "pytest",
        )
        self.assertEqual(
            run_suite.detect_test_framework("test_celery_workflows"),
            "unittest",
        )

    def test_builds_framework_specific_command(self):
        pytest_command = run_suite.build_test_command("test_annotation_strategies")
        self.assertEqual(pytest_command[:3], [run_suite.sys.executable, "-m", "pytest"])
        self.assertEqual(pytest_command[-2:], ["tests/test_annotation_strategies.py", "-q"])

        unittest_command = run_suite.build_test_command("test_celery_workflows")
        self.assertEqual(
            unittest_command,
            [run_suite.sys.executable, "-m", "unittest", "tests.test_celery_workflows", "-v"],
        )

    def test_zero_test_output_is_not_counted_as_success(self):
        self.assertTrue(run_suite.has_zero_tests("Ran 0 tests in 0.000s\n\nNO TESTS RAN"))
        self.assertTrue(run_suite.has_zero_tests("================ no tests ran ================"))
        self.assertFalse(run_suite.has_zero_tests("Ran 3 tests in 0.100s\n\nOK"))

    def test_run_modules_marks_zero_test_success_as_failure(self):
        completed = run_suite.subprocess.CompletedProcess(
            args=["fake"],
            returncode=0,
            stdout="Ran 0 tests in 0.000s\n\nNO TESTS RAN",
            stderr="",
        )
        with patch.object(run_suite, "detect_test_framework", return_value="unittest"), patch.object(
            run_suite.subprocess, "run", return_value=completed
        ) as run:
            # 吞掉夹具回显：run_modules 会把模拟输出逐行打印，若不重定向，
            # CI 日志会出现假的 ">>> test_fake: FAILED / NO TESTS RAN"，
            # 曾被误读为真实套件失败（测试卫生批次，run 41428207476 等日志佐证）
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(run_suite.run_modules(["test_fake"]), 1)
        run.assert_called_once()

    def test_run_modules_uses_outer_unittest_summary_after_nested_zero_test_output(self):
        completed = run_suite.subprocess.CompletedProcess(
            args=["fake"],
            returncode=0,
            stdout=(
                "nested runner output\n"
                "Ran 0 tests in 0.000s\n\n"
                "NO TESTS RAN\n"
                "Ran 1 test in 0.010s\n\n"
                "OK\n"
            ),
            stderr="",
        )
        with patch.object(run_suite, "detect_test_framework", return_value="unittest"), patch.object(
            run_suite.subprocess, "run", return_value=completed
        ):
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(run_suite.run_modules(["test_fake"]), 0)

    def test_child_output_is_decoded_as_utf8_with_replace(self):
        """父进程必须按 UTF-8 容错解码子进程输出，且子进程 stdout 固定 UTF-8。

        ``text=True`` 会用 locale 代码页解码子进程输出（CI 的 Windows runner
        为 cp1252）——子进程写出的 UTF-8 中文字节里含 cp1252 **未定义字节**
        （0x81/0x8D/0x8F/0x90/0x9D）→ 父进程 UnicodeDecodeError 直接崩掉整轮，
        且没有任何模块级细节（2026-11-14 CI Quality (windows-latest) 的同款风险）。
        """
        completed = run_suite.subprocess.CompletedProcess(
            args=["fake"],
            returncode=0,
            stdout="Ran 1 test in 0.010s\n\nOK\n",
            stderr="",
        )
        with patch.object(run_suite, "detect_test_framework", return_value="unittest"), patch.object(
            run_suite.subprocess, "run", return_value=completed
        ) as run:
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(run_suite.run_modules(["test_fake"]), 0)
        kwargs = run.call_args.kwargs
        self.assertEqual(kwargs.get("encoding"), "utf-8")
        self.assertEqual(kwargs.get("errors"), "replace")
        # text=True 与 encoding 不能同时给（subprocess 会 ValueError）
        self.assertNotIn("text", kwargs)
        env = kwargs.get("env") or {}
        self.assertEqual(env.get("PYTHONIOENCODING"), "utf-8")

    def test_main_switches_own_stdout_to_utf8(self):
        """run_suite 必须把**自己**的 stdout 切到 UTF-8。

        run_suite 会把子进程输出原样回显（含中文测试名）。Windows 上 stdout
        被重定向到管道时用 locale 代码页（CI runner = cp1252）且 errors=strict
        → print(中文) 直接 UnicodeEncodeError，崩掉**整个 harness**——表现为
        「Run backend suite」失败且**无模块级汇总**（2026-11-14 CI
        Quality (windows-latest) 的真实根因）。

        本用例把「stdout 是 cp1252」显式化（``PYTHONIOENCODING=cp1252``），
        使回归在任何宿主 locale 下都可复现。
        """
        script = (
            "import run_suite, sys\n"
            "run_suite.run_modules = lambda modules: ("
            "print('ENCODING=' + (sys.stdout.encoding or '?')), 0)[1]\n"
            "sys.argv = ['run_suite.py', '--week', '1']\n"
            "raise SystemExit(run_suite.main())\n"
        )
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "cp1252"
        env["PYTHONPATH"] = str(run_suite.BACKEND_DIR)
        completed = subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True,
            cwd=str(run_suite.BACKEND_DIR),
            env=env,
            timeout=300,
        )
        stdout = completed.stdout.decode("utf-8", "replace")
        stderr = completed.stderr.decode("utf-8", "replace")
        self.assertNotIn("UnicodeEncodeError", stdout + stderr)
        self.assertIn("ENCODING=utf-8", stdout, stderr[-2000:])

    def test_pytest_is_an_explicit_backend_test_dependency(self):
        requirements = (run_suite.Path(run_suite.BACKEND_DIR) / "requirements.txt").read_text(
            encoding="utf-8",
        )
        self.assertRegex(requirements, r"(?m)^pytest==")


if __name__ == "__main__":
    unittest.main()
