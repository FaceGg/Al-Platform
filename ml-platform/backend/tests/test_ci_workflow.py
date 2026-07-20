import unittest
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
CI_WORKFLOW = REPOSITORY_ROOT / ".github" / "workflows" / "ci.yml"


class TestProductionIntegrationWorkflow(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workflow = CI_WORKFLOW.read_text(encoding="utf-8")

    def test_worker_startup_waits_for_ready_log_without_control_probe(self):
        wait_step = self.workflow.split(
            "- name: Wait for Celery worker",
            maxsplit=1,
        )[1].split("- name: Run production integration tests", maxsplit=1)[0]

        self.assertIn('grep -q " ready\\." "$RUNNER_TEMP/celery.log"', wait_step)
        self.assertNotIn("celery -A", wait_step)

    def test_failure_evidence_scan_uses_runner_available_grep(self):
        evidence_step = self.workflow.split(
            "- name: Scan and upload production failure evidence",
            maxsplit=1,
        )[1].split("- name: Upload production failure evidence", maxsplit=1)[0]

        self.assertIn("grep -Eni", evidence_step)
        self.assertNotIn("rg -n", evidence_step)


if __name__ == "__main__":
    unittest.main()
