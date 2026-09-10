"""Run backend test modules individually with isolated storage."""

import argparse
import ast
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

from tests.week_manifest import (
    ALL_TEST_MODULES,
    DEPRECATED_TEST_MODULES,
    WEEK_TEST_MODULES,
)


BACKEND_DIR = os.path.dirname(__file__)
PROJECT_DIR = os.path.dirname(os.path.dirname(BACKEND_DIR))
MODULE_TIMEOUT_SECONDS = 300
TESTS_DIR = Path(BACKEND_DIR) / "tests"


def _test_module_path(module: str) -> Path:
    """Resolve a manifest module to a file inside the backend test directory."""
    candidate = (TESTS_DIR / f"{module}.py").resolve()
    tests_root = TESTS_DIR.resolve()
    if tests_root not in candidate.parents:
        raise ValueError(f"test module escapes test directory: {module}")
    return candidate


def _uses_pytest(tree: ast.AST) -> bool:
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            if any(alias.name == "pytest" or alias.name.startswith("pytest.") for alias in node.names):
                return True
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if module == "pytest" or module.startswith("pytest."):
                return True

    # Pytest-style modules commonly expose top-level test functions, while
    # unittest modules keep test methods inside TestCase classes.
    return any(
        isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name.startswith("test_")
        for node in tree.body
    )


def detect_test_framework(module: str) -> str:
    """Return the runner required to execute a manifest test module."""
    path = _test_module_path(module)
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (OSError, SyntaxError):
        # Let the selected subprocess report missing/invalid source with its
        # normal diagnostics instead of hiding the original failure here.
        return "unittest"
    return "pytest" if _uses_pytest(tree) else "unittest"


def build_test_command(module: str, framework: str | None = None) -> list[str]:
    """Build a command that executes one module with its native test runner."""
    selected = framework or detect_test_framework(module)
    if selected == "pytest":
        return [sys.executable, "-m", "pytest", f"tests/{module}.py", "-q"]
    if selected == "unittest":
        return [sys.executable, "-m", "unittest", f"tests.{module}", "-v"]
    raise ValueError(f"unsupported test framework: {selected}")


def has_zero_tests(output: str, framework: str | None = None) -> bool:
    """Detect when the target runner's final summary executed no tests."""
    normalized = output.lower()

    if framework == "unittest":
        summaries = re.findall(r"\bran\s+(\d+)\s+tests?\b", normalized)
        if summaries:
            return int(summaries[-1]) == 0

    return any(
        re.search(pattern, normalized)
        for pattern in (
            r"\bran\s+0\s+tests?\b",
            r"\bno\s+tests?\s+ran\b",
            r"\bcollected\s+0\s+items?\b",
        )
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--week",
        type=int,
        choices=sorted(WEEK_TEST_MODULES),
        help="Run only the test modules owned by one development week.",
    )
    parser.add_argument(
        "--include-deprecated",
        action="store_true",
        help="Include historical point-weld-quality AutoML tests excluded from default acceptance.",
    )
    return parser.parse_args()


def run_modules(test_modules: list[str]) -> int:
    test_root = os.path.join(
        PROJECT_DIR,
        "temp_test",
        "test-suite",
        str(int(time.time())),
    )
    os.makedirs(test_root, exist_ok=True)

    passed = 0
    failed = 0
    errors: list[str] = []

    try:
        for module in test_modules:
            db_path = os.path.join(test_root, f"test_{module}.db")
            artifact_dir = os.path.join(test_root, f"artifacts_{module}")
            system_temp_dir = os.path.join(test_root, f"system_{module}")
            os.makedirs(system_temp_dir, exist_ok=True)
            env = os.environ.copy()
            env["DATABASE_URL"] = f"sqlite:///{db_path}"
            env["ARTIFACT_STORAGE_DIR"] = artifact_dir
            env["ML_PLATFORM_TEMP_DIR"] = os.path.join(test_root, f"data_{module}")
            env["TEMP"] = system_temp_dir
            env["TMP"] = system_temp_dir
            env["TMPDIR"] = system_temp_dir
            env["PYTHONPATH"] = BACKEND_DIR

            print(f"\n{'=' * 60}")
            print(f"  RUNNING: {module}")
            print(f"  DB: {db_path}")
            print(f"{'=' * 60}")

            framework = detect_test_framework(module)
            command = build_test_command(module, framework)
            print(f"  FRAMEWORK: {framework}")
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                cwd=BACKEND_DIR,
                env=env,
                timeout=MODULE_TIMEOUT_SECONDS,
            )

            combined_output = f"{result.stdout}\n{result.stderr}"
            zero_tests = has_zero_tests(combined_output, framework)
            lines = combined_output.splitlines()
            for line in lines:
                line_upper = line.upper()
                if line.strip() and any(marker in line_upper for marker in ("...", "FAIL", "ERROR", "RAN ", "OK", "PASSED", "SKIPPED", "NO TESTS")):
                    print(f"  {line}")

            if result.returncode == 0 and not zero_tests:
                passed += 1
                print(f"  >>> {module}: PASSED")
                continue

            failed += 1
            errors.append(module)
            print(f"  >>> {module}: FAILED")
            if zero_tests:
                print("  STDERR: test runner reported zero collected tests")
            if result.stdout.strip():
                print("  STDOUT:")
                for output_line in result.stdout.rstrip().splitlines():
                    print(f"    {output_line}")
            if result.stderr.strip():
                print("  STDERR:")
                for error_line in result.stderr.rstrip().splitlines():
                    print(f"    {error_line}")
    finally:
        shutil.rmtree(test_root, ignore_errors=True)

    print(f"\n{'=' * 60}")
    print(f"  RESULTS: {passed} passed, {failed} failed out of {passed + failed} modules")
    if errors:
        print(f"  Failed modules: {', '.join(errors)}")
    print(f"{'=' * 60}")
    return 0 if failed == 0 else 1


def main() -> int:
    args = parse_args()
    if args.week:
        modules = list(WEEK_TEST_MODULES[args.week])
    else:
        modules = list(ALL_TEST_MODULES)
    if not args.include_deprecated:
        modules = [module for module in modules if module not in DEPRECATED_TEST_MODULES]
    if args.week:
        print(f"Running Week {args.week} acceptance suite ({len(modules)} modules).")
    else:
        print(f"Running complete active acceptance suite ({len(modules)} modules).")
    if args.include_deprecated:
        print("Including deprecated point-weld-quality AutoML tests.")
    return run_modules(modules)


if __name__ == "__main__":
    raise SystemExit(main())
