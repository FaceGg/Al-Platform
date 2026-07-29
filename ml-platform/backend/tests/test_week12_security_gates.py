import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools.security_scans import (
    HttpResponse,
    main as security_scans_main,
    redact_scan_output,
    run_all,
    run_scan,
    run_web_gate,
)


class SecurityGateTests(unittest.TestCase):
    def test_scan_failure_is_preserved_as_failed_gate(self):
        with patch("tools.security_scans.subprocess.run") as run:
            run.return_value.returncode = 1
            run.return_value.stdout = "vulnerability: test-password"
            run.return_value.stderr = ""
            result = run_scan(["scanner", "fs", "."])
        self.assertEqual(result["status"], "failed")
        self.assertNotIn("test-password", json.dumps(result))

    def test_redaction_removes_urls_credentials_and_tokens(self):
        value = redact_scan_output(
            "postgresql://user:pass@db/app token=abc Authorization: Bearer xyz",
        )
        self.assertNotIn("user:pass@", value)
        self.assertNotIn("abc", value)
        self.assertNotIn("xyz", value)

    def test_redaction_removes_formatted_json_secret_values(self):
        value = redact_scan_output('{"Secret": "json-value", "status": "failed"}')
        self.assertNotIn("json-value", value)

    def test_redaction_removes_compound_json_secret_keys(self):
        value = redact_scan_output(
            '{"access_token": "json-probe", "refreshToken": "second-probe"}',
        )
        self.assertNotIn("json-probe", value)
        self.assertNotIn("second-probe", value)

    def test_redaction_removes_unquoted_compound_secret_assignments(self):
        value = redact_scan_output(
            "access_token=assignment-probe refreshToken: refresh-probe",
        )
        self.assertNotIn("assignment-probe", value)
        self.assertNotIn("refresh-probe", value)

    def test_redaction_removes_nested_camel_case_key_values(self):
        value = redact_scan_output(
            '{"nested": {"apiKey": "nested-api-probe", "accessKey": "nested-access-probe"}}',
        )
        self.assertNotIn("nested-api-probe", value)
        self.assertNotIn("nested-access-probe", value)

    def test_redaction_removes_empty_username_redis_credentials(self):
        value = redact_scan_output("redis://:secret@cache/0")
        self.assertNotIn(":secret@", value)

    def test_redaction_removes_raw_userinfo_client_secret_and_basic_credentials(self):
        value = redact_scan_output(
            "https://user:pa@ss@receiver.invalid client_secret: probe-value Authorization: Basic YmFzaWMtcHJvYmU=",
        )
        self.assertNotIn("pa@ss", value)
        self.assertNotIn("probe-value", value)
        self.assertNotIn("YmFzaWMtcHJvYmU", value)

    def test_scan_record_redacts_credential_bearing_command_arguments(self):
        with patch("tools.security_scans.subprocess.run") as run:
            run.return_value.returncode = 0
            run.return_value.stdout = "clean"
            run.return_value.stderr = ""
            result = run_scan(["scanner", "--token=abc", "postgresql://u:p@db/app"])
        serialized = json.dumps(result)
        self.assertNotIn("token=abc", serialized)
        self.assertNotIn("u:p@", serialized)

    def test_scan_redacts_before_truncating_large_secret_values(self):
        with patch("tools.security_scans.subprocess.run") as run:
            run.return_value.returncode = 1
            run.return_value.stdout = "token=" + ("leak" * 5000)
            run.return_value.stderr = ""
            result = run_scan(["scanner", "fs", "."])
        self.assertNotIn("leak", result["stdout"])

    def test_run_all_writes_machine_readable_failed_gate(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "security.json"
            with patch(
                "tools.security_scans.run_scan",
                side_effect=[
                    {"status": "passed"},
                    {"status": "failed"},
                    {"status": "passed"},
                    {"status": "passed"},
                    {"status": "passed"},
                ],
            ):
                result = run_all(output)
            serialized = json.loads(output.read_text(encoding="utf-8"))
        self.assertEqual(result["status"], "failed")
        self.assertEqual(serialized["status"], "failed")

    def test_frontend_scan_runs_from_frontend_package_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "security.json"
            with patch(
                "tools.security_scans.run_scan",
                return_value={"status": "passed"},
            ) as run_scan:
                run_all(output)
        frontend_command = run_scan.call_args_list[2].args[0]
        self.assertIn("--prefix", frontend_command)
        self.assertIn("frontend", frontend_command[frontend_command.index("--prefix") + 1])

    def test_cli_returns_aggregate_gate_status(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "security.json"
            with patch(
                "tools.security_scans.run_all",
                return_value={"status": "failed"},
            ):
                exit_code = security_scans_main(["all", "--output", str(output)])
        self.assertEqual(exit_code, 1)

    def test_summary_cli_fails_when_any_raw_gate_failed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "one.json").write_text('{"status": "passed"}', encoding="utf-8")
            (root / "two.json").write_text('{"status": "failed"}', encoding="utf-8")
            output = root / "summary.json"
            self.assertEqual(
                security_scans_main(
                    ["summarize", "--input-dir", str(root), "--output", str(output)],
                ),
                1,
            )
            result = json.loads(output.read_text(encoding="utf-8"))
        self.assertEqual(result["status"], "failed")

    def test_summary_requires_complete_recursive_security_gate_set(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            nested = root / "nested"
            nested.mkdir()
            (nested / "security.json").write_text(
                json.dumps(
                    {
                        "status": "passed",
                        "gates": {
                            "python_dependencies": {"status": "passed"},
                            "source_bandit": {"status": "passed"},
                            "frontend_dependencies": {"status": "passed"},
                            "filesystem_trivy": {"status": "passed"},
                            "container_image": {"status": "passed"},
                            "secret_gitleaks": {"status": "passed"},
                        },
                    },
                ),
                encoding="utf-8",
            )
            (nested / "web.json").write_text('{"status": "passed"}', encoding="utf-8")
            output = root / "summary.json"
            exit_code = security_scans_main(
                ["summarize", "--input-dir", str(root), "--output", str(output)],
            )
            result = json.loads(output.read_text(encoding="utf-8"))
        self.assertEqual(exit_code, 1)
        self.assertEqual(result["status"], "failed")

    def test_summary_rejects_a_passing_but_incomplete_scan_set(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "partial.json").write_text('{"status": "passed"}', encoding="utf-8")
            output = root / "summary.json"
            exit_code = security_scans_main(
                ["summarize", "--input-dir", str(root), "--output", str(output)],
            )
            result = json.loads(output.read_text(encoding="utf-8"))
        self.assertEqual(exit_code, 1)
        self.assertEqual(result["status"], "failed")

    def test_summary_redacts_sensitive_values_from_raw_reports(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "raw.json").write_text(
                '{"status": "failed", "details": "access_token=summary-probe"}',
                encoding="utf-8",
            )
            output = root / "summary.json"
            security_scans_main(
                ["summarize", "--input-dir", str(root), "--output", str(output)],
            )
            serialized = output.read_text(encoding="utf-8")
        self.assertNotIn("summary-probe", serialized)

    def test_summary_redacts_nested_sensitive_json_keys(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "raw.json").write_text(
                '{"status": "failed", "nested": {"db_api_key": "nested-probe"}}',
                encoding="utf-8",
            )
            output = root / "summary.json"
            security_scans_main(
                ["summarize", "--input-dir", str(root), "--output", str(output)],
            )
            serialized = output.read_text(encoding="utf-8")
        self.assertNotIn("nested-probe", serialized)


class WebSecurityGateTests(unittest.TestCase):
    def test_web_cli_loads_a_restricted_context_file_without_serializing_tokens(self):
        context = {
            "schema_version": 1,
            "project_id": "project-1",
            "endpoint_id": "endpoint-1",
            "user_ids": {
                "owner": "owner-id",
                "editor": "editor-id",
                "operator": "operator-id",
                "viewer": "viewer-id",
                "outsider": "outsider-id",
            },
            "tokens": {
                "owner": "owner-token-probe",
                "editor": "editor-token-probe",
                "operator": "operator-token-probe",
                "viewer": "viewer-token-probe",
                "outsider": "outsider-token-probe",
            },
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            context_path = root / "web-context.json"
            output = root / "web.json"
            context_path.write_text(json.dumps(context), encoding="utf-8")
            with patch("tools.security_scans.run_web_gate", return_value={"status": "passed", "gates": {}}) as run_web_gate:
                exit_code = security_scans_main(
                    [
                        "web",
                        "--base-url",
                        "http://acceptance.example.invalid",
                        "--context",
                        str(context_path),
                        "--output",
                        str(output),
                    ],
                )
            serialized = output.read_text(encoding="utf-8")
        self.assertEqual(exit_code, 0)
        environment = run_web_gate.call_args.kwargs["environment"]
        self.assertEqual(environment["WEB_SCAN_OWNER_TOKEN"], "owner-token-probe")
        self.assertNotIn("owner-token-probe", serialized)

    def test_web_gate_exercises_role_and_notification_boundaries_without_leaking_tokens(self):
        environment = {
            "WEB_SCAN_PROJECT_ID": "project-1",
            "WEB_SCAN_ENDPOINT_ID": "endpoint-1",
            "WEB_SCAN_OWNER_TOKEN": "owner-token-probe",
            "WEB_SCAN_EDITOR_TOKEN": "editor-token-probe",
            "WEB_SCAN_OPERATOR_TOKEN": "operator-token-probe",
            "WEB_SCAN_VIEWER_TOKEN": "viewer-token-probe",
            "WEB_SCAN_OUTSIDER_TOKEN": "outsider-token-probe",
        }
        calls = []

        def request(method, url, headers, payload):
            calls.append((method, url, headers, payload))
            token = headers.get("Authorization")
            if method == "GET" and token == "Bearer outsider-token-probe":
                return HttpResponse(404, {"detail": {"code": "PROJECT_NOT_FOUND"}})
            if method == "GET" and token in {
                "Bearer operator-token-probe",
                "Bearer viewer-token-probe",
            }:
                return HttpResponse(200, {"items": [], "total": 0})
            if method == "POST" and url.endswith("/endpoint-1/test"):
                if token == "Bearer outsider-token-probe":
                    return HttpResponse(404, {"detail": {"code": "PROJECT_NOT_FOUND"}})
                if token in {"Bearer operator-token-probe", "Bearer viewer-token-probe"}:
                    return HttpResponse(403, {"detail": {"code": "PROJECT_PERMISSION_DENIED"}})
                return HttpResponse(200, {"status": "sent", "error_code": None})
            if method == "POST" and url.endswith("notification-endpoints"):
                if token == "Bearer outsider-token-probe":
                    return HttpResponse(404, {"detail": {"code": "PROJECT_NOT_FOUND"}})
                if getattr(payload, "body", None) is not None:
                    return HttpResponse(413, {"detail": {"code": "NOTIFICATION_REQUEST_TOO_LARGE"}})
                return HttpResponse(
                    422,
                    {"detail": {"code": "NOTIFICATION_ENDPOINT_FORBIDDEN"}},
                )
            return HttpResponse(500, {"secret": "must-not-appear"})

        result = run_web_gate(
            "http://acceptance.example.invalid/",
            environment=environment,
            request=request,
        )

        self.assertEqual(result["status"], "passed")
        self.assertTrue({
            "outsider_hidden",
            "outsider_endpoint_hidden",
            "outsider_mutation_hidden",
            "operator_read",
            "viewer_read",
            "operator_manage_denied",
            "viewer_manage_denied",
            "editor_endpoint_test",
            "owner_endpoint_test",
            "ssrf_loopback",
            "ssrf_private",
            "ssrf_link_local",
            "ssrf_metadata",
            "ssrf_ipv6_loopback",
            "redirect_escape",
            "oversized_request",
            "notification_payload_limit",
            "notification_timeout",
        }.issubset(result["gates"]))
        self.assertGreaterEqual(len(calls), 14)
        serialized = json.dumps(result)
        self.assertNotIn("owner-token-probe", serialized)
        self.assertNotIn("editor-token-probe", serialized)
        self.assertNotIn("operator-token-probe", serialized)
        self.assertNotIn("viewer-token-probe", serialized)
        self.assertNotIn("outsider-token-probe", serialized)
        self.assertNotIn("must-not-appear", serialized)

    def test_web_gate_fails_when_any_required_security_probe_is_missing(self):
        environment = {
            "WEB_SCAN_PROJECT_ID": "project-1",
            "WEB_SCAN_ENDPOINT_ID": "endpoint-1",
            "WEB_SCAN_OWNER_TOKEN": "owner-token-probe",
            "WEB_SCAN_EDITOR_TOKEN": "editor-token-probe",
            "WEB_SCAN_OPERATOR_TOKEN": "operator-token-probe",
            "WEB_SCAN_VIEWER_TOKEN": "viewer-token-probe",
            "WEB_SCAN_OUTSIDER_TOKEN": "outsider-token-probe",
        }

        def request(method, url, headers, _payload):
            token = headers.get("Authorization")
            if method == "GET":
                return HttpResponse(404, {}) if token == "Bearer outsider-token-probe" else HttpResponse(200, {})
            if url.endswith("/endpoint-1/test"):
                if token == "Bearer outsider-token-probe":
                    return HttpResponse(404, {})
                if token in {"Bearer operator-token-probe", "Bearer viewer-token-probe"}:
                    return HttpResponse(403, {})
                return HttpResponse(200, {"status": "sent", "error_code": None})
            if token == "Bearer outsider-token-probe":
                return HttpResponse(404, {})
            if getattr(_payload, "body", None) is not None:
                return HttpResponse(413, {})
            return HttpResponse(422, {})

        result = run_web_gate(
            "http://acceptance.example.invalid/",
            environment=environment,
            request=request,
        )

        required = {
            "outsider_hidden",
            "outsider_endpoint_hidden",
            "outsider_mutation_hidden",
            "viewer_read",
            "operator_read",
            "viewer_manage_denied",
            "operator_manage_denied",
            "editor_endpoint_test",
            "owner_endpoint_test",
            "ssrf_loopback",
            "ssrf_private",
            "ssrf_link_local",
            "ssrf_metadata",
            "ssrf_ipv6_loopback",
            "redirect_escape",
            "oversized_request",
            "notification_payload_limit",
            "notification_timeout",
        }
        self.assertEqual(result["status"], "passed")
        self.assertTrue(required.issubset(result["gates"]))

    def test_web_gate_fails_when_endpoint_test_exposes_provider_payload(self):
        environment = {
            "WEB_SCAN_PROJECT_ID": "project-1",
            "WEB_SCAN_ENDPOINT_ID": "endpoint-1",
            "WEB_SCAN_OWNER_TOKEN": "owner-token-probe",
            "WEB_SCAN_EDITOR_TOKEN": "editor-token-probe",
            "WEB_SCAN_OPERATOR_TOKEN": "operator-token-probe",
            "WEB_SCAN_VIEWER_TOKEN": "viewer-token-probe",
            "WEB_SCAN_OUTSIDER_TOKEN": "outsider-token-probe",
        }

        def request(method, url, headers, _payload):
            token = headers.get("Authorization")
            if method == "GET":
                return HttpResponse(404, {}) if token == "Bearer outsider-token-probe" else HttpResponse(200, {"items": [], "total": 0})
            if method == "POST" and url.endswith("/endpoint-1/test"):
                if token in {"Bearer operator-token-probe", "Bearer viewer-token-probe"}:
                    return HttpResponse(403, {"detail": {"code": "PROJECT_PERMISSION_DENIED"}})
                return HttpResponse(
                    200,
                    {
                        "status": "sent",
                        "error_code": None,
                        "provider_response": "must-not-appear",
                    },
                )
            return HttpResponse(422, {"detail": {"code": "NOTIFICATION_ENDPOINT_FORBIDDEN"}})

        result = run_web_gate(
            "http://acceptance.example.invalid/",
            environment=environment,
            request=request,
        )

        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["gates"]["owner_endpoint_test"]["status"], "failed")
        self.assertNotIn("must-not-appear", json.dumps(result))

    def test_web_gate_requires_successful_endpoint_test_delivery(self):
        environment = {
            "WEB_SCAN_PROJECT_ID": "project-1",
            "WEB_SCAN_ENDPOINT_ID": "endpoint-1",
            "WEB_SCAN_OWNER_TOKEN": "owner-token-probe",
            "WEB_SCAN_EDITOR_TOKEN": "editor-token-probe",
            "WEB_SCAN_OPERATOR_TOKEN": "operator-token-probe",
            "WEB_SCAN_VIEWER_TOKEN": "viewer-token-probe",
            "WEB_SCAN_OUTSIDER_TOKEN": "outsider-token-probe",
        }

        def request(method, url, headers, _payload):
            token = headers.get("Authorization")
            if method == "GET":
                return HttpResponse(404, {}) if token == "Bearer outsider-token-probe" else HttpResponse(200, {"items": [], "total": 0})
            if method == "POST" and url.endswith("/endpoint-1/test"):
                if token in {"Bearer operator-token-probe", "Bearer viewer-token-probe"}:
                    return HttpResponse(403, {"detail": {"code": "PROJECT_PERMISSION_DENIED"}})
                return HttpResponse(
                    200,
                    {
                        "status": "retry",
                        "error_code": "NOTIFICATION_PROVIDER_UNAVAILABLE",
                    },
                )
            return HttpResponse(422, {"detail": {"code": "NOTIFICATION_ENDPOINT_FORBIDDEN"}})

        result = run_web_gate(
            "http://acceptance.example.invalid/",
            environment=environment,
            request=request,
        )

        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["gates"]["owner_endpoint_test"]["status"], "failed")

    def test_web_gate_requires_all_project_role_context(self):
        environment = {
            "WEB_SCAN_PROJECT_ID": "project-1",
            "WEB_SCAN_ENDPOINT_ID": "endpoint-1",
            "WEB_SCAN_OWNER_TOKEN": "owner-token-probe",
            "WEB_SCAN_VIEWER_TOKEN": "viewer-token-probe",
            "WEB_SCAN_OUTSIDER_TOKEN": "outsider-token-probe",
        }

        result = run_web_gate(
            "http://acceptance.example.invalid/",
            environment=environment,
            request=lambda *_args: HttpResponse(500, {}),
        )

        self.assertEqual(result["status"], "failed")
        self.assertEqual(
            result["gates"]["identity_context"]["missing"],
            ["editor_token", "operator_token"],
        )

    def test_web_gate_fails_closed_when_identity_context_is_missing(self):
        result = run_web_gate("http://acceptance.example.invalid", environment={})

        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["gates"]["identity_context"]["code"], "WEB_SCAN_CONTEXT_MISSING")

    def test_web_cli_writes_the_gate_result(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "web.json"
            with patch(
                "tools.security_scans.run_web_gate",
                return_value={"status": "passed", "gates": {}},
            ):
                exit_code = security_scans_main(
                    ["web", "--base-url", "http://acceptance.example.invalid", "--output", str(output)],
                )
            result = json.loads(output.read_text(encoding="utf-8"))

        self.assertEqual(exit_code, 0)
        self.assertEqual(result["status"], "passed")


if __name__ == "__main__":
    unittest.main()
