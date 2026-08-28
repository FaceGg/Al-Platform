import json
import hashlib
import os
import sqlite3
import subprocess
import sys
import tempfile
import threading
import unittest
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from http.client import HTTPConnection
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import Request, urlopen
from unittest.mock import patch

import tools.week11_performance as week11_performance
from tools.acceptance_environment import collect_environment, redact
from tools.backup_restore import (
    _write_operation_receipt,
    _write_pending_operation_receipt,
    backup_postgres,
    create_backup_manifest,
    main as backup_restore_main,
    mirror_minio,
    restore_minio,
    restore_postgres,
    run_backup_command,
    verify_restore,
)
from tools.notification_receiver import NotificationReceiver
from tools.upgrade_fixture import (
    EXPECTED_HEAD,
    EXPECTED_N_MINUS_ONE,
    EXPECTED_N_MINUS_ONE_HEADS,
    create_upgrade_fixture,
    create_upgrade_record,
    execute_upgrade,
    main as upgrade_fixture_main,
    run_alembic,
    snapshot_database,
    validate_upgrade_result,
    verify_upgrade,
)
from tools.week11_performance import (
    SCENARIO_EXPECTED_LOAD,
    _git_commit,
    evaluate_thresholds,
    main as performance_main,
    percentile,
    run_http_scenario,
    write_result,
)


class PerformanceToolContractTests(unittest.TestCase):
    def test_percentile_is_deterministic_and_uses_sorted_samples(self):
        self.assertEqual(percentile([30.0, 10.0, 20.0], 0.95), 29.0)

    def test_threshold_result_contains_named_gate_and_raw_samples(self):
        result = evaluate_thresholds(
            {"p95_ms": 100.0, "p99_ms": 200.0, "error_rate": 0.0},
            {"p95_ms": 300.0, "p99_ms": 800.0, "error_rate": 0.001},
        )
        self.assertEqual(result["status"], "passed")
        self.assertEqual(result["gates"]["p95_ms"]["limit"], 300.0)

    def test_error_rate_gate_rejects_the_candidate_limit(self):
        result = evaluate_thresholds(
            {"error_rate": 0.001},
            {"error_rate": 0.001},
        )
        self.assertEqual(result["status"], "failed")

    def test_write_result_creates_machine_readable_json(self):
        with tempfile.TemporaryDirectory() as directory:
            path = write_result(Path(directory) / "run.json", {"status": "passed"})
            self.assertEqual(
                json.loads(path.read_text(encoding="utf-8"))["status"],
                "passed",
            )

    @patch.dict(os.environ, {"ACCEPTANCE_SOURCE_COMMIT": "b" * 40}, clear=False)
    @patch("tools.week11_performance.subprocess.run")
    def test_explicit_source_commit_is_used_when_container_has_no_git(self, run):
        self.assertEqual(_git_commit(), "b" * 40)
        run.assert_not_called()


class EnvironmentManifestTests(unittest.TestCase):
    @patch("tools.acceptance_environment._command_output", return_value="available")
    def test_manifest_contains_versions_but_no_secret_values(self, _command_output):
        manifest = collect_environment(
            {
                "SECRET_KEY": "test-secret",
                "DATABASE_URL": "postgresql://u:p@db/app",
                "APP_MODE": "production",
            },
        )
        serialized = json.dumps(manifest)
        self.assertIn("python", manifest["runtime"])
        self.assertEqual(manifest["configuration"], {"APP_MODE": "production"})
        self.assertNotIn("test-secret", serialized)
        self.assertNotIn("u:p@", serialized)

    def test_redaction_handles_password_only_url_userinfo(self):
        value = redact("redis://:secret@cache/0")
        self.assertNotIn(":secret@", value)
        manifest = collect_environment({"TASK_BACKEND": "redis://:secret@cache/0"})
        self.assertNotIn(":secret@", json.dumps(manifest))

    def test_redaction_handles_raw_userinfo_and_colon_secret_assignments(self):
        rendered = redact(
            "https://user:pa@ss@receiver.example.invalid client_secret: probe-value",
        )
        self.assertNotIn("pa@ss", rendered)
        self.assertNotIn("probe-value", rendered)


class AcceptanceRunnerContractTests(unittest.TestCase):
    def test_week11_runner_uses_versioned_executors_not_temp_test(self):
        root = Path(__file__).resolve().parents[3]
        runner = root / "ml-platform" / "backend" / "tools" / "acceptance" / "run_week11_acceptance.sh"
        self.assertTrue(runner.is_file())
        content = runner.read_text(encoding="utf-8")
        self.assertIn("tools/acceptance/run_performance.sh", content)
        self.assertIn("tools/acceptance/run_backup_restore.sh", content)
        self.assertIn("tools/acceptance/run_upgrade_fixture.sh", content)
        self.assertNotIn("temp_test", content)

    def test_full_ci_runs_the_versioned_live_week11_executor(self):
        root = Path(__file__).resolve().parents[3]
        workflow = (root / ".github" / "workflows" / "ci.yml").read_text(
            encoding="utf-8",
        )
        self.assertIn("Run live Week 11 acceptance evidence", workflow)
        self.assertIn(
            "bash ml-platform/backend/tools/acceptance/run_week11_acceptance.sh",
            workflow,
        )

    def test_upgrade_smoke_failure_stops_the_acceptance_runner(self):
        root = Path(__file__).resolve().parents[3]
        runner = (
            root / "ml-platform" / "backend" / "tools" / "acceptance"
            / "run_upgrade_fixture.sh"
        )
        content = runner.read_text(encoding="utf-8")
        self.assertIn("raise SystemExit(0 if result[\"status\"] == \"passed\" else 1)", content)

    def test_performance_runner_preserves_compose_managed_runtime_secrets(self):
        root = Path(__file__).resolve().parents[3]
        runner = (
            root / "ml-platform" / "backend" / "tools" / "acceptance"
            / "run_performance.sh"
        )
        content = runner.read_text(encoding="utf-8")
        self.assertNotIn("/tmp/week9-12-secrets", content)
        self.assertNotIn("docker run -d", content)
        self.assertIn('docker cp "$BACKEND:$CONTAINER_PERFORMANCE/." "$PERFORMANCE"', content)


class _OkHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"{}")

    def log_message(self, *_args):
        return


class _InferenceApiKeyHandler(BaseHTTPRequestHandler):
    observed_headers: dict[str, str] = {}

    def do_POST(self):
        self.__class__.observed_headers = dict(self.headers.items())
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"{}")

    def log_message(self, *_args):
        return


class _WorkflowCompletionHandler(BaseHTTPRequestHandler):
    submitted = 0

    def do_POST(self):
        self.__class__.submitted += 1
        payload = json.dumps({"run_id": f"run-{self.submitted}"}).encode("utf-8")
        self.send_response(201)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self):
        payload = json.dumps({"status": "completed"}).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *_args):
        return


class PerformanceScenarioTests(unittest.TestCase):
    _COMMIT = "a" * 40

    @classmethod
    def _raw_result(
        cls,
        scenario: str,
        iteration: int,
        *,
        errors: int = 0,
        p95_ms: float = 10.0,
        p99_ms: float = 12.0,
        duration_ms: float | None = None,
    ) -> dict[str, object]:
        load = SCENARIO_EXPECTED_LOAD[scenario]
        requests = load["concurrency"] * load["requests_per_worker"]
        result: dict[str, object] = {
            "concurrency": load["concurrency"],
            "requests_per_worker": load["requests_per_worker"],
            "requests": requests,
            "errors": errors,
            "error_rate": errors / requests,
            "status_counts": {"200": requests - errors, "500": errors},
            "p95_ms": p95_ms,
            "p99_ms": p99_ms,
            "scenario": scenario,
            "iteration": iteration,
            "commit": cls._COMMIT,
        }
        if duration_ms is not None:
            result["duration_ms"] = duration_ms
        if scenario == "welding-e2e":
            result.update(
                {
                    "completed_requests": requests,
                    "terminal_status_counts": {"completed": requests},
                    "completion_samples_ms": [duration_ms or 1000.0] * requests,
                },
            )
        return result

    def _summarize(self, root: Path, output: Path) -> int:
        with patch("tools.week11_performance._git_commit", return_value=self._COMMIT):
            return performance_main(
                ["summarize", "--input-dir", str(root), "--output", str(output)],
            )

    def test_scenario_records_status_latency_and_error_rate(self):
        server = ThreadingHTTPServer(("127.0.0.1", 0), _OkHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            result = run_http_scenario(
                f"http://127.0.0.1:{server.server_port}/",
                concurrency=2,
                requests_per_worker=3,
            )
        finally:
            server.shutdown()
            thread.join(timeout=3)
            server.server_close()
        self.assertEqual(result["requests"], 6)
        self.assertEqual(result["errors"], 0)
        self.assertEqual(result.get("concurrency"), 2)
        self.assertEqual(result.get("requests_per_worker"), 3)
        self.assertIn("p95_ms", result)
        self.assertIn("p99_ms", result)

    def test_api_key_cli_uses_the_frozen_inference_header(self):
        server = ThreadingHTTPServer(("127.0.0.1", 0), _InferenceApiKeyHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with tempfile.TemporaryDirectory() as directory, patch.dict(
                os.environ,
                {"TEST_INFERENCE_API_KEY": "test-inference-key"},
                clear=False,
            ):
                exit_code = performance_main(
                    [
                        "run",
                        "--url",
                        f"http://127.0.0.1:{server.server_port}/predict",
                        "--concurrency",
                        "1",
                        "--requests-per-worker",
                        "1",
                        "--scenario",
                        "cold-model-load",
                        "--iteration",
                        "1",
                        "--method",
                        "POST",
                        "--api-key-env",
                        "TEST_INFERENCE_API_KEY",
                        "--output",
                        str(Path(directory) / "result.json"),
                    ],
                )
        finally:
            server.shutdown()
            thread.join(timeout=3)
            server.server_close()

        self.assertEqual(exit_code, 0)
        self.assertEqual(
            _InferenceApiKeyHandler.observed_headers.get("X-Inference-Api-Key"),
            "test-inference-key",
        )
        self.assertNotIn("X-API-Key", _InferenceApiKeyHandler.observed_headers)

    def test_welding_runner_waits_for_all_terminal_completions(self):
        runner = getattr(week11_performance, "run_workflow_scenario", None)
        self.assertIsNotNone(runner)
        _WorkflowCompletionHandler.submitted = 0
        server = ThreadingHTTPServer(("127.0.0.1", 0), _WorkflowCompletionHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            base_url = f"http://127.0.0.1:{server.server_port}"
            result = runner(
                f"{base_url}/workflows/test/run",
                f"{base_url}/runs/{{run_id}}",
                requests_per_worker=10,
                poll_interval=0.01,
            )
        finally:
            server.shutdown()
            thread.join(timeout=3)
            server.server_close()

        self.assertEqual(result["requests"], 10)
        self.assertEqual(result["completed_requests"], 10)
        self.assertEqual(result["errors"], 0)
        self.assertEqual(result["terminal_status_counts"], {"completed": 10})
        self.assertEqual(len(result["completion_samples_ms"]), 10)
        self.assertEqual(result["duration_ms"], max(result["completion_samples_ms"]))

    def test_summary_rejects_reduced_load_and_inconsistent_error_accounting(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for iteration in range(1, 4):
                write_result(
                    root / f"core-{iteration}.json",
                    {
                        "concurrency": 1,
                        "requests_per_worker": 2000,
                        "requests": 2000,
                        "errors": 0,
                        "error_rate": 0.0,
                        "status_counts": {"200": 1999, "500": 1},
                        "p95_ms": 100.0,
                        "p99_ms": 200.0,
                        "scenario": "core-read",
                        "iteration": iteration,
                        "commit": "a" * 40,
                    },
                )
            output = root / "summary.json"
            self._summarize(root, output)
            summary = json.loads(output.read_text(encoding="utf-8"))

        self.assertEqual(summary["scenarios"]["core-read"]["status"], "failed")

    def test_summary_requires_consistent_raw_commits(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for iteration, commit in enumerate(("a" * 40, "a" * 40, "b" * 40), start=1):
                write_result(
                    root / f"core-{iteration}.json",
                    {
                        "concurrency": 20,
                        "requests_per_worker": 100,
                        "requests": 2000,
                        "errors": 0,
                        "error_rate": 0.0,
                        "status_counts": {"200": 2000},
                        "p95_ms": 100.0,
                        "p99_ms": 200.0,
                        "scenario": "core-read",
                        "iteration": iteration,
                        "commit": commit,
                    },
                )
            output = root / "summary.json"
            self._summarize(root, output)
            summary = json.loads(output.read_text(encoding="utf-8"))

        self.assertEqual(summary["scenarios"]["core-read"]["status"], "failed")

    def test_summary_rejects_raw_commit_different_from_current_commit(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for iteration in range(1, 4):
                result = self._raw_result("core-read", iteration, p95_ms=100.0, p99_ms=200.0)
                result["commit"] = "b" * 40
                write_result(root / f"core-{iteration}.json", result)
            output = root / "summary.json"
            self._summarize(root, output)
            summary = json.loads(output.read_text(encoding="utf-8"))

        self.assertEqual(summary["scenarios"]["core-read"]["status"], "failed")

    def test_summary_cli_fails_when_required_scenarios_are_missing(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_result(
                root / "run-1.json",
                {
                    "errors": 0,
                    "p95_ms": 10.0,
                    "p99_ms": 12.0,
                    "error_rate": 0.0,
                    "scenario": "core-read",
                    "iteration": 1,
                },
            )
            write_result(
                root / "run-2.json",
                {
                    "errors": 0,
                    "p95_ms": 11.0,
                    "p99_ms": 13.0,
                    "error_rate": 0.0,
                    "scenario": "core-read",
                    "iteration": 2,
                },
            )
            write_result(
                root / "run-3.json",
                {
                    "errors": 0,
                    "p95_ms": 12.0,
                    "p99_ms": 14.0,
                    "error_rate": 0.0,
                    "scenario": "core-read",
                    "iteration": 3,
                },
            )
            output = root / "summary.json"
            self.assertEqual(
                self._summarize(root, output),
                1,
            )
            summary = json.loads(output.read_text(encoding="utf-8"))
        self.assertEqual(summary["status"], "failed")
        self.assertEqual(len(summary["iterations"]), 3)

    def test_summary_requires_every_frozen_acceptance_scenario(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for iteration in range(1, 4):
                write_result(
                    root / f"core-{iteration}.json",
                    self._raw_result("core-read", iteration, p95_ms=100.0, p99_ms=200.0),
                )
            output = root / "summary.json"
            self._summarize(root, output)
            summary = json.loads(output.read_text(encoding="utf-8"))
        self.assertEqual(summary["status"], "failed")

    def test_summary_fails_candidate_gate_and_keeps_raw_result_path(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_result(
                root / "slow.json",
                {"errors": 0, "p95_ms": 5000.0, "p99_ms": 6000.0, "error_rate": 0.0},
            )
            output = root / "summary.json"
            self._summarize(root, output)
            summary = json.loads(output.read_text(encoding="utf-8"))
        self.assertEqual(summary["candidate_status"], "failed")
        self.assertEqual(summary["iterations"][0]["path"], "slow.json")

    def test_summary_uses_warm_inference_thresholds_and_error_rate_not_count(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for iteration in range(1, 4):
                write_result(
                    root / f"warm-{iteration}.json",
                    self._raw_result("warm-inference", iteration, p95_ms=250.0, p99_ms=700.0),
                )
            output = root / "warm-summary.json"
            self._summarize(root, output)
            warm_summary = json.loads(output.read_text(encoding="utf-8"))
        self.assertEqual(warm_summary["candidate_status"], "failed")

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for iteration in range(1, 4):
                write_result(
                    root / f"core-{iteration}.json",
                    self._raw_result(
                        "core-read",
                        iteration,
                        errors=1,
                        p95_ms=100.0,
                        p99_ms=200.0,
                    ),
                )
            output = root / "core-summary.json"
            self._summarize(root, output)
            core_summary = json.loads(output.read_text(encoding="utf-8"))
        self.assertEqual(core_summary["scenarios"]["core-read"]["status"], "passed")

    def test_summary_accepts_single_cold_and_welding_measurements(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_result(
                root / "cold-load-1.json",
                self._raw_result("cold-model-load", 1, p99_ms=10.0),
            )
            write_result(
                root / "welding-e2e-1.json",
                self._raw_result(
                    "welding-e2e",
                    1,
                    p99_ms=10.0,
                    duration_ms=1000.0,
                ),
            )
            output = root / "summary.json"
            self._summarize(root, output)
            summary = json.loads(output.read_text(encoding="utf-8"))
        self.assertEqual(summary["scenarios"]["cold-model-load"]["status"], "passed")
        self.assertEqual(summary["scenarios"]["welding-e2e"]["status"], "passed")

    def test_summary_rejects_failed_welding_run(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_result(
                root / "welding-e2e-1.json",
                self._raw_result(
                    "welding-e2e",
                    1,
                    errors=1,
                    p99_ms=10.0,
                    duration_ms=1000.0,
                ),
            )
            output = root / "summary.json"
            self._summarize(root, output)
            summary = json.loads(output.read_text(encoding="utf-8"))
        self.assertEqual(summary["scenarios"]["welding-e2e"]["status"], "failed")

    def test_summary_rejects_welding_submissions_without_completion_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            result = self._raw_result(
                "welding-e2e",
                1,
                p99_ms=10.0,
                duration_ms=1000.0,
            )
            result.pop("completed_requests")
            result.pop("terminal_status_counts")
            result.pop("completion_samples_ms")
            write_result(root / "welding-e2e-1.json", result)
            output = root / "summary.json"
            self._summarize(root, output)
            summary = json.loads(output.read_text(encoding="utf-8"))

        self.assertEqual(summary["scenarios"]["welding-e2e"]["status"], "failed")

    def test_summary_requires_all_ten_welding_runs(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            incomplete = self._raw_result(
                "welding-e2e",
                1,
                p99_ms=10.0,
                duration_ms=1000.0,
            )
            incomplete.update(
                {
                    "requests_per_worker": 9,
                    "requests": 9,
                    "status_counts": {"200": 9},
                },
            )
            write_result(root / "welding-e2e-1.json", incomplete)
            output = root / "summary.json"
            self._summarize(root, output)
            summary = json.loads(output.read_text(encoding="utf-8"))
        self.assertEqual(summary["scenarios"]["welding-e2e"]["status"], "failed")


class BackupRestoreTests(unittest.TestCase):
    _EVIDENCE_KEY = "week11-12-test-evidence-key"

    @classmethod
    def _restore_environment(cls, database_url: str, destination: str) -> dict[str, str]:
        return {
            "DATABASE_URL": "postgresql://user:password@db/default",
            "RESTORE_ACCEPTANCE_DATABASE_URL": database_url,
            "RESTORE_ACCEPTANCE_ISOLATED": "1",
            "RESTORE_ACCEPTANCE_MINIO_DESTINATION": destination,
            "RESTORE_SOURCE_MINIO": "https://minio.example.test/backup/ml-platform",
            "BACKUP_RESTORE_EVIDENCE_KEY": cls._EVIDENCE_KEY,
        }

    @staticmethod
    def _representative_snapshot() -> dict[str, object]:
        return {
            "table_counts": {"retained": 1},
            "foreign_key_violations": [],
        }

    @classmethod
    def _write_signed_restore_receipts(
        cls,
        root: Path,
        postgres_duration: float = 1.0,
        minio_duration: float = 1.0,
    ) -> None:
        manifest_path = root / "manifest.json"
        _write_operation_receipt(
            manifest_path,
            "restore-operation.json",
            "restore-postgres",
            0,
            postgres_duration,
        )
        _write_operation_receipt(
            manifest_path,
            "minio-restore-operation.json",
            "restore-minio",
            0,
            minio_duration,
        )

    def test_backup_command_rejects_credentials_in_output(self):
        with patch("tools.backup_restore.subprocess.run") as run:
            run.return_value.stdout = "dump postgresql://user:password@db/app token=abc"
            run.return_value.stderr = ""
            run.return_value.returncode = 0
            result = run_backup_command(["pg_dump", "--file", "backup.dump"])
        serialized = json.dumps(result)
        self.assertEqual(result["returncode"], 0)
        self.assertNotIn("password", serialized.lower())
        self.assertNotIn("token=abc", serialized)

    def test_backup_command_rejects_credential_bearing_url_arguments(self):
        with self.assertRaises(ValueError):
            run_backup_command(
                ["mc", "mirror", "postgresql://user:password@db/app", "backup"],
            )

    def test_backup_command_rejects_equals_form_urls_and_credential_options(self):
        with self.assertRaises(ValueError):
            run_backup_command(
                ["pg_dump", "--dbname=postgresql://user:password@db/app"],
            )
        with self.assertRaises(ValueError):
            run_backup_command(["scanner", "--client-secret=probe-value"])

    def test_postgres_command_uses_environment_for_credentials_and_failure_exit(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "backup.dump"
            database_url = "postgresql://user:password@db:5432/app"
            with patch.dict(
                os.environ,
                {
                    "DATABASE_URL": "postgresql://user:password@db/default",
                    "BACKUP_ACCEPTANCE_DATABASE_URL": database_url,
                    "BACKUP_ACCEPTANCE_ISOLATED": "1",
                    "BACKUP_RESTORE_EVIDENCE_KEY": self._EVIDENCE_KEY,
                },
                clear=True,
            ):
                with patch("tools.backup_restore.subprocess.run") as run:
                    run.return_value.stdout = ""
                    run.return_value.stderr = ""
                    run.return_value.returncode = 12
                    result = backup_postgres(database_url, output)
                    command = run.call_args.args[0]
                    environment = run.call_args.kwargs["env"]
            with (
                patch(
                    "tools.backup_restore.backup_postgres",
                    return_value={"returncode": 12},
                ),
                patch("builtins.print"),
            ):
                with patch.dict(
                    os.environ,
                    {
                        "DATABASE_URL": "postgresql://user:password@db/default",
                        "BACKUP_DATABASE_URL": database_url,
                        "BACKUP_ACCEPTANCE_DATABASE_URL": database_url,
                        "BACKUP_ACCEPTANCE_ISOLATED": "1",
                    },
                    clear=True,
                ):
                    exit_code = backup_restore_main(
                        [
                            "backup-postgres",
                            "--database-url-env",
                            "BACKUP_DATABASE_URL",
                            "--output",
                            str(output),
                        ],
                    )
        self.assertNotIn("user:password", " ".join(command))
        self.assertEqual(environment["PGPASSWORD"], "password")
        self.assertNotIn("user:password", json.dumps(result))
        self.assertEqual(exit_code, 12)

    def test_restore_postgres_requires_explicit_isolated_acceptance_target(self):
        with tempfile.TemporaryDirectory() as directory:
            dump = Path(directory) / "postgres.dump"
            dump.write_bytes(b"backup")
            database_url = "postgresql://restore:restore-password@db/default"
            default_database_url = "postgresql://source:source-password@db/default"
            source_database_url = "postgresql://backup:backup-password@source-db/source"
            with (
                patch.dict(
                    os.environ,
                    {
                        "DATABASE_URL": default_database_url,
                        "RESTORE_ACCEPTANCE_DATABASE_URL": database_url,
                        "RESTORE_ACCEPTANCE_ISOLATED": "1",
                    },
                    clear=True,
                ),
                patch("tools.backup_restore.run_backup_command") as run_command,
            ):
                run_command.return_value = {
                    "returncode": 0,
                    "stdout": "",
                    "stderr": "",
                }
                with self.assertRaisesRegex(ValueError, "isolated") as error:
                    restore_postgres(database_url, dump, source_database_url)
        run_command.assert_not_called()
        self.assertNotIn("restore-password", str(error.exception))
        self.assertNotIn("source-password", str(error.exception))
        self.assertNotIn("backup-password", str(error.exception))

    def test_restore_cli_rejects_arbitrary_database_environment_target(self):
        with tempfile.TemporaryDirectory() as directory:
            dump = Path(directory) / "postgres.dump"
            dump.write_bytes(b"backup")
            database_url = "postgresql://user:password@db/default"
            with (
                patch.dict(
                    os.environ,
                    {"RESTORE_DATABASE_URL": database_url},
                    clear=True,
                ),
                patch("tools.backup_restore.run_backup_command") as run_command,
            ):
                run_command.return_value = {
                    "returncode": 0,
                    "stdout": "",
                    "stderr": "",
                }
                with self.assertRaisesRegex(ValueError, "isolated") as error:
                    backup_restore_main(
                        [
                            "restore-postgres",
                            "--database-url-env",
                            "RESTORE_DATABASE_URL",
                            "--dump",
                            str(dump),
                        ],
                    )
        run_command.assert_not_called()
        self.assertNotIn("user:password", str(error.exception))

    def test_restore_postgres_accepts_only_matching_isolated_target(self):
        with tempfile.TemporaryDirectory() as directory:
            dump = Path(directory) / "postgres.dump"
            dump.write_bytes(b"backup")
            database_url = "postgresql://user:password@db/acceptance_restore"
            source_database_url = "postgresql://user:password@db/source"
            with (
                patch.dict(
                    os.environ,
                    {
                        "DATABASE_URL": "postgresql://user:password@db/default",
                        "RESTORE_ACCEPTANCE_DATABASE_URL": database_url,
                        "RESTORE_ACCEPTANCE_ISOLATED": "1",
                        "BACKUP_RESTORE_EVIDENCE_KEY": self._EVIDENCE_KEY,
                    },
                    clear=True,
                ),
                patch("tools.backup_restore.run_backup_command") as run_command,
            ):
                run_command.return_value = {
                    "returncode": 0,
                    "stdout": "",
                    "stderr": "",
                }
                create_backup_manifest(Path(directory))
                result = restore_postgres(
                    database_url,
                    dump,
                    source_database_url,
                )
        self.assertEqual(result["returncode"], 0)
        self.assertNotIn("user:password", json.dumps(result))
        self.assertEqual(run_command.call_args.args[0][0], "pg_restore")

    def test_restore_postgres_requires_a_distinct_explicit_source_target(self):
        with tempfile.TemporaryDirectory() as directory:
            dump = Path(directory) / "postgres.dump"
            dump.write_bytes(b"backup")
            database_url = "postgresql://user:password@db/acceptance_restore"
            source_database_url = "postgresql://source:source-password@db/acceptance_restore"
            with (
                patch.dict(
                    os.environ,
                    {
                        "RESTORE_ACCEPTANCE_DATABASE_URL": database_url,
                        "RESTORE_ACCEPTANCE_ISOLATED": "1",
                    },
                    clear=True,
                ),
                patch("tools.backup_restore.run_backup_command") as run_command,
            ):
                run_command.return_value = {
                    "returncode": 0,
                    "stdout": "",
                    "stderr": "",
                }
                with self.assertRaisesRegex(ValueError, "isolated") as error:
                    restore_postgres(database_url, dump, source_database_url)
        run_command.assert_not_called()
        self.assertNotIn("user:password", str(error.exception))
        self.assertNotIn("source-password", str(error.exception))

    def test_restore_minio_requires_explicit_isolated_destination(self):
        with tempfile.TemporaryDirectory() as directory:
            receipt = Path(directory) / "minio-restore-operation.json"
            destination = "s3://user:password@production/restored"
            with (
                patch.dict(os.environ, {}, clear=True),
                patch("tools.backup_restore.run_backup_command") as run_command,
            ):
                with self.assertRaisesRegex(ValueError, "isolated") as error:
                    restore_minio("backup/minio", destination, receipt)
        run_command.assert_not_called()
        self.assertNotIn("user:password", str(error.exception))

    def test_restore_minio_cli_rejects_arbitrary_destination(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            destination = "s3://user:password@production/restored"
            with (
                patch.dict(os.environ, {}, clear=True),
                patch("tools.backup_restore.run_backup_command") as run_command,
            ):
                with self.assertRaisesRegex(ValueError, "isolated") as error:
                    backup_restore_main(
                        [
                            "restore-minio",
                            "--source",
                            "backup/minio",
                            "--destination",
                            destination,
                            "--receipt-dir",
                            str(root),
                        ],
                    )
        run_command.assert_not_called()
        self.assertNotIn("user:password", str(error.exception))

    def test_restore_minio_accepts_matching_isolated_destination(self):
        with tempfile.TemporaryDirectory() as directory:
            receipt = Path(directory) / "minio-restore-operation.json"
            source = str(Path(directory) / "backup" / "minio")
            destination = str(Path(directory) / "restored" / "ml-platform")
            with (
                patch.dict(
                    os.environ,
                    {
                        "RESTORE_ACCEPTANCE_MINIO_DESTINATION": destination,
                        "RESTORE_ACCEPTANCE_ISOLATED": "1",
                        "BACKUP_RESTORE_EVIDENCE_KEY": self._EVIDENCE_KEY,
                    },
                    clear=True,
                ),
                patch("tools.backup_restore.run_backup_command") as run_command,
            ):
                run_command.return_value = {
                    "returncode": 0,
                    "stdout": "",
                    "stderr": "",
                }
                create_backup_manifest(Path(directory))
                result = restore_minio(source, destination, receipt)
        self.assertEqual(result["returncode"], 0)
        self.assertEqual(run_command.call_args.args[0][:3], ["mc", "mirror", "--overwrite"])

    def test_verify_restore_requires_restore_timing_receipt(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.db"
            restored = root / "restored.db"
            sqlite3.connect(source).close()
            sqlite3.connect(restored).close()
            manifest = root / "manifest.json"
            manifest.write_text('{"created_at": "2026-07-20T12:00:00Z", "files": []}', encoding="utf-8")
            result = verify_restore(
                f"sqlite:///{source.as_posix()}",
                f"sqlite:///{restored.as_posix()}",
                manifest,
                root,
                root / "result.json",
            )
        self.assertEqual(result["status"], "failed")
        self.assertIsNone(result["rto_seconds"])

    def test_verify_restore_requires_successful_restore_receipt(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.db"
            restored = root / "restored.db"
            sqlite3.connect(source).close()
            sqlite3.connect(restored).close()
            manifest = root / "manifest.json"
            manifest.write_text(
                '{"created_at": "2026-07-20T12:00:00Z", "files": []}',
                encoding="utf-8",
            )
            (root / "restore-operation.json").write_text(
                '{"returncode": 12, "duration_seconds": 1.0}',
                encoding="utf-8",
            )
            result = verify_restore(
                f"sqlite:///{source.as_posix()}",
                f"sqlite:///{restored.as_posix()}",
                manifest,
                root,
                root / "result.json",
            )
        self.assertEqual(result["status"], "failed")

    def test_manifest_contains_sha256_relative_paths_and_no_self_hash(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "dump.bin"
            path.write_bytes(b"backup")
            with patch.dict(
                os.environ,
                {"BACKUP_RESTORE_EVIDENCE_KEY": self._EVIDENCE_KEY},
                clear=True,
            ):
                first = create_backup_manifest(root)
                second = create_backup_manifest(root)
        self.assertEqual(first["files"][0]["path"], "dump.bin")
        self.assertEqual(len(first["files"][0]["sha256"]), 64)
        self.assertEqual(first["files"], second["files"])
        self.assertEqual(
            datetime.fromisoformat(first["created_at"]).tzinfo,
            timezone.utc,
        )

    def test_manifest_cli_generates_utc_timestamp(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            before = datetime.now(timezone.utc)
            with (
                patch.dict(
                    os.environ,
                    {"BACKUP_RESTORE_EVIDENCE_KEY": self._EVIDENCE_KEY},
                    clear=True,
                ),
                patch("builtins.print"),
            ):
                self.assertEqual(backup_restore_main(["manifest", "--root", str(root)]), 0)
            after = datetime.now(timezone.utc)
            created_at = datetime.fromisoformat(
                json.loads((root / "manifest.json").read_text(encoding="utf-8"))["created_at"],
            )

        self.assertEqual(created_at.tzinfo, timezone.utc)
        self.assertGreaterEqual(created_at, before)
        self.assertLessEqual(created_at, after)

    def test_manifest_cli_rejects_user_supplied_timestamp_without_leaking_it(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaisesRegex(ValueError, "generated") as error:
                backup_restore_main(
                    [
                        "manifest",
                        "--root",
                        str(root),
                        "--created-at",
                        "postgresql://user:password@db/default",
                    ],
                )
        self.assertNotIn("user:password", str(error.exception))

    def test_verify_restore_compares_database_counts_and_mirrored_hashes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            backup_root = root / "backup"
            (backup_root / "minio").mkdir(parents=True)
            (backup_root / "minio" / "artifact.bin").write_bytes(b"artifact")
            restored_root = root / "restored-objects"
            restored_root.mkdir()
            (restored_root / "artifact.bin").write_bytes(b"artifact")
            source = "postgresql://user:password@db/source"
            restored = "postgresql://user:password@db/restored"
            snapshots = {
                "table_counts": {"parent": 1, "child": 1},
                "foreign_key_violations": [],
            }
            with patch.dict(
                os.environ,
                self._restore_environment(restored, str(restored_root)),
                clear=True,
            ):
                create_backup_manifest(backup_root)
                _write_operation_receipt(
                    backup_root / "manifest.json",
                    "postgres-backup-operation.json",
                    "backup-postgres",
                    0,
                    1.0,
                )
                _write_operation_receipt(
                    backup_root / "manifest.json",
                    "minio-backup-operation.json",
                    "backup-minio",
                    0,
                    1.0,
                )
                self._write_signed_restore_receipts(backup_root)
                with patch(
                    "tools.backup_restore.collect_database_snapshot",
                    side_effect=[snapshots, snapshots],
                ):
                    result = verify_restore(
                        source,
                        restored,
                        backup_root / "manifest.json",
                        restored_root,
                        root / "restore-result.json",
                    )
                serialized = (root / "restore-result.json").read_text(encoding="utf-8")
        self.assertEqual(result["status"], "passed")
        self.assertNotIn("user:password", serialized)
        self.assertEqual(result["object_hashes"]["status"], "passed")

    def test_verify_restore_rejects_stale_or_future_backup_rpo(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = "postgresql://user:password@db/source"
            restored = "postgresql://user:password@db/restored"
            snapshots = self._representative_snapshot()
            for index, completion_time in enumerate((
                datetime.now(timezone.utc) - timedelta(days=2),
                datetime.now(timezone.utc) + timedelta(minutes=5),
            )):
                backup_root = root / f"backup-{index}"
                minio_root = backup_root / "minio"
                minio_root.mkdir(parents=True)

                class FixedDatetime(datetime):
                    @classmethod
                    def now(cls, tz=None):
                        return completion_time if tz is not None else completion_time.replace(tzinfo=None)

                with patch.dict(
                    os.environ,
                    self._restore_environment(restored, str(minio_root)),
                    clear=True,
                ):
                    with patch("tools.backup_restore.datetime", FixedDatetime):
                        create_backup_manifest(backup_root)
                        _write_operation_receipt(
                            backup_root / "manifest.json",
                            "postgres-backup-operation.json",
                            "backup-postgres",
                            0,
                            1.0,
                            completion_time,
                        )
                        _write_operation_receipt(
                            backup_root / "manifest.json",
                            "minio-backup-operation.json",
                            "backup-minio",
                            0,
                            1.0,
                            completion_time,
                        )
                    self._write_signed_restore_receipts(backup_root)
                    with patch(
                        "tools.backup_restore.collect_database_snapshot",
                        side_effect=[snapshots, snapshots],
                    ):
                        result = verify_restore(
                            source,
                            restored,
                            backup_root / "manifest.json",
                            minio_root,
                            root / "restore-result.json",
                        )
                self.assertEqual(result["status"], "failed")
                self.assertFalse(result["rpo_passed"])

    def test_verify_restore_requires_and_counts_minio_restore_receipt(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            backup_root = root / "backup"
            (backup_root / "minio").mkdir(parents=True)
            source = "postgresql://user:password@db/source"
            restored = "postgresql://user:password@db/restored"
            snapshots = self._representative_snapshot()
            with patch.dict(
                os.environ,
                self._restore_environment(restored, str(backup_root / "minio")),
                clear=True,
            ):
                create_backup_manifest(backup_root)
                self._write_signed_restore_receipts(
                    backup_root,
                    postgres_duration=1000.0,
                    minio_duration=900.0,
                )
                with patch(
                    "tools.backup_restore.collect_database_snapshot",
                    side_effect=[snapshots, snapshots],
                ):
                    result = verify_restore(
                        source,
                        restored,
                        backup_root / "manifest.json",
                        backup_root / "minio",
                        root / "restore-result.json",
                    )
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["rto_seconds"], 1900.0)

    def test_verify_restore_rejects_credential_bucket_before_mc_call(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = root / "manifest.json"
            manifest.write_text(
                '{"created_at": "2026-07-20T12:00:00Z", "files": [{"path": "minio/object.bin", "sha256": "0"}]}',
                encoding="utf-8",
            )
            output = root / "result.json"
            restored = "postgresql://user:password@db/restored"
            with (
                patch.dict(
                    os.environ,
                    self._restore_environment(restored, "s3://bucket/restored"),
                    clear=True,
                ),
                patch("tools.backup_restore.subprocess.run") as run,
            ):
                result = verify_restore(
                    "postgresql://user:password@db/source",
                    restored,
                    manifest,
                    "s3://user:password@bucket/restored",
                    output,
                )
            serialized = output.read_text(encoding="utf-8")
        run.assert_not_called()
        self.assertEqual(result["status"], "failed")
        self.assertNotIn("user:password", serialized)

    def test_verify_restore_rejects_source_target_self_comparison_before_snapshot(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = root / "manifest.json"
            manifest.write_text(
                '{"created_at": "2026-07-20T12:00:00Z", "files": []}',
                encoding="utf-8",
            )
            output = root / "result.json"
            database_url = "postgresql://user:password@db/default"
            with (
                patch.dict(
                    os.environ,
                    self._restore_environment(database_url, str(root)),
                    clear=True,
                ),
                patch("tools.backup_restore.collect_database_snapshot") as collect,
            ):
                collect.return_value = {
                    "table_counts": {"retained": 1},
                    "foreign_key_violations": [],
                }
                result = verify_restore(database_url, database_url, manifest, root, output)
            serialized = output.read_text(encoding="utf-8")
        self.assertEqual(result["status"], "failed")
        collect.assert_not_called()
        self.assertNotIn("user:password", serialized)


class BackupUpgradeHardeningRegressionTests(unittest.TestCase):
    _EVIDENCE_KEY = "test-evidence-key"

    @classmethod
    def _write_signed_backup_completion_receipts(
        cls,
        root: Path,
        postgres_completed_at: datetime | None = None,
        minio_completed_at: datetime | None = None,
    ) -> None:
        postgres_completed_at = postgres_completed_at or datetime.now(timezone.utc)
        minio_completed_at = minio_completed_at or datetime.now(timezone.utc)
        manifest_path = root / "manifest.json"
        _write_operation_receipt(
            manifest_path,
            "postgres-backup-operation.json",
            "backup-postgres",
            0,
            1.0,
            postgres_completed_at,
        )
        _write_operation_receipt(
            manifest_path,
            "minio-backup-operation.json",
            "backup-minio",
            0,
            1.0,
            minio_completed_at,
        )

    @staticmethod
    def _restore_environment(database_url: str, destination: str) -> dict[str, str]:
        return {
            "DATABASE_URL": "postgresql://user:password@db/default",
            "RESTORE_ACCEPTANCE_DATABASE_URL": database_url,
            "RESTORE_ACCEPTANCE_ISOLATED": "1",
            "RESTORE_ACCEPTANCE_MINIO_DESTINATION": destination,
            "RESTORE_SOURCE_MINIO": "https://minio.example.test/backup/ml-platform",
            "BACKUP_RESTORE_EVIDENCE_KEY": "test-evidence-key",
        }

    @staticmethod
    def _representative_snapshot() -> dict[str, object]:
        return {
            "table_counts": {"retained": 1},
            "foreign_key_violations": [],
        }

    @classmethod
    def _write_signed_restore_receipts(cls, root: Path) -> None:
        manifest_path = root / "manifest.json"
        _write_operation_receipt(
            manifest_path,
            "restore-operation.json",
            "restore-postgres",
            0,
            1.0,
        )
        _write_operation_receipt(
            manifest_path,
            "minio-restore-operation.json",
            "restore-minio",
            0,
            1.0,
        )

    def test_mirror_minio_rejects_equivalent_alias_backed_bucket_before_mirror(self):
        aliases = "\n".join(
            (
                json.dumps(
                    {
                        "alias": "source",
                        "URL": "https://minio.example.test",
                    },
                ),
                json.dumps(
                    {
                        "alias": "restored",
                        "URL": "https://minio.example.test",
                    },
                ),
            ),
        )
        with (
            patch.dict(
                os.environ,
                {
                    "BACKUP_ACCEPTANCE_MINIO_DESTINATION": "restored/ml-platform",
                    "BACKUP_ACCEPTANCE_ISOLATED": "1",
                },
                clear=True,
            ),
            patch("tools.backup_restore.subprocess.run") as alias_list,
            patch("tools.backup_restore.run_backup_command") as mirror,
        ):
            alias_list.return_value = type(
                "Completed",
                (),
                {"returncode": 0, "stdout": aliases, "stderr": ""},
            )()
            with self.assertRaisesRegex(ValueError, "isolated"):
                mirror_minio("source/ml-platform", "restored/ml-platform")
        alias_list.assert_called_once_with(
            ["mc", "alias", "list", "--json"],
            capture_output=True,
            text=True,
            check=False,
        )
        mirror.assert_not_called()

    def test_mirror_minio_rejects_unavailable_or_unknown_aliases_before_mirror(self):
        unavailable = OSError("mc alias lookup unavailable")
        unknown_destination = type(
            "Completed",
            (),
            {
                "returncode": 0,
                "stdout": json.dumps(
                    {
                        "alias": "source",
                        "URL": "https://minio.example.test",
                    },
                ),
                "stderr": "",
            },
        )()
        failed_listing = type(
            "Completed",
            (),
            {"returncode": 2, "stdout": "", "stderr": ""},
        )()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch.dict(
                os.environ,
                {
                    "BACKUP_ACCEPTANCE_MINIO_DESTINATION": "restored/ml-platform",
                    "BACKUP_ACCEPTANCE_ISOLATED": "1",
                    "BACKUP_RESTORE_EVIDENCE_KEY": self._EVIDENCE_KEY,
                },
                clear=True,
            ):
                create_backup_manifest(root)
                for label, response in (
                    ("unavailable", unavailable),
                    ("nonzero", failed_listing),
                    ("unknown", unknown_destination),
                ):
                    with self.subTest(label=label):
                        with (
                            patch("tools.backup_restore.subprocess.run") as alias_list,
                            patch("tools.backup_restore.run_backup_command") as mirror,
                        ):
                            if isinstance(response, Exception):
                                alias_list.side_effect = response
                            else:
                                alias_list.return_value = response
                            with self.assertRaisesRegex(ValueError, "isolated"):
                                mirror_minio(
                                    "source/ml-platform",
                                    "restored/ml-platform",
                                    root / "minio-backup-operation.json",
                                )
                            mirror.assert_not_called()

    def test_mirror_minio_requires_a_receipt_path_before_mirror(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            destination = root / "destination"
            with (
                patch.dict(
                    os.environ,
                    {
                        "BACKUP_ACCEPTANCE_MINIO_DESTINATION": str(destination),
                        "BACKUP_ACCEPTANCE_ISOLATED": "1",
                    },
                    clear=True,
                ),
                patch("tools.backup_restore.run_backup_command") as mirror,
            ):
                with self.assertRaisesRegex(ValueError, "receipt"):
                    mirror_minio(str(source), str(destination))
        mirror.assert_not_called()

    def test_backup_minio_cli_writes_a_signed_pending_completion_record(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            destination = root / "minio"
            postgres_output = root / "postgres.dump"
            database_url = "postgresql://user:password@db/default"

            def complete_backup(command, _environment=None):
                if command[0] == "pg_dump":
                    postgres_output.write_bytes(b"postgres backup")
                else:
                    destination.mkdir(parents=True, exist_ok=True)
                    (destination / "artifact.bin").write_bytes(b"artifact")
                return {"returncode": 0, "stdout": "", "stderr": ""}

            with (
                patch.dict(
                    os.environ,
                    {
                        "DATABASE_URL": database_url,
                        "BACKUP_ACCEPTANCE_MINIO_DESTINATION": str(destination),
                        "BACKUP_ACCEPTANCE_ISOLATED": "1",
                        "BACKUP_RESTORE_EVIDENCE_KEY": self._EVIDENCE_KEY,
                    },
                    clear=True,
                ),
                patch(
                    "tools.backup_restore.run_backup_command",
                    side_effect=complete_backup,
                ) as mirror,
                patch("builtins.print"),
            ):
                backup_postgres(database_url, postgres_output)
                exit_code = backup_restore_main(
                    [
                        "backup-minio",
                        "--source",
                        str(source),
                        "--destination",
                        str(destination),
                        "--receipt-dir",
                        str(root),
                    ],
                )
                receipt = json.loads(
                    (root / "minio-backup-pending.json").read_text(encoding="utf-8"),
                )
        self.assertEqual(exit_code, 0)
        self.assertEqual(receipt["operation"], "backup-minio")
        self.assertNotIn("manifest_sha256", receipt)
        self.assertEqual(mirror.call_args.args[0][:3], ["mc", "mirror", "--overwrite"])

    def test_mirror_minio_rejects_hard_linked_object_before_signing_pending_record(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            postgres_output = root / "postgres.dump"
            minio_source = root / "source"
            minio_destination = root / "minio"
            external_artifact = root / "external-artifact.bin"
            external_artifact.write_bytes(b"external artifact")
            probe_link = root / "hard-link-probe.bin"
            try:
                os.link(external_artifact, probe_link)
            except OSError as error:
                self.skipTest(f"hard links are unavailable: {error}")
            probe_link.unlink()
            database_url = "postgresql://user:password@db/default"

            def complete_backup(command, _environment=None):
                if command[0] == "pg_dump":
                    postgres_output.write_bytes(b"postgres backup")
                else:
                    minio_destination.mkdir(parents=True, exist_ok=True)
                    os.link(external_artifact, minio_destination / "artifact.bin")
                return {"returncode": 0, "stdout": "", "stderr": ""}

            with (
                patch.dict(
                    os.environ,
                    {
                        "DATABASE_URL": database_url,
                        "BACKUP_ACCEPTANCE_MINIO_DESTINATION": str(minio_destination),
                        "BACKUP_ACCEPTANCE_ISOLATED": "1",
                        "BACKUP_RESTORE_EVIDENCE_KEY": self._EVIDENCE_KEY,
                    },
                    clear=True,
                ),
                patch(
                    "tools.backup_restore.run_backup_command",
                    side_effect=complete_backup,
                ),
            ):
                backup_postgres(database_url, postgres_output)
                with self.assertRaisesRegex(ValueError, "linked"):
                    mirror_minio(
                        str(minio_source),
                        str(minio_destination),
                        root / "minio-backup-operation.json",
                    )

            self.assertEqual(external_artifact.read_bytes(), b"external artifact")
            self.assertFalse((root / "minio-backup-pending.json").exists())

    def test_manifest_creation_rejects_an_occupied_invalid_pending_receipt_path(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "postgres-backup-pending.json").mkdir()

            with self.assertRaisesRegex(ValueError, "pending records"):
                create_backup_manifest(root)

            self.assertFalse((root / "manifest.json").exists())

    def test_backup_flow_finalizes_both_receipts_against_final_minio_manifest(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            postgres_output = root / "postgres.dump"
            minio_source = root / "source"
            minio_destination = root / "minio"
            database_url = "postgresql://user:password@db/default"

            def complete_backup(command, _environment=None):
                if command[0] == "pg_dump":
                    postgres_output.write_bytes(b"postgres backup")
                else:
                    minio_destination.mkdir(parents=True, exist_ok=True)
                    (minio_destination / "artifact.bin").write_bytes(b"artifact")
                return {"returncode": 0, "stdout": "", "stderr": ""}

            with (
                patch.dict(
                    os.environ,
                    {
                        "DATABASE_URL": database_url,
                        "BACKUP_ACCEPTANCE_MINIO_DESTINATION": str(minio_destination),
                        "BACKUP_ACCEPTANCE_ISOLATED": "1",
                        "BACKUP_RESTORE_EVIDENCE_KEY": self._EVIDENCE_KEY,
                    },
                    clear=True,
                ),
                patch(
                    "tools.backup_restore.run_backup_command",
                    side_effect=complete_backup,
                ),
            ):
                backup_postgres(database_url, postgres_output)
                mirror_minio(
                    str(minio_source),
                    str(minio_destination),
                    root / "minio-backup-operation.json",
                )
                manifest = create_backup_manifest(root)
                manifest_sha256 = hashlib.sha256(
                    (root / "manifest.json").read_bytes(),
                ).hexdigest()
                postgres_receipt = json.loads(
                    (root / "postgres-backup-operation.json").read_text(encoding="utf-8"),
                )
                minio_receipt = json.loads(
                    (root / "minio-backup-operation.json").read_text(encoding="utf-8"),
                )
        self.assertIn(
            "minio/artifact.bin",
            [entry["path"] for entry in manifest["files"]],
        )
        self.assertEqual(postgres_receipt["manifest_sha256"], manifest_sha256)
        self.assertEqual(minio_receipt["manifest_sha256"], manifest_sha256)
        self.assertEqual(postgres_receipt["operation"], "backup-postgres")
        self.assertEqual(minio_receipt["operation"], "backup-minio")

    def test_final_manifest_recovers_matching_pending_record_after_interrupted_cleanup(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            postgres_output = root / "postgres.dump"
            minio_source = root / "source"
            minio_destination = root / "minio"
            database_url = "postgresql://user:password@db/default"

            def complete_backup(command, _environment=None):
                if command[0] == "pg_dump":
                    postgres_output.write_bytes(b"postgres backup")
                else:
                    minio_destination.mkdir(parents=True, exist_ok=True)
                    (minio_destination / "artifact.bin").write_bytes(b"artifact")
                return {"returncode": 0, "stdout": "", "stderr": ""}

            with (
                patch.dict(
                    os.environ,
                    {
                        "DATABASE_URL": database_url,
                        "BACKUP_ACCEPTANCE_MINIO_DESTINATION": str(minio_destination),
                        "BACKUP_ACCEPTANCE_ISOLATED": "1",
                        "BACKUP_RESTORE_EVIDENCE_KEY": self._EVIDENCE_KEY,
                    },
                    clear=True,
                ),
                patch(
                    "tools.backup_restore.run_backup_command",
                    side_effect=complete_backup,
                ),
            ):
                backup_postgres(database_url, postgres_output)
                mirror_minio(
                    str(minio_source),
                    str(minio_destination),
                    root / "minio-backup-operation.json",
                )
                retained_pending = (root / "minio-backup-pending.json").read_bytes()
                manifest = create_backup_manifest(root)
                final_receipts = {
                    name: (root / name).read_bytes()
                    for name in (
                        "postgres-backup-operation.json",
                        "minio-backup-operation.json",
                    )
                }
                (root / "minio-backup-pending.json").write_bytes(retained_pending)

                recovered = create_backup_manifest(root)
                self.assertEqual(recovered, manifest)
                self.assertFalse((root / "minio-backup-pending.json").exists())
                self.assertEqual(
                    (root / "postgres-backup-operation.json").read_bytes(),
                    final_receipts["postgres-backup-operation.json"],
                )
                self.assertEqual(
                    (root / "minio-backup-operation.json").read_bytes(),
                    final_receipts["minio-backup-operation.json"],
                )

    def test_final_manifest_recovers_after_interrupted_receipt_finalization(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            postgres_output = root / "postgres.dump"
            minio_source = root / "source"
            minio_destination = root / "minio"
            database_url = "postgresql://user:password@db/default"

            def complete_backup(command, _environment=None):
                if command[0] == "pg_dump":
                    postgres_output.write_bytes(b"postgres backup")
                else:
                    minio_destination.mkdir(parents=True, exist_ok=True)
                    (minio_destination / "artifact.bin").write_bytes(b"artifact")
                return {"returncode": 0, "stdout": "", "stderr": ""}

            with (
                patch.dict(
                    os.environ,
                    {
                        "DATABASE_URL": database_url,
                        "BACKUP_ACCEPTANCE_MINIO_DESTINATION": str(minio_destination),
                        "BACKUP_ACCEPTANCE_ISOLATED": "1",
                        "BACKUP_RESTORE_EVIDENCE_KEY": self._EVIDENCE_KEY,
                    },
                    clear=True,
                ),
                patch(
                    "tools.backup_restore.run_backup_command",
                    side_effect=complete_backup,
                ),
            ):
                backup_postgres(database_url, postgres_output)
                mirror_minio(
                    str(minio_source),
                    str(minio_destination),
                    root / "minio-backup-operation.json",
                )
                original_write = _write_operation_receipt
                writes = 0

                def interrupt_second_receipt(*args, **kwargs):
                    nonlocal writes
                    writes += 1
                    if writes == 2:
                        raise OSError("interrupted receipt finalization")
                    return original_write(*args, **kwargs)

                with patch(
                    "tools.backup_restore._write_operation_receipt",
                    side_effect=interrupt_second_receipt,
                ):
                    with self.assertRaisesRegex(OSError, "interrupted"):
                        create_backup_manifest(root)

                self.assertTrue((root / "manifest.json").is_file())
                self.assertTrue((root / "postgres-backup-operation.json").is_file())
                self.assertTrue((root / "postgres-backup-pending.json").is_file())
                self.assertTrue((root / "minio-backup-pending.json").is_file())

                recovered = create_backup_manifest(root)
                self.assertIn("backup_run_id", recovered)
                self.assertTrue((root / "postgres-backup-operation.json").is_file())
                self.assertTrue((root / "minio-backup-operation.json").is_file())
                self.assertFalse((root / "postgres-backup-pending.json").exists())
                self.assertFalse((root / "minio-backup-pending.json").exists())

    def test_interrupted_finalization_rejects_corrupt_existing_final_receipt(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            postgres_output = root / "postgres.dump"
            minio_source = root / "source"
            minio_destination = root / "minio"
            database_url = "postgresql://user:password@db/default"

            def complete_backup(command, _environment=None):
                if command[0] == "pg_dump":
                    postgres_output.write_bytes(b"postgres backup")
                else:
                    minio_destination.mkdir(parents=True, exist_ok=True)
                    (minio_destination / "artifact.bin").write_bytes(b"artifact")
                return {"returncode": 0, "stdout": "", "stderr": ""}

            with (
                patch.dict(
                    os.environ,
                    {
                        "DATABASE_URL": database_url,
                        "BACKUP_ACCEPTANCE_MINIO_DESTINATION": str(minio_destination),
                        "BACKUP_ACCEPTANCE_ISOLATED": "1",
                        "BACKUP_RESTORE_EVIDENCE_KEY": self._EVIDENCE_KEY,
                    },
                    clear=True,
                ),
                patch(
                    "tools.backup_restore.run_backup_command",
                    side_effect=complete_backup,
                ),
            ):
                backup_postgres(database_url, postgres_output)
                mirror_minio(
                    str(minio_source),
                    str(minio_destination),
                    root / "minio-backup-operation.json",
                )
                original_write = _write_operation_receipt
                writes = 0

                def interrupt_second_receipt(*args, **kwargs):
                    nonlocal writes
                    writes += 1
                    if writes == 2:
                        raise OSError("interrupted receipt finalization")
                    return original_write(*args, **kwargs)

                with patch(
                    "tools.backup_restore._write_operation_receipt",
                    side_effect=interrupt_second_receipt,
                ):
                    with self.assertRaisesRegex(OSError, "interrupted"):
                        create_backup_manifest(root)

                final_path = root / "postgres-backup-operation.json"
                corrupted = json.loads(final_path.read_text(encoding="utf-8"))
                corrupted["signature"] = "corrupt"
                final_path.write_text(
                    json.dumps(corrupted, ensure_ascii=True, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8",
                )
                preserved = {
                    name: (root / name).read_bytes()
                    for name in (
                        "postgres-backup-operation.json",
                        "postgres-backup-pending.json",
                        "minio-backup-pending.json",
                    )
                }

                with self.assertRaisesRegex(ValueError, "finalization is invalid"):
                    create_backup_manifest(root)

                for name, original in preserved.items():
                    self.assertEqual((root / name).read_bytes(), original)
                self.assertFalse((root / "minio-backup-operation.json").exists())

    def test_interrupted_finalization_rejects_existing_final_receipt_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            postgres_output = root / "postgres.dump"
            minio_source = root / "source"
            minio_destination = root / "minio"
            database_url = "postgresql://user:password@db/default"

            def complete_backup(command, _environment=None):
                if command[0] == "pg_dump":
                    postgres_output.write_bytes(b"postgres backup")
                else:
                    minio_destination.mkdir(parents=True, exist_ok=True)
                    (minio_destination / "artifact.bin").write_bytes(b"artifact")
                return {"returncode": 0, "stdout": "", "stderr": ""}

            with (
                patch.dict(
                    os.environ,
                    {
                        "DATABASE_URL": database_url,
                        "BACKUP_ACCEPTANCE_MINIO_DESTINATION": str(minio_destination),
                        "BACKUP_ACCEPTANCE_ISOLATED": "1",
                        "BACKUP_RESTORE_EVIDENCE_KEY": self._EVIDENCE_KEY,
                    },
                    clear=True,
                ),
                patch(
                    "tools.backup_restore.run_backup_command",
                    side_effect=complete_backup,
                ),
            ):
                backup_postgres(database_url, postgres_output)
                mirror_minio(
                    str(minio_source),
                    str(minio_destination),
                    root / "minio-backup-operation.json",
                )
                original_write = _write_operation_receipt
                writes = 0

                def interrupt_second_receipt(*args, **kwargs):
                    nonlocal writes
                    writes += 1
                    if writes == 2:
                        raise OSError("interrupted receipt finalization")
                    return original_write(*args, **kwargs)

                with patch(
                    "tools.backup_restore._write_operation_receipt",
                    side_effect=interrupt_second_receipt,
                ):
                    with self.assertRaisesRegex(OSError, "interrupted"):
                        create_backup_manifest(root)

                final_path = root / "postgres-backup-operation.json"
                final_path.unlink()
                final_path.mkdir()
                preserved = {
                    name: (root / name).read_bytes()
                    for name in (
                        "manifest.json",
                        "postgres-backup-pending.json",
                        "minio-backup-pending.json",
                    )
                }

                with self.assertRaisesRegex(ValueError, "finalization is invalid"):
                    create_backup_manifest(root)

                self.assertTrue(final_path.is_dir())
                for name, original in preserved.items():
                    self.assertEqual((root / name).read_bytes(), original)
                self.assertFalse((root / "minio-backup-operation.json").exists())

    def test_final_manifest_rejects_symlinked_signed_completion_receipt(self):
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            root = parent / "backup"
            root.mkdir()
            postgres_dump = root / "postgres.dump"
            minio_artifact = root / "minio" / "artifact.bin"
            postgres_dump.write_bytes(b"postgres backup")
            minio_artifact.parent.mkdir()
            minio_artifact.write_bytes(b"artifact")
            completed_at = datetime.now(timezone.utc)

            with patch.dict(
                os.environ,
                {"BACKUP_RESTORE_EVIDENCE_KEY": self._EVIDENCE_KEY},
                clear=True,
            ):
                _write_pending_operation_receipt(
                    root / "postgres-backup-pending.json",
                    "backup-postgres",
                    0,
                    1.0,
                    [
                        {
                            "path": "postgres.dump",
                            "size": postgres_dump.stat().st_size,
                            "sha256": hashlib.sha256(postgres_dump.read_bytes()).hexdigest(),
                        },
                    ],
                    completed_at,
                    backup_run_id="e" * 32,
                )
                _write_pending_operation_receipt(
                    root / "minio-backup-pending.json",
                    "backup-minio",
                    0,
                    1.0,
                    [
                        {
                            "path": "minio/artifact.bin",
                            "size": minio_artifact.stat().st_size,
                            "sha256": hashlib.sha256(
                                minio_artifact.read_bytes()
                            ).hexdigest(),
                        },
                    ],
                    completed_at,
                    backup_run_id="e" * 32,
                )
                create_backup_manifest(root)

                receipt_path = root / "postgres-backup-operation.json"
                receipt_bytes = receipt_path.read_bytes()
                original_is_symlink = Path.is_symlink

                def mark_receipt_as_symlink(path: Path) -> bool:
                    return path == receipt_path or original_is_symlink(path)

                with patch(
                    "tools.backup_restore.Path.is_symlink",
                    new=mark_receipt_as_symlink,
                ):
                    with self.assertRaisesRegex(ValueError, "finalization is invalid"):
                        create_backup_manifest(root)

                self.assertEqual(receipt_path.read_bytes(), receipt_bytes)

    def test_final_manifest_rejects_hard_linked_signed_completion_receipt(self):
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            root = parent / "backup"
            root.mkdir()
            postgres_dump = root / "postgres.dump"
            minio_artifact = root / "minio" / "artifact.bin"
            postgres_dump.write_bytes(b"postgres backup")
            minio_artifact.parent.mkdir()
            minio_artifact.write_bytes(b"artifact")
            completed_at = datetime.now(timezone.utc)

            with patch.dict(
                os.environ,
                {"BACKUP_RESTORE_EVIDENCE_KEY": self._EVIDENCE_KEY},
                clear=True,
            ):
                _write_pending_operation_receipt(
                    root / "postgres-backup-pending.json",
                    "backup-postgres",
                    0,
                    1.0,
                    [
                        {
                            "path": "postgres.dump",
                            "size": postgres_dump.stat().st_size,
                            "sha256": hashlib.sha256(postgres_dump.read_bytes()).hexdigest(),
                        },
                    ],
                    completed_at,
                    backup_run_id="f" * 32,
                )
                _write_pending_operation_receipt(
                    root / "minio-backup-pending.json",
                    "backup-minio",
                    0,
                    1.0,
                    [
                        {
                            "path": "minio/artifact.bin",
                            "size": minio_artifact.stat().st_size,
                            "sha256": hashlib.sha256(
                                minio_artifact.read_bytes()
                            ).hexdigest(),
                        },
                    ],
                    completed_at,
                    backup_run_id="f" * 32,
                )
                create_backup_manifest(root)

                receipt_path = root / "postgres-backup-operation.json"
                receipt_bytes = receipt_path.read_bytes()
                external_receipt = parent / "signed-postgres-receipt.json"
                try:
                    os.link(receipt_path, external_receipt)
                except OSError as error:
                    self.skipTest(f"hard links are unavailable: {error}")

                with self.assertRaisesRegex(ValueError, "finalization is invalid"):
                    create_backup_manifest(root)

                self.assertEqual(receipt_path.read_bytes(), receipt_bytes)
                self.assertEqual(external_receipt.read_bytes(), receipt_bytes)

    def test_manifest_creation_replaces_hard_link_without_writing_external_file(self):
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            root = parent / "backup"
            root.mkdir()
            external_manifest = parent / "external-manifest.json"
            external_manifest.write_text("external manifest", encoding="utf-8")
            manifest_path = root / "manifest.json"
            try:
                os.link(external_manifest, manifest_path)
            except OSError as error:
                self.skipTest(f"hard links are unavailable: {error}")

            manifest = create_backup_manifest(root)

            self.assertIn("created_at", manifest)
            self.assertEqual(
                external_manifest.read_text(encoding="utf-8"),
                "external manifest",
            )
            self.assertNotEqual(
                manifest_path.read_text(encoding="utf-8"),
                "external manifest",
            )

    def test_operation_receipt_replaces_hard_link_without_writing_external_file(self):
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            root = parent / "backup"
            root.mkdir()
            manifest_path = root / "manifest.json"
            manifest_path.write_text("{}\n", encoding="utf-8")
            external_receipt = parent / "external-receipt.json"
            external_receipt.write_text("external receipt", encoding="utf-8")
            receipt_path = root / "restore-operation.json"
            try:
                os.link(external_receipt, receipt_path)
            except OSError as error:
                self.skipTest(f"hard links are unavailable: {error}")

            with patch.dict(
                os.environ,
                {"BACKUP_RESTORE_EVIDENCE_KEY": self._EVIDENCE_KEY},
                clear=True,
            ):
                _write_operation_receipt(
                    manifest_path,
                    receipt_path.name,
                    "restore-postgres",
                    0,
                    1.0,
                )

            self.assertEqual(
                external_receipt.read_text(encoding="utf-8"),
                "external receipt",
            )
            self.assertNotEqual(
                receipt_path.read_text(encoding="utf-8"),
                "external receipt",
            )

    def test_operation_receipt_rejects_a_linked_manifest_before_hashing_it(self):
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            root = parent / "backup"
            root.mkdir()
            external_manifest = parent / "external-manifest.json"
            external_manifest.write_text("external manifest", encoding="utf-8")
            manifest_path = root / "manifest.json"
            try:
                os.link(external_manifest, manifest_path)
            except OSError as error:
                self.skipTest(f"hard links are unavailable: {error}")

            with (
                patch.dict(
                    os.environ,
                    {"BACKUP_RESTORE_EVIDENCE_KEY": self._EVIDENCE_KEY},
                    clear=True,
                ),
                patch(
                    "tools.backup_restore._sha256_file",
                    side_effect=AssertionError("linked manifest was hashed"),
                ),
            ):
                with self.assertRaisesRegex(ValueError, "regular evidence file"):
                    _write_operation_receipt(
                        manifest_path,
                        "restore-operation.json",
                        "restore-postgres",
                        0,
                        1.0,
                    )

    def test_final_manifest_rejects_new_pending_records_after_finalization(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            postgres_output = root / "postgres.dump"
            minio_source = root / "source"
            minio_destination = root / "minio"
            database_url = "postgresql://user:password@db/default"

            def complete_backup(command, _environment=None):
                if command[0] == "pg_dump":
                    postgres_output.write_bytes(b"postgres backup")
                else:
                    minio_destination.mkdir(parents=True, exist_ok=True)
                    (minio_destination / "artifact.bin").write_bytes(b"artifact")
                return {"returncode": 0, "stdout": "", "stderr": ""}

            with (
                patch.dict(
                    os.environ,
                    {
                        "DATABASE_URL": database_url,
                        "BACKUP_ACCEPTANCE_MINIO_DESTINATION": str(minio_destination),
                        "BACKUP_ACCEPTANCE_ISOLATED": "1",
                        "BACKUP_RESTORE_EVIDENCE_KEY": self._EVIDENCE_KEY,
                    },
                    clear=True,
                ),
                patch(
                    "tools.backup_restore.run_backup_command",
                    side_effect=complete_backup,
                ),
            ):
                backup_postgres(database_url, postgres_output)
                mirror_minio(
                    str(minio_source),
                    str(minio_destination),
                    root / "minio-backup-operation.json",
                )
                create_backup_manifest(root)
                finalized_manifest = (root / "manifest.json").read_bytes()
                finalized_receipts = {
                    name: (root / name).read_bytes()
                    for name in (
                        "postgres-backup-operation.json",
                        "minio-backup-operation.json",
                    )
                }

                postgres_output.write_bytes(b"new postgres backup")
                (minio_destination / "artifact.bin").write_bytes(b"new artifact")
                completed_at = datetime.now(timezone.utc) + timedelta(minutes=1)
                _write_pending_operation_receipt(
                    root / "postgres-backup-pending.json",
                    "backup-postgres",
                    0,
                    1.0,
                    [
                        {
                            "path": "postgres.dump",
                            "size": postgres_output.stat().st_size,
                            "sha256": hashlib.sha256(postgres_output.read_bytes()).hexdigest(),
                        },
                    ],
                    completed_at,
                    backup_run_id="c" * 32,
                )
                minio_artifact = minio_destination / "artifact.bin"
                _write_pending_operation_receipt(
                    root / "minio-backup-pending.json",
                    "backup-minio",
                    0,
                    1.0,
                    [
                        {
                            "path": "minio/artifact.bin",
                            "size": minio_artifact.stat().st_size,
                            "sha256": hashlib.sha256(minio_artifact.read_bytes()).hexdigest(),
                        },
                    ],
                    completed_at,
                    backup_run_id="c" * 32,
                )

                with self.assertRaisesRegex(ValueError, "finalized"):
                    create_backup_manifest(root)
                self.assertEqual((root / "manifest.json").read_bytes(), finalized_manifest)
                for name, receipt in finalized_receipts.items():
                    self.assertEqual((root / name).read_bytes(), receipt)

    def test_final_manifest_replaces_an_unfinalized_manifest_after_staging(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            postgres_dump = root / "postgres.dump"
            minio_artifact = root / "minio" / "artifact.bin"
            postgres_dump.write_bytes(b"postgres backup")
            minio_artifact.parent.mkdir()
            minio_artifact.write_bytes(b"artifact")
            completed_at = datetime.now(timezone.utc)

            with patch.dict(
                os.environ,
                {"BACKUP_RESTORE_EVIDENCE_KEY": self._EVIDENCE_KEY},
                clear=True,
            ):
                create_backup_manifest(root)
                _write_pending_operation_receipt(
                    root / "postgres-backup-pending.json",
                    "backup-postgres",
                    0,
                    1.0,
                    [
                        {
                            "path": "postgres.dump",
                            "size": postgres_dump.stat().st_size,
                            "sha256": hashlib.sha256(postgres_dump.read_bytes()).hexdigest(),
                        },
                    ],
                    completed_at,
                    backup_run_id="d" * 32,
                )
                _write_pending_operation_receipt(
                    root / "minio-backup-pending.json",
                    "backup-minio",
                    0,
                    1.0,
                    [
                        {
                            "path": "minio/artifact.bin",
                            "size": minio_artifact.stat().st_size,
                            "sha256": hashlib.sha256(minio_artifact.read_bytes()).hexdigest(),
                        },
                    ],
                    completed_at,
                    backup_run_id="d" * 32,
                )

                manifest = create_backup_manifest(root)

        self.assertEqual(
            [entry["path"] for entry in manifest["files"]],
            ["minio/artifact.bin", "postgres.dump"],
        )

    def test_final_manifest_rejects_pending_records_from_different_backup_runs(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            postgres_dump = root / "postgres.dump"
            minio_artifact = root / "minio" / "artifact.bin"
            postgres_dump.write_bytes(b"postgres backup")
            minio_artifact.parent.mkdir()
            minio_artifact.write_bytes(b"artifact")
            completed_at = datetime.now(timezone.utc)

            with patch.dict(
                os.environ,
                {"BACKUP_RESTORE_EVIDENCE_KEY": self._EVIDENCE_KEY},
                clear=True,
            ):
                _write_pending_operation_receipt(
                    root / "postgres-backup-pending.json",
                    "backup-postgres",
                    0,
                    1.0,
                    [
                        {
                            "path": "postgres.dump",
                            "size": postgres_dump.stat().st_size,
                            "sha256": hashlib.sha256(postgres_dump.read_bytes()).hexdigest(),
                        },
                    ],
                    completed_at,
                    backup_run_id="a" * 32,
                )
                _write_pending_operation_receipt(
                    root / "minio-backup-pending.json",
                    "backup-minio",
                    0,
                    1.0,
                    [
                        {
                            "path": "minio/artifact.bin",
                            "size": minio_artifact.stat().st_size,
                            "sha256": hashlib.sha256(minio_artifact.read_bytes()).hexdigest(),
                        },
                    ],
                    completed_at,
                    backup_run_id="b" * 32,
                )

                with self.assertRaisesRegex(ValueError, "same backup run"):
                    create_backup_manifest(root)

    def test_final_manifest_rejects_a_staged_backup_without_minio_objects(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            postgres_output = root / "postgres.dump"
            minio_source = root / "source"
            minio_destination = root / "minio"
            database_url = "postgresql://user:password@db/default"

            def complete_backup(command, _environment=None):
                if command[0] == "pg_dump":
                    postgres_output.write_bytes(b"postgres backup")
                return {"returncode": 0, "stdout": "", "stderr": ""}

            with (
                patch.dict(
                    os.environ,
                    {
                        "DATABASE_URL": database_url,
                        "BACKUP_ACCEPTANCE_MINIO_DESTINATION": str(minio_destination),
                        "BACKUP_ACCEPTANCE_ISOLATED": "1",
                        "BACKUP_RESTORE_EVIDENCE_KEY": self._EVIDENCE_KEY,
                    },
                    clear=True,
                ),
                patch(
                    "tools.backup_restore.run_backup_command",
                    side_effect=complete_backup,
                ),
            ):
                backup_postgres(database_url, postgres_output)
                mirror_minio(
                    str(minio_source),
                    str(minio_destination),
                    root / "minio-backup-operation.json",
                )
                with self.assertRaisesRegex(ValueError, "MinIO"):
                    create_backup_manifest(root)
            manifest_created = (root / "manifest.json").is_file()
        self.assertFalse(manifest_created)

    def test_final_manifest_rejects_staged_evidence_hash_drift(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            postgres_output = root / "postgres.dump"
            minio_source = root / "source"
            minio_destination = root / "minio"
            database_url = "postgresql://user:password@db/default"

            def complete_backup(command, _environment=None):
                if command[0] == "pg_dump":
                    postgres_output.write_bytes(b"postgres backup")
                else:
                    minio_destination.mkdir(parents=True, exist_ok=True)
                    (minio_destination / "artifact.bin").write_bytes(b"artifact")
                return {"returncode": 0, "stdout": "", "stderr": ""}

            with (
                patch.dict(
                    os.environ,
                    {
                        "DATABASE_URL": database_url,
                        "BACKUP_ACCEPTANCE_MINIO_DESTINATION": str(minio_destination),
                        "BACKUP_ACCEPTANCE_ISOLATED": "1",
                        "BACKUP_RESTORE_EVIDENCE_KEY": self._EVIDENCE_KEY,
                    },
                    clear=True,
                ),
                patch(
                    "tools.backup_restore.run_backup_command",
                    side_effect=complete_backup,
                ),
            ):
                backup_postgres(database_url, postgres_output)
                mirror_minio(
                    str(minio_source),
                    str(minio_destination),
                    root / "minio-backup-operation.json",
                )
                for evidence_file in (
                    postgres_output,
                    minio_destination / "artifact.bin",
                ):
                    original = evidence_file.read_bytes()
                    evidence_file.write_bytes(original + b"-tampered")
                    with self.assertRaisesRegex(ValueError, "pending"):
                        create_backup_manifest(root)
                    self.assertFalse((root / "manifest.json").is_file())
                    evidence_file.write_bytes(original)

    def test_mirror_minio_requires_postgres_pending_in_the_receipt_root(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            receipt_root = root / "receipt-root"
            destination = receipt_root / "minio"
            with (
                patch.dict(
                    os.environ,
                    {
                        "BACKUP_ACCEPTANCE_MINIO_DESTINATION": str(destination),
                        "BACKUP_ACCEPTANCE_ISOLATED": "1",
                        "BACKUP_RESTORE_EVIDENCE_KEY": self._EVIDENCE_KEY,
                    },
                    clear=True,
                ),
                patch("tools.backup_restore.run_backup_command") as mirror,
            ):
                with self.assertRaisesRegex(ValueError, "PostgreSQL"):
                    mirror_minio(
                        str(root / "source"),
                        str(destination),
                        receipt_root / "minio-backup-operation.json",
                    )
        mirror.assert_not_called()

    def test_verify_restore_rejects_zero_checked_minio_backup_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            backup_root = root / "backup"
            backup_root.mkdir()
            (backup_root / "postgres.dump").write_bytes(b"backup")
            restored_minio = root / "restored-minio"
            restored_minio.mkdir()
            source = "postgresql://user:password@db/source"
            target = "postgresql://user:password@db/restored"
            snapshots = self._representative_snapshot()
            with (
                patch.dict(
                    os.environ,
                    self._restore_environment(target, str(restored_minio)),
                    clear=True,
                ),
                patch(
                    "tools.backup_restore.collect_database_snapshot",
                    side_effect=[snapshots, snapshots],
                ),
            ):
                create_backup_manifest(backup_root)
                self._write_signed_backup_completion_receipts(backup_root)
                self._write_signed_restore_receipts(backup_root)
                result = verify_restore(
                    source,
                    target,
                    backup_root / "manifest.json",
                    restored_minio,
                    root / "restore-result.json",
                )
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["object_hashes"]["checked"], 0)

    def test_verify_restore_requires_both_backup_completion_receipts(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            backup_root = root / "backup"
            (backup_root / "minio").mkdir(parents=True)
            (backup_root / "postgres.dump").write_bytes(b"backup")
            source = "postgresql://user:password@db/source"
            target = "postgresql://user:password@db/restored"
            snapshots = self._representative_snapshot()
            with (
                patch.dict(
                    os.environ,
                    self._restore_environment(target, str(backup_root / "minio")),
                    clear=True,
                ),
                patch(
                    "tools.backup_restore.collect_database_snapshot",
                    side_effect=[snapshots, snapshots],
                ),
            ):
                create_backup_manifest(backup_root)
                self._write_signed_restore_receipts(backup_root)
                result = verify_restore(
                    source,
                    target,
                    backup_root / "manifest.json",
                    backup_root / "minio",
                    root / "restore-result.json",
                )
        self.assertEqual(result["status"], "failed")
        self.assertFalse(result["rpo_passed"])

    def test_verify_restore_rejects_post_hoc_manifest_signature_as_rpo_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            backup_root = root / "backup"
            (backup_root / "minio").mkdir(parents=True)
            (backup_root / "postgres.dump").write_bytes(b"old backup")
            source = "postgresql://user:password@db/source"
            target = "postgresql://user:password@db/restored"
            snapshots = self._representative_snapshot()
            with (
                patch.dict(
                    os.environ,
                    self._restore_environment(target, str(backup_root / "minio")),
                    clear=True,
                ),
                patch(
                    "tools.backup_restore.collect_database_snapshot",
                    side_effect=[snapshots, snapshots],
                ),
            ):
                create_backup_manifest(backup_root)
                _write_operation_receipt(
                    backup_root / "manifest.json",
                    "backup-operation.json",
                    "backup",
                    0,
                    0.0,
                )
                self._write_signed_restore_receipts(backup_root)
                result = verify_restore(
                    source,
                    target,
                    backup_root / "manifest.json",
                    backup_root / "minio",
                    root / "restore-result.json",
                )
        self.assertEqual(result["status"], "failed")
        self.assertFalse(result["rpo_passed"])

    def test_verify_restore_rejects_tampered_backup_receipt_or_manifest(self):
        for tampered_file in (
            "postgres-backup-operation.json",
            "manifest.json",
        ):
            with self.subTest(tampered_file=tampered_file), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                backup_root = root / "backup"
                (backup_root / "minio").mkdir(parents=True)
                (backup_root / "postgres.dump").write_bytes(b"backup")
                source = "postgresql://user:password@db/source"
                target = "postgresql://user:password@db/restored"
                snapshots = self._representative_snapshot()
                with (
                    patch.dict(
                        os.environ,
                        self._restore_environment(target, str(backup_root / "minio")),
                        clear=True,
                    ),
                    patch(
                        "tools.backup_restore.collect_database_snapshot",
                        side_effect=[snapshots, snapshots],
                    ),
                ):
                    create_backup_manifest(backup_root)
                    self._write_signed_backup_completion_receipts(backup_root)
                    self._write_signed_restore_receipts(backup_root)
                    path = backup_root / tampered_file
                    payload = json.loads(path.read_text(encoding="utf-8"))
                    if tampered_file == "manifest.json":
                        payload["files"].append({"path": "extra", "sha256": "0"})
                    else:
                        payload["duration_seconds"] = 2.0
                    path.write_text(json.dumps(payload), encoding="utf-8")
                    result = verify_restore(
                        source,
                        target,
                        backup_root / "manifest.json",
                        backup_root / "minio",
                        root / "restore-result.json",
                    )
            self.assertEqual(result["status"], "failed")
            self.assertFalse(result["rpo_passed"])

    def test_verify_restore_uses_the_older_backup_completion_timestamp_for_rpo(self):
        reference = datetime(2026, 7, 29, 12, tzinfo=timezone.utc)

        class FixedDatetime(datetime):
            @classmethod
            def now(cls, tz=None):
                return reference if tz is not None else reference.replace(tzinfo=None)

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            backup_root = root / "backup"
            (backup_root / "minio").mkdir(parents=True)
            source = "postgresql://user:password@db/source"
            target = "postgresql://user:password@db/restored"
            snapshots = self._representative_snapshot()
            with (
                patch.dict(
                    os.environ,
                    self._restore_environment(target, str(backup_root / "minio")),
                    clear=True,
                ),
                patch("tools.backup_restore.datetime", FixedDatetime),
                patch(
                    "tools.backup_restore.collect_database_snapshot",
                    side_effect=[snapshots, snapshots],
                ),
            ):
                (backup_root / "postgres.dump").write_bytes(b"backup")
                create_backup_manifest(backup_root)
                self._write_signed_backup_completion_receipts(
                    backup_root,
                    postgres_completed_at=reference - timedelta(minutes=20),
                    minio_completed_at=reference - timedelta(minutes=5),
                )
                self._write_signed_restore_receipts(backup_root)
                result = verify_restore(
                    source,
                    target,
                    backup_root / "manifest.json",
                    backup_root / "minio",
                    root / "restore-result.json",
                )
        self.assertTrue(result["rpo_passed"])
        self.assertEqual(result["rpo_seconds"], 1200.0)

    def test_restore_treats_implicit_postgres_port_as_the_same_source_target(self):
        with tempfile.TemporaryDirectory() as directory:
            dump = Path(directory) / "postgres.dump"
            dump.write_bytes(b"backup")
            target = "postgresql://user:password@db/acceptance_restore"
            source = "postgresql://source:source-password@db:5432/acceptance_restore"
            with (
                patch.dict(
                    os.environ,
                    {
                        "DATABASE_URL": "postgresql://user:password@db/default",
                        "RESTORE_ACCEPTANCE_DATABASE_URL": target,
                        "RESTORE_ACCEPTANCE_ISOLATED": "1",
                    },
                    clear=True,
                ),
                patch("tools.backup_restore.run_backup_command") as run_command,
            ):
                run_command.return_value = {
                    "returncode": 0,
                    "stdout": "",
                    "stderr": "",
                }
                with self.assertRaisesRegex(ValueError, "isolated"):
                    restore_postgres(target, dump, source)
        run_command.assert_not_called()

    def test_backup_postgres_allows_the_configured_default_database_as_read_only_source(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "backup.dump"
            default_database = "postgresql://user:password@db:5432/default"

            def complete_dump(_command, _environment):
                output.write_bytes(b"backup")
                return {"returncode": 0, "stdout": "", "stderr": ""}

            with (
                patch.dict(
                    os.environ,
                    {
                        "DATABASE_URL": default_database,
                        "BACKUP_RESTORE_EVIDENCE_KEY": self._EVIDENCE_KEY,
                    },
                    clear=True,
                ),
                patch(
                    "tools.backup_restore.run_backup_command",
                    side_effect=complete_dump,
                ) as run_command,
            ):
                result = backup_postgres(default_database, output)
                receipt_created = (output.parent / "postgres-backup-pending.json").is_file()
        self.assertEqual(result["returncode"], 0)
        self.assertEqual(run_command.call_args.args[0][0], "pg_dump")
        self.assertTrue(receipt_created)

    def test_verify_restore_requires_the_confirmed_isolated_target_before_snapshot(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = root / "manifest.json"
            manifest.write_text(
                '{"created_at": "2026-07-20T12:00:00Z", "files": []}',
                encoding="utf-8",
            )
            source = "postgresql://user:password@db/source"
            target = "postgresql://user:password@db/restored"
            with patch("tools.backup_restore.collect_database_snapshot") as collect:
                collect.return_value = {
                    "table_counts": {"retained": 1},
                    "foreign_key_violations": [],
                }
                result = verify_restore(source, target, manifest, root, root / "result.json")
        self.assertEqual(result["status"], "failed")
        collect.assert_not_called()

    def test_verify_restore_rejects_a_minio_target_that_aliases_the_source(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = root / "manifest.json"
            manifest.write_text(
                '{"created_at": "2026-07-20T12:00:00Z", "files": []}',
                encoding="utf-8",
            )
            source = "postgresql://user:password@db/source"
            target = "postgresql://user:password@db/restored"
            minio_source = "restored/ml-platform"
            with (
                patch.dict(
                    os.environ,
                    {
                        "DATABASE_URL": "postgresql://user:password@db/default",
                        "RESTORE_ACCEPTANCE_DATABASE_URL": target,
                        "RESTORE_ACCEPTANCE_ISOLATED": "1",
                        "RESTORE_ACCEPTANCE_MINIO_DESTINATION": minio_source,
                        "RESTORE_SOURCE_MINIO": minio_source,
                        "BACKUP_RESTORE_EVIDENCE_KEY": "test-evidence-key",
                    },
                    clear=True,
                ),
                patch("tools.backup_restore.collect_database_snapshot") as collect,
            ):
                collect.return_value = {
                    "table_counts": {"retained": 1},
                    "foreign_key_violations": [],
                }
                result = verify_restore(source, target, manifest, minio_source, root / "result.json")
        self.assertEqual(result["status"], "failed")
        collect.assert_not_called()

    def test_verify_restore_rejects_fabricated_short_timing_receipts(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = root / "manifest.json"
            manifest.write_text(
                json.dumps(
                    {
                        "created_at": datetime.now(timezone.utc).isoformat(),
                        "files": [],
                    },
                ),
                encoding="utf-8",
            )
            for name in ("restore-operation.json", "minio-restore-operation.json"):
                (root / name).write_text(
                    '{"returncode": 0, "duration_seconds": 0.01}',
                    encoding="utf-8",
                )
            source = "postgresql://user:password@db/source"
            target = "postgresql://user:password@db/restored"
            snapshots = {
                "table_counts": {"retained": 1},
                "foreign_key_violations": [],
            }
            with (
                patch.dict(
                    os.environ,
                    {
                        "DATABASE_URL": "postgresql://user:password@db/default",
                        "RESTORE_ACCEPTANCE_DATABASE_URL": target,
                        "RESTORE_ACCEPTANCE_ISOLATED": "1",
                        "BACKUP_RESTORE_EVIDENCE_KEY": "test-evidence-key",
                    },
                    clear=True,
                ),
                patch(
                    "tools.backup_restore.collect_database_snapshot",
                    side_effect=[snapshots, snapshots],
                ),
            ):
                result = verify_restore(source, target, manifest, root, root / "result.json")
        self.assertEqual(result["status"], "failed")
        self.assertFalse(result["rto_passed"])

    def test_manifest_creation_rejects_a_caller_selected_timestamp(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, "generated"):
                create_backup_manifest(
                    Path(directory),
                    datetime(2026, 7, 20, 12, tzinfo=timezone.utc),
                )

    def test_run_alembic_rejects_the_default_database_before_subprocess(self):
        default_database = "postgresql://user:password@db:5432/default"
        with (
            patch.dict(
                os.environ,
                {
                    "DATABASE_URL": default_database,
                    "UPGRADE_ACCEPTANCE_DATABASE_URL": default_database,
                    "UPGRADE_ACCEPTANCE_ISOLATED": "1",
                },
                clear=True,
            ),
            patch("tools.upgrade_fixture.subprocess.run") as subprocess_run,
        ):
            with self.assertRaisesRegex(ValueError, "isolated"):
                run_alembic(default_database, "current")
        subprocess_run.assert_not_called()

    def test_upgrade_fixture_direct_cli_loads_the_tools_package(self):
        script = Path(__file__).parents[1] / "tools" / "upgrade_fixture.py"
        completed = subprocess.run(
            [sys.executable, str(script), "--help"],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)

    def test_create_upgrade_fixture_allows_empty_n_minus_one_database_before_seed(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "fixture.json"
            database_url = "postgresql://user:password@db/upgrade_acceptance"
            completed = type("Completed", (), {"returncode": 0, "stdout": ""})()
            n_minus_one = type(
                "Completed",
                (),
                {"returncode": 0, "stdout": "\n".join(sorted(EXPECTED_N_MINUS_ONE_HEADS))},
            )()
            with (
                patch.dict(
                    os.environ,
                    {
                        "DATABASE_URL": "postgresql://user:password@db/default",
                        "UPGRADE_ACCEPTANCE_DATABASE_URL": database_url,
                        "UPGRADE_ACCEPTANCE_ISOLATED": "1",
                    },
                    clear=True,
                ),
                patch(
                    "tools.upgrade_fixture.run_alembic",
                    side_effect=[completed, n_minus_one],
                ),
                patch("tools.upgrade_fixture.snapshot_database") as snapshot_database,
            ):
                result = create_upgrade_fixture(database_url, EXPECTED_N_MINUS_ONE, output)
        self.assertEqual(result["status"], "passed")
        self.assertTrue(result["seed_required"])
        snapshot_database.assert_not_called()

    def test_create_upgrade_fixture_requires_the_exact_frozen_current_revision(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "fixture.json"
            database_url = "postgresql://user:password@db/upgrade_acceptance"
            completed = type("Completed", (), {"returncode": 0, "stdout": ""})()
            wrong_current = type(
                "Completed",
                (),
                {"returncode": 0, "stdout": "20260720_09_production_inference"},
            )()
            with (
                patch.dict(
                    os.environ,
                    {
                        "DATABASE_URL": "postgresql://user:password@db/default",
                        "UPGRADE_ACCEPTANCE_DATABASE_URL": database_url,
                        "UPGRADE_ACCEPTANCE_ISOLATED": "1",
                    },
                    clear=True,
                ),
                patch(
                    "tools.upgrade_fixture.run_alembic",
                    side_effect=[completed, wrong_current],
                ),
            ):
                result = create_upgrade_fixture(database_url, EXPECTED_N_MINUS_ONE, output)
        self.assertEqual(result["status"], "failed")

    def test_execute_upgrade_rejects_multiple_start_revisions(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "result.json"
            database_url = "postgresql://user:password@db/upgrade_acceptance"
            duplicate_start = type(
                "Completed",
                (),
                {"returncode": 0, "stdout": f"{EXPECTED_N_MINUS_ONE}\n{EXPECTED_N_MINUS_ONE}"},
            )()
            completed = type("Completed", (), {"returncode": 0, "stdout": ""})()
            frozen_head = type(
                "Completed",
                (),
                {"returncode": 0, "stdout": f"{EXPECTED_HEAD} (head)"},
            )()
            snapshot = {
                "status": "passed",
                "table_counts": {
                    "users": 1,
                    "projects": 1,
                    "workflows": 1,
                    "model_library": 1,
                },
                "foreign_key_violations": [],
            }
            with (
                patch.dict(
                    os.environ,
                    {
                        "DATABASE_URL": "postgresql://user:password@db/default",
                        "UPGRADE_ACCEPTANCE_DATABASE_URL": database_url,
                        "UPGRADE_ACCEPTANCE_ISOLATED": "1",
                    },
                    clear=True,
                ),
                patch(
                    "tools.upgrade_fixture.run_alembic",
                    side_effect=[duplicate_start, completed, completed, frozen_head, completed],
                ) as run,
                patch("tools.upgrade_fixture.snapshot_database", side_effect=[snapshot, snapshot]),
            ):
                result = execute_upgrade(database_url, EXPECTED_HEAD, output)
        self.assertEqual(result["status"], "failed")
        self.assertEqual(run.call_count, 1)

    def test_execute_upgrade_rejects_multiple_frozen_heads(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "result.json"
            database_url = "postgresql://user:password@db/upgrade_acceptance"
            frozen_start = type(
                "Completed",
                (),
                {"returncode": 0, "stdout": EXPECTED_N_MINUS_ONE},
            )()
            completed = type("Completed", (), {"returncode": 0, "stdout": ""})()
            duplicate_head = type(
                "Completed",
                (),
                {"returncode": 0, "stdout": f"{EXPECTED_HEAD} (head)\n{EXPECTED_HEAD} (head)"},
            )()
            snapshot = {
                "status": "passed",
                "table_counts": {
                    "users": 1,
                    "projects": 1,
                    "workflows": 1,
                    "model_library": 1,
                },
                "foreign_key_violations": [],
            }
            with (
                patch.dict(
                    os.environ,
                    {
                        "DATABASE_URL": "postgresql://user:password@db/default",
                        "UPGRADE_ACCEPTANCE_DATABASE_URL": database_url,
                        "UPGRADE_ACCEPTANCE_ISOLATED": "1",
                    },
                    clear=True,
                ),
                patch(
                    "tools.upgrade_fixture.run_alembic",
                    side_effect=[frozen_start, completed, completed, duplicate_head, completed],
                ),
                patch("tools.upgrade_fixture.snapshot_database", side_effect=[snapshot, snapshot]),
            ):
                result = execute_upgrade(database_url, EXPECTED_HEAD, output)
        self.assertEqual(result["status"], "failed")


class UpgradeFixtureTests(unittest.TestCase):
    @staticmethod
    def _environment(database_url: str) -> dict[str, str]:
        return {
            "DATABASE_URL": "postgresql://user:password@db/default",
            "UPGRADE_ACCEPTANCE_DATABASE_URL": database_url,
            "UPGRADE_ACCEPTANCE_ISOLATED": "1",
        }

    @staticmethod
    def _snapshot(**extra_counts: int) -> dict[str, object]:
        return {
            "status": "passed",
            "table_counts": {
                "users": 1,
                "projects": 1,
                "workflows": 1,
                "model_library": 1,
                **extra_counts,
            },
            "foreign_key_violations": [],
        }

    def test_upgrade_result_requires_head_repeatability_and_no_data_loss(self):
        result = {
            "from_revision": EXPECTED_N_MINUS_ONE,
            "to_revision": EXPECTED_HEAD,
            "first_upgrade": "ok",
            "second_upgrade": "ok",
            "alembic_check": "ok",
            "row_counts_equal": True,
            "business_data_loss": False,
            "pre_upgrade_snapshot_valid": True,
            "post_upgrade_snapshot_valid": True,
        }
        self.assertEqual(validate_upgrade_result(result)["status"], "passed")

    def test_release_n_minus_one_contract_targets_current_merge_head(self):
        self.assertEqual(EXPECTED_N_MINUS_ONE, "20260720_10_security_notifications")
        self.assertEqual(EXPECTED_HEAD, "20260826_13")

    def test_wrong_target_revision_fails_closed(self):
        with self.assertRaises(ValueError):
            validate_upgrade_result(
                {"from_revision": EXPECTED_N_MINUS_ONE, "to_revision": "other"},
            )

    def test_upgrade_record_never_serializes_database_credentials(self):
        with tempfile.TemporaryDirectory() as directory:
            database_url = "postgresql://user:password@db/app"
            with patch.dict(
                os.environ,
                self._environment(database_url),
                clear=True,
            ):
                output = create_upgrade_record(
                    Path(directory) / "upgrade.json",
                    database_url,
                )
                serialized = output.read_text(encoding="utf-8")
        self.assertNotIn("user:password", serialized)
        self.assertEqual(json.loads(serialized)["database_url"], "[redacted]")

    def test_snapshot_and_upgrade_cli_never_write_database_url(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database_url = "postgresql://user:password@db/upgrade_acceptance"
            snapshot_data = self._snapshot()
            snapshot_output = root / "snapshot.json"
            with patch.dict(
                os.environ,
                self._environment(database_url),
                clear=True,
            ):
                with patch(
                    "tools.upgrade_fixture.collect_database_snapshot",
                    return_value={
                        "table_counts": snapshot_data["table_counts"],
                        "foreign_key_violations": [],
                    },
                ):
                    snapshot = snapshot_database(database_url)
                with (
                    patch("tools.upgrade_fixture.snapshot_database", return_value=snapshot),
                    patch("builtins.print"),
                ):
                    self.assertEqual(
                        upgrade_fixture_main(
                            [
                                "snapshot",
                                "--database-url",
                                database_url,
                                "--output",
                                str(snapshot_output),
                            ],
                        ),
                        0,
                    )
                with patch("tools.upgrade_fixture.execute_upgrade") as upgrade:
                    upgrade.return_value = {"status": "passed"}
                    self.assertEqual(
                        upgrade_fixture_main(
                            [
                                "upgrade",
                                "--database-url",
                                database_url,
                                "--target",
                                EXPECTED_HEAD,
                                "--output",
                                str(root / "result.json"),
                            ],
                        ),
                        0,
                    )
            serialized = snapshot_output.read_text(encoding="utf-8")
        self.assertEqual(snapshot["table_counts"], snapshot_data["table_counts"])
        self.assertNotIn("user:password", serialized)

    def test_execute_upgrade_requires_two_upgrades_and_clean_check(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "result.json"
            database_url = "postgresql://user:password@db/upgrade_acceptance"
            n_minus_one = type(
                "Completed",
                (),
                {"returncode": 0, "stdout": EXPECTED_N_MINUS_ONE},
            )()
            completed = type(
                "Completed",
                (),
                {"returncode": 0, "stdout": f"{EXPECTED_HEAD} (head)"},
            )()
            snapshot = self._snapshot()
            with (
                patch.dict(os.environ, self._environment(database_url), clear=True),
                patch(
                    "tools.upgrade_fixture.run_alembic",
                    side_effect=[n_minus_one, completed, completed, completed, completed],
                ) as run_alembic,
                patch(
                    "tools.upgrade_fixture.snapshot_database",
                    side_effect=[snapshot, snapshot],
                ),
            ):
                result = execute_upgrade(
                    database_url,
                    EXPECTED_HEAD,
                    output,
                )
            serialized = output.read_text(encoding="utf-8")
        self.assertEqual(result["status"], "passed")
        self.assertEqual(run_alembic.call_count, 5)
        self.assertNotIn("user:password", serialized)

    def test_execute_upgrade_allows_new_empty_migration_tables(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "result.json"
            database_url = "postgresql://user:password@db/upgrade_acceptance"
            n_minus_one = type(
                "Completed",
                (),
                {"returncode": 0, "stdout": EXPECTED_N_MINUS_ONE},
            )()
            completed = type(
                "Completed",
                (),
                {"returncode": 0, "stdout": f"{EXPECTED_HEAD} (head)"},
            )()
            before = self._snapshot()
            after = self._snapshot(notification_outbox=0)
            with (
                patch.dict(os.environ, self._environment(database_url), clear=True),
                patch(
                    "tools.upgrade_fixture.run_alembic",
                    side_effect=[n_minus_one, completed, completed, completed, completed],
                ),
                patch(
                    "tools.upgrade_fixture.snapshot_database",
                    side_effect=[before, after],
                ),
            ):
                result = execute_upgrade(
                    database_url,
                    EXPECTED_HEAD,
                    output,
                )
        self.assertEqual(result["status"], "passed")

    def test_execute_upgrade_rejects_all_zero_snapshot_before_migrating(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "result.json"
            database_url = "postgresql://user:password@db/upgrade_acceptance"
            n_minus_one = type(
                "Completed",
                (),
                {"returncode": 0, "stdout": EXPECTED_N_MINUS_ONE},
            )()
            completed = type(
                "Completed",
                (),
                {"returncode": 0, "stdout": EXPECTED_HEAD},
            )()
            empty_snapshot = {
                "status": "passed",
                "table_counts": {"users": 0, "projects": 0},
                "foreign_key_violations": [],
            }
            with (
                patch.dict(os.environ, self._environment(database_url), clear=True),
                patch(
                    "tools.upgrade_fixture.run_alembic",
                    side_effect=[n_minus_one, completed, completed, completed, completed],
                ) as run_alembic,
                patch(
                    "tools.upgrade_fixture.snapshot_database",
                    return_value=empty_snapshot,
                ),
            ):
                result = execute_upgrade(
                    database_url,
                    EXPECTED_HEAD,
                    output,
                )
        self.assertEqual(result["status"], "failed")
        self.assertEqual(run_alembic.call_count, 1)
        self.assertEqual(run_alembic.call_args.args[1:], ("current",))

    def test_upgrade_cli_rejects_default_database_url_and_verify_reruns_gates(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch.dict(
                os.environ,
                {"DATABASE_URL": "sqlite:///:memory:"},
                clear=True,
            ):
                with self.assertRaises(ValueError):
                    upgrade_fixture_main(["snapshot", "--output", str(root / "snapshot.json")])

            before = root / "before.json"
            database_url = "postgresql://user:password@db/upgrade_acceptance"
            before.write_text(json.dumps(self._snapshot()), encoding="utf-8")
            n_minus_one = type(
                "Completed",
                (),
                {"returncode": 0, "stdout": EXPECTED_N_MINUS_ONE},
            )()
            completed = type(
                "Completed",
                (),
                {"returncode": 0, "stdout": EXPECTED_HEAD},
            )()
            snapshot = self._snapshot()
            with (
                patch.dict(os.environ, self._environment(database_url), clear=True),
                patch(
                    "tools.upgrade_fixture.run_alembic",
                    side_effect=[n_minus_one, completed, completed, completed, completed],
                ) as run_alembic,
                patch("tools.upgrade_fixture.snapshot_database", return_value=snapshot),
            ):
                result = verify_upgrade(
                    before,
                    database_url,
                    root / "verify.json",
                )
        self.assertEqual(result["status"], "passed")
        self.assertEqual(run_alembic.call_count, 5)

    def test_verify_upgrade_rejects_failed_or_empty_snapshot_before_migrating(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "verify.json"
            database_url = "postgresql://user:password@db/upgrade_acceptance"
            with patch.dict(
                os.environ,
                self._environment(database_url),
                clear=True,
            ):
                for payload in (
                    {"status": "failed", "table_counts": {"retained": 1}},
                    {"status": "passed", "table_counts": {}, "foreign_key_violations": []},
                    {
                        "status": "passed",
                        "table_counts": {"users": 0, "projects": 0},
                        "foreign_key_violations": [],
                    },
                    {
                        "status": "passed",
                        "table_counts": {"alembic_version": 1},
                        "foreign_key_violations": [],
                    },
                ):
                    before = root / "before.json"
                    before.write_text(json.dumps(payload), encoding="utf-8")
                    with patch("tools.upgrade_fixture.run_alembic") as run_alembic:
                        result = verify_upgrade(before, database_url, output)
                    self.assertEqual(result["status"], "failed")
                    run_alembic.assert_not_called()

    def test_upgrade_cli_requires_explicit_isolated_database_confirmation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database_url = f"sqlite:///{(root / 'upgrade.db').as_posix()}"
            with patch.dict(
                os.environ,
                {
                    "UPGRADE_ACCEPTANCE_DATABASE_URL": database_url,
                    "UPGRADE_ACCEPTANCE_ISOLATED": "0",
                },
                clear=True,
            ):
                with self.assertRaises(ValueError):
                    upgrade_fixture_main(
                        [
                            "snapshot",
                            "--database-url",
                            database_url,
                            "--output",
                            str(root / "snapshot.json"),
                        ],
                    )

    def test_verify_upgrade_fails_before_any_upgrade_from_the_wrong_revision(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            before = root / "before.json"
            database_url = "postgresql://user:password@db/upgrade_acceptance"
            before.write_text(json.dumps(self._snapshot()), encoding="utf-8")
            wrong_revision = type(
                "Completed",
                (),
                {"returncode": 0, "stdout": "20260720_09_production_inference"},
            )()
            with (
                patch.dict(os.environ, self._environment(database_url), clear=True),
                patch(
                    "tools.upgrade_fixture.run_alembic",
                    return_value=wrong_revision,
                ) as run_alembic,
            ):
                result = verify_upgrade(before, database_url, root / "verify.json")
        self.assertEqual(result["status"], "failed")
        self.assertEqual(run_alembic.call_args.args[1:], ("current",))
        self.assertEqual(run_alembic.call_count, 1)


class NotificationReceiverTests(unittest.TestCase):
    @staticmethod
    def _post(url, payload):
        request = Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(request, timeout=3) as response:
            return response.status

    def test_receiver_records_redacted_json_and_can_assert_event_type(self):
        receiver = NotificationReceiver()
        with receiver.running() as url:
            status = self._post(
                url,
                {
                    "event_type": "rollout.completed",
                    "token": "must-not-persist",
                    "predictions": [{"value": 1}],
                },
            )
        self.assertEqual(status, 202)
        self.assertEqual(receiver.events[0]["payload"]["event_type"], "rollout.completed")
        self.assertEqual(receiver.events[0]["payload"]["token"], "[redacted]")
        self.assertEqual(receiver.events[0]["payload"]["predictions"], "[redacted]")
        receiver.assert_event_type("rollout.completed")

    def test_receiver_bounded_storage_keeps_newest_events(self):
        receiver = NotificationReceiver(max_events=1)
        with receiver.running() as url:
            self._post(url, {"event_type": "first"})
            self._post(url, {"event_type": "second"})
        self.assertEqual(len(receiver.events), 1)
        self.assertEqual(receiver.events[0]["payload"]["event_type"], "second")

    def test_receiver_rejects_negative_content_length(self):
        receiver = NotificationReceiver()
        with receiver.running() as url:
            parsed = urlsplit(url)
            connection = HTTPConnection(parsed.hostname, parsed.port, timeout=3)
            connection.request(
                "POST",
                parsed.path,
                body=b"",
                headers={"Content-Length": "-1"},
            )
            response = connection.getresponse()
            status = response.status
            response.read()
            connection.close()
        self.assertEqual(status, 400)
        self.assertEqual(receiver.events, [])

    def test_receiver_redacts_api_keys_and_bearer_credentials_in_values(self):
        receiver = NotificationReceiver()
        with receiver.running() as url:
            status = self._post(
                url,
                {
                    "event_type": "rollout.completed",
                    "api_key": "mli_should-not-persist",
                    "detail": "Authorization: Bearer bearer-should-not-persist",
                },
            )
        serialized = json.dumps(receiver.events)
        self.assertEqual(status, 202)
        self.assertNotIn("mli_should-not-persist", serialized)
        self.assertNotIn("bearer-should-not-persist", serialized)

    def test_receiver_redacts_raw_url_userinfo_and_basic_credentials(self):
        receiver = NotificationReceiver()
        with receiver.running() as url:
            status = self._post(
                url,
                {
                    "event_type": "rollout.completed",
                    "detail": "https://user:pa@ss@receiver.invalid Authorization: Basic YmFzaWMtcHJvYmU=",
                },
            )
        serialized = json.dumps(receiver.events)
        self.assertEqual(status, 202)
        self.assertNotIn("pa@ss", serialized)
        self.assertNotIn("YmFzaWMtcHJvYmU", serialized)

    def test_receiver_redacts_nested_camel_case_api_and_access_keys(self):
        receiver = NotificationReceiver()
        with receiver.running() as url:
            status = self._post(
                url,
                {
                    "event_type": "rollout.completed",
                    "nested": {
                        "apiKey": "nested-api-probe",
                        "accessKey": "nested-access-probe",
                    },
                },
            )
        serialized = json.dumps(receiver.events)
        self.assertEqual(status, 202)
        self.assertNotIn("nested-api-probe", serialized)
        self.assertNotIn("nested-access-probe", serialized)


if __name__ == "__main__":
    unittest.main()
