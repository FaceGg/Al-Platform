import unittest
from pathlib import Path

import yaml


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
CI_WORKFLOW = REPOSITORY_ROOT / ".github" / "workflows" / "ci.yml"
COMPOSE_FILE = REPOSITORY_ROOT / "docker-compose.yml"


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

    def test_experiment_integration_declares_compose_required_runtime_secret(self):
        experiment_job = yaml.safe_load(self.workflow)["jobs"]["experiment-integration"]

        self.assertIn("INFERENCE_INTERNAL_SECRET", experiment_job["env"])

    def test_production_integration_declares_runtime_url_for_production_settings(self):
        production_job = yaml.safe_load(self.workflow)["jobs"]["production-integration"]

        self.assertIn("INFERENCE_RUNTIME_URL", production_job["env"])

    def test_compose_has_dedicated_celery_beat_scheduler(self):
        compose = yaml.safe_load(COMPOSE_FILE.read_text(encoding="utf-8"))
        scheduler = compose["services"]["scheduler"]
        self.assertIn("beat", " ".join(scheduler["command"]))
        self.assertEqual(scheduler["environment"], compose["services"]["worker"]["environment"])
        self.assertEqual(
            scheduler["depends_on"]["migrate"]["condition"],
            "service_completed_successfully",
        )
        self.assertEqual(scheduler["depends_on"]["redis"]["condition"], "service_healthy")

    def test_experiment_ci_starts_scheduler_service(self):
        parsed = yaml.safe_load(self.workflow)
        steps = parsed["jobs"]["experiment-integration"]["steps"]
        start = next(step for step in steps if step.get("name") == "Start production experiment stack")
        self.assertIn("scheduler", start["run"])

    def test_experiment_image_build_retries_transient_mirror_failures(self):
        parsed = yaml.safe_load(self.workflow)
        steps = parsed["jobs"]["experiment-integration"]["steps"]
        build = next(step for step in steps if step.get("name") == "Build experiment services")

        self.assertIn("for attempt in {1..3}", build["run"])
        self.assertIn(
            "if docker compose build backend worker tensorboard-gateway inference-runtime; then",
            build["run"],
        )
        self.assertIn("exit 1", build["run"])

    def test_compose_has_internal_non_root_inference_runtime(self):
        compose = yaml.safe_load(COMPOSE_FILE.read_text(encoding="utf-8"))
        runtime = compose["services"]["inference-runtime"]
        self.assertEqual(runtime["build"]["dockerfile"], "Dockerfile.inference")
        self.assertNotIn("ports", runtime)
        self.assertEqual(runtime["expose"], ["7000"])
        self.assertIn("INFERENCE_INTERNAL_SECRET", runtime["environment"])
        self.assertEqual(
            runtime["depends_on"]["minio-init"]["condition"],
            "service_completed_successfully",
        )
        self.assertEqual(
            compose["services"]["backend"]["depends_on"]["inference-runtime"]["condition"],
            "service_healthy",
        )

    def test_experiment_ci_builds_starts_and_verifies_inference_runtime(self):
        parsed = yaml.safe_load(self.workflow)
        steps = parsed["jobs"]["experiment-integration"]["steps"]
        build = next(step for step in steps if step.get("name") == "Build experiment services")
        start = next(step for step in steps if step.get("name") == "Start production experiment stack")
        verify = next(step for step in steps if step.get("name") == "Verify migrations and real experiment lifecycle")
        evidence = next(step for step in steps if step.get("name") == "Collect redacted experiment failure evidence")
        self.assertIn("inference-runtime", build["run"])
        self.assertIn("inference-runtime", start["run"])
        self.assertIn("RUN_INFERENCE_INTEGRATION=1", verify["run"])
        self.assertIn("tests.test_inference_production_stack", verify["run"])
        self.assertIn("inference-runtime", evidence["run"])
        self.assertIn("ci-inference-internal-secret", evidence["run"])


if __name__ == "__main__":
    unittest.main()
