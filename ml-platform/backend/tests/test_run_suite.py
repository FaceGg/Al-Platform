import unittest

import run_suite


class TestRunSuite(unittest.TestCase):
    def test_module_timeout_covers_long_running_quality_api_suite(self):
        self.assertGreaterEqual(run_suite.MODULE_TIMEOUT_SECONDS, 180)


if __name__ == "__main__":
    unittest.main()
