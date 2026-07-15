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


if __name__ == "__main__":
    unittest.main()
