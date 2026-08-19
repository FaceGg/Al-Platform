"""Run backend test modules individually with isolated storage."""

import argparse
import os
import shutil
import subprocess
import sys
import time

from tests.week_manifest import (
    ALL_TEST_MODULES,
    DEPRECATED_TEST_MODULES,
    WEEK_TEST_MODULES,
)


BACKEND_DIR = os.path.dirname(__file__)
PROJECT_DIR = os.path.dirname(os.path.dirname(BACKEND_DIR))
MODULE_TIMEOUT_SECONDS = 300


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

            result = subprocess.run(
                [sys.executable, "-m", "unittest", f"tests.{module}", "-v"],
                capture_output=True,
                text=True,
                cwd=BACKEND_DIR,
                env=env,
                timeout=MODULE_TIMEOUT_SECONDS,
            )

            lines = result.stdout.splitlines()
            for line in lines:
                if line.strip() and any(
                    marker in line
                    for marker in ("...", "FAIL", "ERROR", "Ran ", "OK", "FAILED")
                ):
                    print(f"  {line}")

            if result.returncode == 0:
                passed += 1
                print(f"  >>> {module}: PASSED")
                continue

            failed += 1
            errors.append(module)
            print(f"  >>> {module}: FAILED")
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
