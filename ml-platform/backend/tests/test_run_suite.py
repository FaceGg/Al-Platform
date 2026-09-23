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
            self.assertEqual(run_suite.run_modules(["test_fake"]), 0)

    def test_pytest_is_an_explicit_backend_test_dependency(self):
        requirements = (run_suite.Path(run_suite.BACKEND_DIR) / "requirements.txt").read_text(
            encoding="utf-8",
        )
        self.assertRegex(requirements, r"(?m)^pytest==")


if __name__ == "__main__":
    unittest.main()
