import os
import subprocess
import sys
import unittest
from pathlib import Path

from tests.week_manifest import WEEK_TEST_MODULES


class TestSuiteManifest(unittest.TestCase):
    def test_every_backend_test_module_has_one_week_owner(self):
        test_dir = Path(__file__).parent
        discovered = {
            path.stem for path in test_dir.glob("test_*.py")
        }
        assigned = [module for modules in WEEK_TEST_MODULES.values() for module in modules]

        self.assertEqual(len(assigned), len(set(assigned)), "A test module is assigned to multiple weeks")
        self.assertEqual(discovered, set(assigned))

    def test_production_inference_stack_is_explicitly_gated_without_opt_in(self):
        environment = os.environ.copy()
        environment.pop("RUN_INFERENCE_INTEGRATION", None)
        backend_root = Path(__file__).resolve().parents[1]
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "unittest",
                "tests.test_inference_production_stack",
                "-v",
            ],
            cwd=backend_root,
            env=environment,
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("production inference integration disabled", result.stderr)
        self.assertIn("skipped", result.stderr)


if __name__ == "__main__":
    unittest.main()
