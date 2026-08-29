"""Regression contract for the standalone Week 11 CI runner."""

from pathlib import Path
import unittest


class Week11RunnerContractTests(unittest.TestCase):
    def test_regenerated_notification_key_is_readable_by_runtime_user(self):
        root = Path(__file__).resolve().parents[3]
        runner = root / "ml-platform" / "backend" / "tools" / "acceptance" / "run_week11_acceptance.sh"
        content = runner.read_text(encoding="utf-8")

        self.assertIn('chown 1000:1000 "$NOTIFICATION_CRYPTO_SECRET_FILE"', content)
        self.assertIn('chmod 0400 "$NOTIFICATION_CRYPTO_SECRET_FILE"', content)


if __name__ == "__main__":
    unittest.main()
