import json
import unittest
from pathlib import Path

import yaml


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
CI_WORKFLOW = REPOSITORY_ROOT / ".github" / "workflows" / "ci.yml"
COMPOSE_FILE = REPOSITORY_ROOT / "docker-compose.yml"
ACCEPTANCE_COMPOSE_FILE = REPOSITORY_ROOT / "docker-compose.acceptance.yml"
FRONTEND_DOCKERFILE = REPOSITORY_ROOT / "ml-platform" / "frontend" / "Dockerfile"
NPM_AUDIT_EXCEPTION = (
    REPOSITORY_ROOT / "docs" / "security" / "react-router-rsc-mode-exception.json"
)
PIP_AUDIT_EXCEPTION = (
    REPOSITORY_ROOT / "docs" / "security" / "cryptography-pkcs7-mlflow-exception.json"
)
PRODUCTION_INFRASTRUCTURE = (
    REPOSITORY_ROOT / "docs" / "delivery" / "PRODUCTION_INFRASTRUCTURE.md"
)
USER_GUIDE = REPOSITORY_ROOT / "docs" / "delivery" / "USER_GUIDE.md"
PLATFORM_STATUS = REPOSITORY_ROOT / "PLATFORM_STATUS.md"
NOTIFICATION_STACK_TEST = (
    REPOSITORY_ROOT / "ml-platform" / "backend" / "tests" / "test_notification_production_stack.py"
)
BACKEND_REQUIREMENTS = REPOSITORY_ROOT / "ml-platform" / "backend" / "requirements.txt"


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

    def test_python_security_stack_uses_skinny_mlflow_and_fixed_cryptography_without_exception(self):
        requirements = BACKEND_REQUIREMENTS.read_text(encoding="utf-8")
        self.assertIn("cryptography==50.0.*", requirements)
        self.assertIn("mlflow-skinny==3.15.*", requirements)
        self.assertNotIn("mlflow==3.15.*", requirements)

        security_job = yaml.safe_load(self.workflow)["jobs"]["week11-12-verification"]
        rendered_steps = "\n".join(str(step.get("run", "")) for step in security_job["steps"])
        self.assertNotIn("--pip-audit-exception", rendered_steps)
        self.assertFalse(PIP_AUDIT_EXCEPTION.exists())

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

    def test_notification_stack_uses_a_secret_file_and_isolates_controlled_mailpit(self):
        compose = yaml.safe_load(COMPOSE_FILE.read_text(encoding="utf-8"))
        secret = compose["secrets"]["notification_master_key"]
        self.assertIn("file", secret)
        self.assertNotIn("NOTIFICATION_MASTER_KEY", str(secret))

        for service_name in ("migrate", "backend", "worker", "scheduler", "inference-runtime"):
            with self.subTest(service=service_name):
                service = compose["services"][service_name]
                self.assertEqual(
                    service["environment"]["NOTIFICATION_MASTER_KEY_FILE"],
                    "/run/secrets/notification_master_key",
                )
                self.assertIn("notification_master_key", service["secrets"])

        self.assertNotIn("mailpit", compose["services"])
        self.assertNotEqual(
            compose["services"]["backend"]["environment"]["SMTP_HOST"],
            "${SMTP_HOST:-mailpit}",
        )

        acceptance = yaml.safe_load(ACCEPTANCE_COMPOSE_FILE.read_text(encoding="utf-8"))
        mailpit = acceptance["services"]["mailpit"]
        self.assertEqual(mailpit["expose"], ["1025", "8025"])
        self.assertIn("readyz", " ".join(mailpit["healthcheck"]["test"]))
        for service_name in ("backend", "worker", "scheduler"):
            with self.subTest(service=service_name):
                self.assertEqual(
                    acceptance["services"][service_name]["environment"]["SMTP_HOST"],
                    "mailpit",
                )
                self.assertEqual(
                    acceptance["services"][service_name]["depends_on"]["mailpit"]["condition"],
                    "service_healthy",
                )
        self.assertEqual(
            acceptance["services"]["backend"]["environment"]["NOTIFICATION_TEST_SMTP_API_URL"],
            "http://mailpit:8025/api/v1/messages",
        )

    def test_primary_compose_passes_smtp_authentication_without_literal_credentials(self):
        compose = yaml.safe_load(COMPOSE_FILE.read_text(encoding="utf-8"))

        for service_name in ("migrate", "backend", "worker", "scheduler"):
            with self.subTest(service=service_name):
                environment = compose["services"][service_name]["environment"]
                self.assertEqual(environment["SMTP_USERNAME"], "${SMTP_USERNAME:-}")
                self.assertEqual(environment["SMTP_PASSWORD"], "${SMTP_PASSWORD:-}")

    def test_week11_12_ci_installs_and_executes_real_redacted_security_scanners(self):
        parsed = yaml.safe_load(self.workflow)
        job = parsed["jobs"]["week11-12-verification"]
        steps = job["steps"]
        install = next(
            step for step in steps if step.get("name") == "Install security scanners"
        )
        scan = next(step for step in steps if step.get("name") == "Run security scans")

        self.assertIn("pip-audit==2.", install["run"])
        self.assertIn("bandit==1.", install["run"])
        self.assertIn("v0.67.2", install["run"])
        self.assertIn("v8.24.2", install["run"])
        self.assertEqual(
            scan["env"]["ACCEPTANCE_IMAGE"],
            "ml-platform-backend:week11-12-${{ github.sha }}",
        )
        self.assertIn("tools.security_scans all", scan["run"])
        self.assertIn("--npm-audit-exception", scan["run"])
        self.assertNotIn("--pip-audit-exception", scan["run"])
        self.assertNotIn("cryptography-pkcs7-mlflow-exception.json", scan["run"])
        self.assertIn("security/security.json", scan["run"])

    def test_week11_12_ci_builds_and_scans_every_production_python_image_from_the_commit(self):
        parsed = yaml.safe_load(self.workflow)
        steps = parsed["jobs"]["week11-12-verification"]["steps"]
        build = next(
            step
            for step in steps
            if step.get("name") == "Build production images for security scan"
        )
        scan = next(step for step in steps if step.get("name") == "Run security scans")

        self.assertIn("for image in backend worker inference tensorboard", build["run"])
        self.assertIn("ml-platform-${image}:week11-12-${GITHUB_SHA}", build["run"])
        self.assertIn("ACCEPTANCE_ADDITIONAL_IMAGES", scan["env"])
        self.assertIn("ml-platform-worker:week11-12-${{ github.sha }}", scan["env"]["ACCEPTANCE_ADDITIONAL_IMAGES"])
        self.assertIn("ml-platform-inference:week11-12-${{ github.sha }}", scan["env"]["ACCEPTANCE_ADDITIONAL_IMAGES"])
        self.assertIn("ml-platform-tensorboard:week11-12-${{ github.sha }}", scan["env"]["ACCEPTANCE_ADDITIONAL_IMAGES"])
        self.assertIn('dockerfile="Dockerfile"', build["run"])
        self.assertIn('dockerfile="Dockerfile.$image"', build["run"])
        self.assertIn('-f "$dockerfile"', build["run"])
        self.assertIn("docker image inspect", build["run"])
        self.assertIn("ACCEPTANCE_IMAGE_DIGEST", build["run"])
        self.assertIn("ACCEPTANCE_ADDITIONAL_IMAGES", scan["env"])
        self.assertIn("ACCEPTANCE_SOURCE_COMMIT", scan["env"])
        self.assertEqual(scan["env"]["ACCEPTANCE_SOURCE_COMMIT"], "${{ github.sha }}")

    def test_week11_12_ci_runs_web_gate_on_frozen_stack_then_summarizes_security_evidence(self):
        parsed = yaml.safe_load(self.workflow)
        steps = parsed["jobs"]["week11-12-verification"]["steps"]
        rendered_steps = "\n".join(str(step.get("run", "")) for step in steps)

        self.assertIn("tools.acceptance_environment web-context", rendered_steps)
        self.assertIn("tools.security_scans web", rendered_steps)
        self.assertIn("--base-url http://backend:8000", rendered_steps)
        self.assertIn("security/web.json", rendered_steps)
        self.assertIn("tools.acceptance_environment web-context-cleanup", rendered_steps)
        self.assertIn("WEB_SECURITY_GATE_NOT_RUN", rendered_steps)
        self.assertIn("tools.security_scans summarize", rendered_steps)
        self.assertIn("security/summary.json", rendered_steps)
        self.assertIn('--source-commit "${GITHUB_SHA}"', rendered_steps)
        self.assertIn("docker compose --project-name", rendered_steps)

    def test_react_router_audit_exception_is_scoped_time_bound_and_owned(self):
        exception = json.loads(NPM_AUDIT_EXCEPTION.read_text(encoding="utf-8"))

        self.assertEqual(exception["schema_version"], 1)
        self.assertEqual(exception["id"], "react-router-rsc-mode-csrf")
        self.assertEqual(exception["owner"], "ml-platform-maintainers")
        self.assertEqual(exception["expires_on"], "2026-09-10")
        self.assertEqual(
            exception["package_versions"],
            {"react-router": "7.18.2", "react-router-dom": "7.18.2"},
        )
        self.assertEqual(exception["advisory_sources"], [1138769])
        self.assertIn("BrowserRouter", exception["mitigation"])

    def test_delivery_docs_cover_four_notification_channels_and_evidence_boundary(self):
        infrastructure = PRODUCTION_INFRASTRUCTURE.read_text(encoding="utf-8")
        guide = USER_GUIDE.read_text(encoding="utf-8")
        status = PLATFORM_STATUS.read_text(encoding="utf-8")

        for marker in (
            "MLflow 3.15.0",
            "NOTIFICATION_CRYPTO_SECRET_FILE",
            "SMTP_USERNAME",
            "SMTP_PASSWORD",
            "notification_crypto_configured",
            "notification_worker_registered",
            "RUN_NOTIFICATION_INTEGRATION=1",
        ):
            with self.subTest(infrastructure_marker=marker):
                self.assertIn(marker, infrastructure)
        for marker in ("通知中心", "站内通知", "企业微信", "邮件", "通用 Webhook"):
            with self.subTest(guide_marker=marker):
                self.assertIn(marker, guide)
        for marker in (
            "第十周",
            "20260720_10_security_notifications",
            "本地 WSL",
            "远程 GitHub Actions 尚未执行",
        ):
            with self.subTest(status_marker=marker):
                self.assertIn(marker, status)

    def test_acceptance_receiver_preserves_production_wecom_and_webhook_boundaries(self):
        acceptance = yaml.safe_load(ACCEPTANCE_COMPOSE_FILE.read_text(encoding="utf-8"))
        receiver = acceptance["services"]["notification-receiver"]
        proxy = acceptance["services"]["notification-proxy"]

        self.assertNotIn("user", receiver)
        self.assertEqual(receiver["cap_drop"], ["ALL"])
        self.assertEqual(receiver["cap_add"], ["NET_BIND_SERVICE"])
        self.assertEqual(
            receiver["command"][:3],
            ["python", "-m", "tools.notification_receiver"],
        )
        self.assertIn("443", receiver["expose"])
        self.assertEqual(
            receiver["ports"],
            ["127.0.0.1:${WEEK12_RECEIVER_EVENTS_PORT:-18081}:8080"],
        )
        self.assertEqual(proxy["command"][:3], ["python", "-m", "tools.notification_receiver"])
        self.assertIn("qyapi.weixin.qq.com", " ".join(proxy["command"]))
        self.assertIn("3128", proxy["expose"])
        self.assertIn("127.0.0.1:8080/events", " ".join(receiver["healthcheck"]["test"]))
        self.assertTrue(proxy["healthcheck"]["disable"])

        self.assertIn("notification_acceptance_ca", acceptance["secrets"])
        for service_name in ("backend", "worker"):
            service = acceptance["services"][service_name]
            environment = service["environment"]
            with self.subTest(service=service_name):
                self.assertEqual(environment["HTTPS_PROXY"], "http://notification-proxy:3128")
                self.assertEqual(
                    environment["SSL_CERT_FILE"],
                    "/run/secrets/notification_acceptance_ca",
                )
                self.assertEqual(
                    environment["NOTIFICATION_WEBHOOK_ALLOWLIST"],
                    "notification-receiver",
                )
                self.assertIn("notification-receiver", environment["NO_PROXY"])
                self.assertIn("notification_acceptance_ca", service["secrets"])

        backend_environment = acceptance["services"]["backend"]["environment"]
        self.assertEqual(
            backend_environment["NOTIFICATION_TEST_WEBHOOK_URL"],
            "https://notification-receiver/events",
        )
        self.assertEqual(
            backend_environment["NOTIFICATION_TEST_WECOM_URL"],
            "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=acceptance-controlled",
        )
        self.assertEqual(
            backend_environment["NOTIFICATION_TEST_RECEIVER_EVENTS_URL"],
            "http://notification-receiver:8080/events",
        )
        self.assertEqual(
            acceptance["services"]["postgres"]["ports"],
            ["127.0.0.1:${WEEK12_POSTGRES_PORT:-15432}:5432"],
        )
        self.assertEqual(
            acceptance["services"]["inference-runtime"]["ports"],
            ["127.0.0.1:${WEEK12_INFERENCE_RUNTIME_PORT:-17000}:7000"],
        )

    def test_frontend_healthcheck_uses_ipv4_loopback(self):
        dockerfile = FRONTEND_DOCKERFILE.read_text(encoding="utf-8")

        self.assertIn("wget -qO- http://127.0.0.1/", dockerfile)
        self.assertNotIn("wget -qO- http://localhost/", dockerfile)

    def test_production_ci_generates_and_runs_notification_acceptance(self):
        parsed = yaml.safe_load(self.workflow)
        job = parsed["jobs"]["production-integration"]
        self.assertNotIn("NOTIFICATION_MASTER_KEY", job["env"])

        steps = job["steps"]
        key_step = next(step for step in steps if step.get("name") == "Generate notification test key")
        integration_step = next(step for step in steps if step.get("name") == "Run production integration tests")
        self.assertIn("Fernet.generate_key", key_step["run"])
        self.assertEqual(integration_step["env"]["RUN_NOTIFICATION_INTEGRATION"], "1")
        self.assertIn("tests.test_notification_production_stack", integration_step["run"])
        self.assertEqual(
            job["env"]["NOTIFICATION_TEST_SMTP_API_URL"],
            "http://127.0.0.1:8025/api/v1/messages",
        )

    def test_production_failure_evidence_scans_raw_logs_and_notification_key(self):
        parsed = yaml.safe_load(self.workflow)
        steps = parsed["jobs"]["production-integration"]["steps"]
        evidence = next(
            step
            for step in steps
            if step.get("name") == "Scan and upload production failure evidence"
        )
        upload = next(
            step
            for step in steps
            if step.get("name") == "Upload production failure evidence"
        )
        evidence_script = evidence["run"]

        self.assertIn("PRODUCTION_EVIDENCE_RAW", evidence_script)
        self.assertIn("PRODUCTION_EVIDENCE_REDACTED", evidence_script)
        self.assertIn("trap cleanup_production_evidence EXIT", evidence_script)
        self.assertIn("NOTIFICATION_MASTER_KEY_FILE", evidence_script)
        self.assertIn('grep -RFl -- "$PRODUCTION_NOTIFICATION_MASTER_KEY"', evidence_script)
        self.assertIn("mli_[A-Za-z0-9_-]+", evidence_script)
        self.assertIn('cp "$PRODUCTION_EVIDENCE_RAW"/* "$PRODUCTION_EVIDENCE_REDACTED"/', evidence_script)
        self.assertIn('rm -rf "$PRODUCTION_EVIDENCE_RAW"', evidence_script)
        self.assertIn("trap - EXIT", evidence_script)
        self.assertEqual(upload["with"]["path"], "${{ runner.temp }}/production-evidence")

        self.assertLess(
            evidence_script.index('grep -RFl -- "$PRODUCTION_NOTIFICATION_MASTER_KEY"'),
            evidence_script.index('cp "$PRODUCTION_EVIDENCE_RAW"/*'),
        )
        self.assertLess(
            evidence_script.index("mli_[A-Za-z0-9_-]+"),
            evidence_script.index('cp "$PRODUCTION_EVIDENCE_RAW"/*'),
        )

    def test_notification_stack_sends_mailpit_email_from_the_live_worker(self):
        source = NOTIFICATION_STACK_TEST.read_text(encoding="utf-8")
        mailpit_test = source.split(
            "def test_03_real_mailpit_receives_only_the_safe_email_envelope",
            maxsplit=1,
        )[1].split("def test_04_retry_exhaustion_creates_one_dead_letter_alert", maxsplit=1)[0]

        self.assertNotIn("RecordingSMTP", source)
        self.assertIn("deliver_notifications_task.delay", mailpit_test)
        self.assertIn("NOTIFICATION_TEST_SMTP_API_URL", mailpit_test)

    def test_notification_stack_has_an_opt_in_real_wecom_and_webhook_worker_gate(self):
        source = NOTIFICATION_STACK_TEST.read_text(encoding="utf-8")
        external_gate = source.split(
            "def test_05_real_worker_delivers_webhook_and_wecom_to_controlled_receiver",
            maxsplit=1,
        )[1].split("def test_04_retry_exhaustion_creates_one_dead_letter_alert", maxsplit=1)[0]

        self.assertIn("RUN_NOTIFICATION_EXTERNAL_RECEIVER_INTEGRATION", source)
        self.assertIn("NOTIFICATION_TEST_WEBHOOK_URL", external_gate)
        self.assertIn("NOTIFICATION_TEST_WECOM_URL", external_gate)
        self.assertIn("NOTIFICATION_TEST_RECEIVER_EVENTS_URL", external_gate)
        self.assertIn("deliver_notifications_task.delay", external_gate)
        self.assertNotIn("RecordingHttpClient", external_gate)

    def test_experiment_ci_uses_acceptance_compose_for_controlled_mailpit(self):
        parsed = yaml.safe_load(self.workflow)
        job = parsed["jobs"]["experiment-integration"]
        start = next(
            step
            for step in job["steps"]
            if step.get("name") == "Start production experiment stack"
        )
        verify = next(
            step
            for step in job["steps"]
            if step.get("name") == "Verify migrations and real experiment lifecycle"
        )

        self.assertEqual(
            job["env"].get("COMPOSE_FILE"),
            "docker-compose.yml:docker-compose.acceptance.yml",
        )
        self.assertIn("mailpit", start["run"])
        self.assertIn("notification-receiver", start["run"])
        self.assertIn("notification-proxy", start["run"])
        self.assertIn("RUN_NOTIFICATION_INTEGRATION=1", verify["run"])
        self.assertIn("RUN_NOTIFICATION_EXTERNAL_RECEIVER_INTEGRATION=1", verify["run"])
        self.assertIn("tests.test_notification_production_stack", verify["run"])
        self.assertIn("NOTIFICATION_ACCEPTANCE_CA_FILE", job["env"])
        self.assertIn("NOTIFICATION_RECEIVER_CERTIFICATE_FILE", job["env"])
        self.assertIn("NOTIFICATION_RECEIVER_PRIVATE_KEY_FILE", job["env"])

        receiver_certificate = next(
            step
            for step in job["steps"]
            if step.get("name") == "Generate notification receiver certificate"
        )
        self.assertIn("subjectAltName=DNS:qyapi.weixin.qq.com,DNS:notification-receiver", receiver_certificate["run"])
        self.assertIn("NOTIFICATION_ACCEPTANCE_CA_FILE", receiver_certificate["run"])

    def test_experiment_ci_uses_the_portable_compose_validation_flag(self):
        parsed = yaml.safe_load(self.workflow)
        steps = parsed["jobs"]["experiment-integration"]["steps"]
        validate = next(
            step for step in steps if step.get("name") == "Validate production composition"
        )

        self.assertIn(" config -q", validate["run"])
        self.assertNotIn("config --quiet", validate["run"])

    def test_ci_removes_and_scans_each_generated_notification_key(self):
        parsed = yaml.safe_load(self.workflow)
        production_steps = parsed["jobs"]["production-integration"]["steps"]
        experiment_steps = parsed["jobs"]["experiment-integration"]["steps"]
        production_evidence = next(
            step
            for step in production_steps
            if step.get("name") == "Scan and upload production failure evidence"
        )
        production_stop = next(
            step
            for step in production_steps
            if step.get("name") == "Stop Celery worker"
        )
        experiment_evidence = next(
            step
            for step in experiment_steps
            if step.get("name") == "Collect redacted experiment failure evidence"
        )
        experiment_stop = next(
            step
            for step in experiment_steps
            if step.get("name") == "Stop production experiment stack"
        )

        self.assertIn('rm -f "$NOTIFICATION_MASTER_KEY_FILE"', production_stop["run"])
        self.assertIn("NOTIFICATION_CRYPTO_SECRET_FILE", experiment_evidence["run"])
        self.assertIn(
            'grep -RFl -- "$INFERENCE_NOTIFICATION_MASTER_KEY"',
            experiment_evidence["run"],
        )
        self.assertIn(
            'rm -f "$NOTIFICATION_CRYPTO_SECRET_FILE"',
            experiment_stop["run"],
        )

    def test_week11_12_verification_waits_for_frozen_stack_and_uploads_evidence(self):
        parsed = yaml.safe_load(self.workflow)
        job = parsed["jobs"]["week11-12-verification"]

        self.assertEqual(
            job["needs"],
            [
                "quality",
                "browser-acceptance",
                "production-integration",
                "experiment-integration",
            ],
        )
        run_tools = next(
            step for step in job["steps"] if step.get("name") == "Run verification tools"
        )
        self.assertIn("tests.test_week11_12_tools", run_tools["run"])
        self.assertIn("tests.test_week11_contracts", run_tools["run"])
        self.assertIn("tests.test_week12_security_gates", run_tools["run"])
        self.assertIn("tests.test_evidence_manifest", run_tools["run"])
        self.assertIn("tools.acceptance_environment", run_tools["run"])

        upload = next(
            step for step in job["steps"] if step.get("name") == "Upload verification evidence"
        )
        self.assertEqual(upload["if"], "always()")
        self.assertEqual(upload["with"]["path"], "temp_test/week11-12")

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
