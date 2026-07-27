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
            'if docker compose --project-name "$COMPOSE_PROJECT_NAME" build backend worker tensorboard-gateway inference-runtime; then',
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

    def test_inference_lifecycle_compose_settings_cover_runtime_and_workers(self):
        compose = yaml.safe_load(COMPOSE_FILE.read_text(encoding="utf-8"))
        expected_settings = {
            "INFERENCE_RUNTIME_URL",
            "INFERENCE_INTERNAL_SECRET",
            "INFERENCE_RATE_LIMIT_CAPACITY",
            "INFERENCE_RATE_LIMIT_REFILL_PER_SECOND",
            "INFERENCE_ROLLOUT_OBSERVATION_SECONDS",
        }

        for service_name in ("backend", "worker", "scheduler", "inference-runtime"):
            with self.subTest(service=service_name):
                self.assertTrue(
                    expected_settings.issubset(compose["services"][service_name]["environment"]),
                )

    def test_inference_lifecycle_ci_uses_an_isolated_compose_project(self):
        parsed = yaml.safe_load(self.workflow)
        job = parsed["jobs"]["experiment-integration"]
        project_name = job["env"].get("COMPOSE_PROJECT_NAME", "")
        self.assertIn("ci-inference-", project_name)
        self.assertIn("INFERENCE_RATE_LIMIT_CAPACITY", job["env"])
        self.assertIn("INFERENCE_RATE_LIMIT_REFILL_PER_SECOND", job["env"])
        self.assertIn("INFERENCE_ROLLOUT_OBSERVATION_SECONDS", job["env"])

        steps = job["steps"]
        start = next(step for step in steps if step.get("name") == "Start production experiment stack")
        verify = next(step for step in steps if step.get("name") == "Verify migrations and real experiment lifecycle")
        stop = next(step for step in steps if step.get("name") == "Stop production experiment stack")

        self.assertIn('docker compose --project-name "$COMPOSE_PROJECT_NAME"', start["run"])
        self.assertIn("20260720_09_production_inference", verify["run"])
        self.assertIn("TestInferenceProductionStack", verify["run"])
        self.assertIn("TestInferenceProductionRedisOutage", verify["run"])
        self.assertIn("stop redis inference-runtime", verify["run"])
        self.assertIn("down --volumes --remove-orphans", stop["run"])

    def test_inference_lifecycle_failure_evidence_scans_raw_logs_before_redaction(self):
        parsed = yaml.safe_load(self.workflow)
        steps = parsed["jobs"]["experiment-integration"]["steps"]
        evidence = next(step for step in steps if step.get("name") == "Collect redacted experiment failure evidence")
        upload = next(step for step in steps if step.get("name") == "Upload experiment failure evidence")
        evidence_script = evidence["run"]

        self.assertIn("INFERENCE_EVIDENCE_RAW", evidence_script)
        self.assertIn("INFERENCE_EVIDENCE_REDACTED", evidence_script)
        self.assertIn("trap cleanup_experiment_evidence EXIT", evidence_script)
        cleanup_start = evidence_script.index("cleanup_experiment_evidence()")
        cleanup_end = evidence_script.index("}", cleanup_start)
        cleanup_body = evidence_script[cleanup_start:cleanup_end]
        self.assertIn(
            'rm -rf "$INFERENCE_EVIDENCE_RAW" "$INFERENCE_EVIDENCE_REDACTED"',
            cleanup_body,
        )
        self.assertIn(
            'docker compose --project-name "$COMPOSE_PROJECT_NAME" ps > "$INFERENCE_EVIDENCE_RAW/compose-ps.txt" 2>&1 || true',
            evidence_script,
        )
        self.assertIn(
            'docker compose --project-name "$COMPOSE_PROJECT_NAME" logs --no-color backend worker scheduler mlflow tensorboard-gateway inference-runtime migrate > "$INFERENCE_EVIDENCE_RAW/services.log" 2>&1 || true',
            evidence_script,
        )
        self.assertIn(
            'grep -REal \'ci-postgres-password|ci-minio-root-password|ci-experiment-secret-key|ci-tensorboard-session-secret|ci-inference-internal-secret\' "$INFERENCE_EVIDENCE_RAW"',
            evidence_script,
        )
        self.assertIn(
            'grep -REal \'mli_[A-Za-z0-9_-]+\' "$INFERENCE_EVIDENCE_RAW"',
            evidence_script,
        )
        self.assertIn(
            'grep -RFl -- "$INFERENCE_CREATED_TEST_KEY" "$INFERENCE_EVIDENCE_RAW"',
            evidence_script,
        )
        self.assertIn('cp "$INFERENCE_EVIDENCE_RAW"/* "$INFERENCE_EVIDENCE_REDACTED"/', evidence_script)
        self.assertIn('"$INFERENCE_EVIDENCE_REDACTED"/*', evidence_script)
        self.assertIn('rm -rf "$INFERENCE_EVIDENCE_RAW" "$INFERENCE_EVIDENCE_REDACTED"', evidence_script)
        self.assertIn('rm -rf "$INFERENCE_EVIDENCE_RAW"', evidence_script)
        self.assertIn("trap - EXIT", evidence_script)
        self.assertEqual(upload["with"]["path"], "${{ runner.temp }}/experiment-evidence")

        raw_capture_index = evidence_script.index("INFERENCE_EVIDENCE_RAW")
        ps_capture_index = evidence_script.index(
            'docker compose --project-name "$COMPOSE_PROJECT_NAME" ps > "$INFERENCE_EVIDENCE_RAW/compose-ps.txt"',
        )
        logs_capture_index = evidence_script.index(
            'docker compose --project-name "$COMPOSE_PROJECT_NAME" logs --no-color backend worker scheduler mlflow tensorboard-gateway inference-runtime migrate > "$INFERENCE_EVIDENCE_RAW/services.log"',
        )
        configured_secret_scan_index = evidence_script.index("grep -REal")
        mli_token_scan_index = evidence_script.index(
            'grep -REal \'mli_[A-Za-z0-9_-]+\' "$INFERENCE_EVIDENCE_RAW"',
        )
        created_key_scan_index = evidence_script.index("grep -RFl")
        copy_index = evidence_script.index('cp "$INFERENCE_EVIDENCE_RAW"/*')
        redaction_index = evidence_script.index("sed -i")
        raw_cleanup_index = evidence_script.rindex('rm -rf "$INFERENCE_EVIDENCE_RAW"')
        trap_remove_index = evidence_script.index("trap - EXIT")

        self.assertLess(raw_capture_index, configured_secret_scan_index)
        self.assertLess(ps_capture_index, configured_secret_scan_index)
        self.assertLess(logs_capture_index, configured_secret_scan_index)
        self.assertLess(ps_capture_index, mli_token_scan_index)
        self.assertLess(logs_capture_index, mli_token_scan_index)
        self.assertLess(configured_secret_scan_index, copy_index)
        self.assertLess(mli_token_scan_index, copy_index)
        self.assertLess(created_key_scan_index, copy_index)
        self.assertLess(copy_index, redaction_index)
        self.assertLess(redaction_index, raw_cleanup_index)
        self.assertLess(raw_cleanup_index, trap_remove_index)
        self.assertLess(steps.index(evidence), steps.index(upload))
        self.assertIn("ci-inference-internal-secret", evidence_script)
        self.assertIn("INFERENCE_INTEGRATION_CONTEXT_PATH", evidence_script)


if __name__ == "__main__":
    unittest.main()
