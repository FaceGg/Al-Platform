import json
import os
import stat
import tempfile
import unittest
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from tools.security_scans import (
    HttpResponse,
    REQUIRED_SCAN_GATES,
    WEB_SECURITY_GATE_NAMES,
    evaluate_npm_audit_exception,
    main as security_scans_main,
    redact_scan_output,
    run_all,
    run_scan,
    run_web_gate,
)


class SecurityGateTests(unittest.TestCase):
    @staticmethod
    def _react_router_audit_report():
        return {
            "vulnerabilities": {
                "react-router": {
                    "name": "react-router",
                    "severity": "high",
                    "via": [{"source": 1124282, "severity": "high"}],
                },
                "react-router-dom": {
                    "name": "react-router-dom",
                    "severity": "high",
                    "via": ["react-router"],
                },
            },
            "metadata": {
                "vulnerabilities": {
                    "high": 2,
                    "critical": 0,
                    "total": 2,
                },
            },
        }

    @staticmethod
    def _write_react_router_exception(path: Path, *, expires_on: str = "2026-09-01"):
        path.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "id": "react-router-rsc-mode-csrf",
                    "owner": "ml-platform-maintainers",
                    "reviewed_at": "2026-08-02",
                    "expires_on": expires_on,
                    "package_versions": {
                        "react-router": "7.18.1",
                        "react-router-dom": "7.18.1",
                    },
                    "advisory_sources": [1124282],
                    "mitigation": "BrowserRouter SPA with no RSC, SSR, server handler, or Action routes.",
                },
            ),
            encoding="utf-8",
        )

    @staticmethod
    def _write_frontend_fixture(root: Path, source: str = "export const router = 'BrowserRouter';"):
        (root / "src").mkdir(parents=True)
        (root / "src" / "App.tsx").write_text(source, encoding="utf-8")
        (root / "package-lock.json").write_text(
            json.dumps(
                {
                    "packages": {
                        "node_modules/react-router": {"version": "7.18.1"},
                        "node_modules/react-router-dom": {"version": "7.18.1"},
                    },
                },
            ),
            encoding="utf-8",
        )

    def test_react_router_audit_exception_requires_exact_advisory_versions_and_client_scope(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            exception_path = root / "exception.json"
            frontend = root / "frontend"
            self._write_react_router_exception(exception_path)
            self._write_frontend_fixture(frontend)

            result = evaluate_npm_audit_exception(
                self._react_router_audit_report(),
                exception_path=exception_path,
                frontend_directory=frontend,
                today=date(2026, 8, 2),
            )

        self.assertEqual(result["status"], "passed")
        self.assertEqual(result["exception"]["id"], "react-router-rsc-mode-csrf")
        self.assertNotIn("vulnerabilities", result)

    def test_react_router_audit_exception_accepts_the_real_client_only_frontend(self):
        repository_root = Path(__file__).resolve().parents[3]
        result = evaluate_npm_audit_exception(
            self._react_router_audit_report(),
            exception_path=(
                repository_root
                / "docs"
                / "security"
                / "react-router-rsc-mode-exception.json"
            ),
            frontend_directory=repository_root / "ml-platform" / "frontend",
            today=date(2026, 8, 2),
        )

        self.assertEqual(result["status"], "passed")

    def test_react_router_audit_exception_fails_after_its_expiry(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            exception_path = root / "exception.json"
            frontend = root / "frontend"
            self._write_react_router_exception(exception_path, expires_on="2026-08-01")
            self._write_frontend_fixture(frontend)

            result = evaluate_npm_audit_exception(
                self._react_router_audit_report(),
                exception_path=exception_path,
                frontend_directory=frontend,
                today=date(2026, 8, 2),
            )

        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["error_code"], "NPM_AUDIT_EXCEPTION_EXPIRED")

    def test_react_router_audit_exception_fails_when_the_frontend_adds_server_api_usage(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            exception_path = root / "exception.json"
            frontend = root / "frontend"
            self._write_react_router_exception(exception_path)
            self._write_frontend_fixture(
                frontend,
                "import { createRequestHandler } from 'react-router';",
            )

            result = evaluate_npm_audit_exception(
                self._react_router_audit_report(),
                exception_path=exception_path,
                frontend_directory=frontend,
                today=date(2026, 8, 2),
            )

        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["error_code"], "NPM_AUDIT_EXCEPTION_SCOPE_VIOLATION")

    def test_react_router_audit_exception_fails_closed_for_server_entries_outside_src(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            exception_path = root / "exception.json"
            frontend = root / "frontend"
            self._write_react_router_exception(exception_path)
            self._write_frontend_fixture(frontend)
            (frontend / "server.ts").write_text(
                "export const handler = createStaticHandler(routes);",
                encoding="utf-8",
            )
            (frontend / "node_modules").mkdir()
            (frontend / "node_modules" / "ignored.js").write_text(
                "export const action = () => null;",
                encoding="utf-8",
            )
            (frontend / "dist").mkdir()
            (frontend / "dist" / "ignored.js").write_text(
                "export const prerender = true;",
                encoding="utf-8",
            )

            result = evaluate_npm_audit_exception(
                self._react_router_audit_report(),
                exception_path=exception_path,
                frontend_directory=frontend,
                today=date(2026, 8, 2),
            )

        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["error_code"], "NPM_AUDIT_EXCEPTION_SCOPE_VIOLATION")

    def test_react_router_audit_exception_rejects_ssr_config_outside_src(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            exception_path = root / "exception.json"
            frontend = root / "frontend"
            self._write_react_router_exception(exception_path)
            self._write_frontend_fixture(frontend)
            (frontend / "react-router.config.ts").write_text(
                "export default { ssr: true };",
                encoding="utf-8",
            )

            result = evaluate_npm_audit_exception(
                self._react_router_audit_report(),
                exception_path=exception_path,
                frontend_directory=frontend,
                today=date(2026, 8, 2),
            )

        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["error_code"], "NPM_AUDIT_EXCEPTION_SCOPE_VIOLATION")

    def test_react_router_audit_exception_rejects_hydrated_server_entry(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            exception_path = root / "exception.json"
            frontend = root / "frontend"
            self._write_react_router_exception(exception_path)
            self._write_frontend_fixture(frontend)
            (frontend / "entry.server.tsx").write_text(
                "export const app = <HydratedRouter />;",
                encoding="utf-8",
            )

            result = evaluate_npm_audit_exception(
                self._react_router_audit_report(),
                exception_path=exception_path,
                frontend_directory=frontend,
                today=date(2026, 8, 2),
            )

        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["error_code"], "NPM_AUDIT_EXCEPTION_SCOPE_VIOLATION")

    def test_react_router_audit_exception_rejects_route_action(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            exception_path = root / "exception.json"
            frontend = root / "frontend"
            self._write_react_router_exception(exception_path)
            self._write_frontend_fixture(frontend)
            (frontend / "routes.ts").write_text(
                "export const routes = [{ action: async () => null }];",
                encoding="utf-8",
            )

            result = evaluate_npm_audit_exception(
                self._react_router_audit_report(),
                exception_path=exception_path,
                frontend_directory=frontend,
                today=date(2026, 8, 2),
            )

        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["error_code"], "NPM_AUDIT_EXCEPTION_SCOPE_VIOLATION")

    def test_react_router_audit_exception_rejects_empty_server_entry(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            exception_path = root / "exception.json"
            frontend = root / "frontend"
            self._write_react_router_exception(exception_path)
            self._write_frontend_fixture(frontend)
            (frontend / "entry.server.tsx").write_text(
                "export default null;",
                encoding="utf-8",
            )

            result = evaluate_npm_audit_exception(
                self._react_router_audit_report(),
                exception_path=exception_path,
                frontend_directory=frontend,
                today=date(2026, 8, 2),
            )

        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["error_code"], "NPM_AUDIT_EXCEPTION_SCOPE_VIOLATION")

    def test_react_router_audit_exception_rejects_hydrated_router_in_client_entry(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            exception_path = root / "exception.json"
            frontend = root / "frontend"
            self._write_react_router_exception(exception_path)
            self._write_frontend_fixture(frontend)
            (frontend / "entry.client.tsx").write_text(
                "export const app = <HydratedRouter />;",
                encoding="utf-8",
            )

            result = evaluate_npm_audit_exception(
                self._react_router_audit_report(),
                exception_path=exception_path,
                frontend_directory=frontend,
                today=date(2026, 8, 2),
            )

        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["error_code"], "NPM_AUDIT_EXCEPTION_SCOPE_VIOLATION")

    def test_react_router_audit_exception_rejects_named_route_action(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            exception_path = root / "exception.json"
            frontend = root / "frontend"
            self._write_react_router_exception(exception_path)
            self._write_frontend_fixture(frontend)
            (frontend / "routes.ts").write_text(
                "export const routes = [{ action: handleForm }];",
                encoding="utf-8",
            )

            result = evaluate_npm_audit_exception(
                self._react_router_audit_report(),
                exception_path=exception_path,
                frontend_directory=frontend,
                today=date(2026, 8, 2),
            )

        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["error_code"], "NPM_AUDIT_EXCEPTION_SCOPE_VIOLATION")

    def test_react_router_audit_exception_rejects_async_function_route_action(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            exception_path = root / "exception.json"
            frontend = root / "frontend"
            self._write_react_router_exception(exception_path)
            self._write_frontend_fixture(frontend)
            (frontend / "routes.ts").write_text(
                "export const routes = [{ action: async function submit() {} }];",
                encoding="utf-8",
            )

            result = evaluate_npm_audit_exception(
                self._react_router_audit_report(),
                exception_path=exception_path,
                frontend_directory=frontend,
                today=date(2026, 8, 2),
            )

        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["error_code"], "NPM_AUDIT_EXCEPTION_SCOPE_VIOLATION")

    def test_react_router_audit_exception_rejects_dotted_route_action(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            exception_path = root / "exception.json"
            frontend = root / "frontend"
            self._write_react_router_exception(exception_path)
            self._write_frontend_fixture(frontend)
            (frontend / "routes.ts").write_text(
                "export const routes = [{ action: routeActions.submit }];",
                encoding="utf-8",
            )

            result = evaluate_npm_audit_exception(
                self._react_router_audit_report(),
                exception_path=exception_path,
                frontend_directory=frontend,
                today=date(2026, 8, 2),
            )

        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["error_code"], "NPM_AUDIT_EXCEPTION_SCOPE_VIOLATION")

    def test_react_router_audit_exception_rejects_shorthand_route_action(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            exception_path = root / "exception.json"
            frontend = root / "frontend"
            self._write_react_router_exception(exception_path)
            self._write_frontend_fixture(frontend)
            (frontend / "routes.ts").write_text(
                "export type Metadata = string\n"
                "export const routes: RouteObject[] = [{ action }];",
                encoding="utf-8",
            )

            result = evaluate_npm_audit_exception(
                self._react_router_audit_report(),
                exception_path=exception_path,
                frontend_directory=frontend,
                today=date(2026, 8, 2),
            )

        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["error_code"], "NPM_AUDIT_EXCEPTION_SCOPE_VIOLATION")

    def test_react_router_audit_exception_allows_typescript_action_type_fields(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            exception_path = root / "exception.json"
            frontend = root / "frontend"
            self._write_react_router_exception(exception_path)
            self._write_frontend_fixture(frontend)
            (frontend / "src" / "securityNotifications.ts").write_text(
                "export interface SecurityNotification { action: string; }\n"
                "export type NotificationFilter = { action: string }\n",
                encoding="utf-8",
            )

            result = evaluate_npm_audit_exception(
                self._react_router_audit_report(),
                exception_path=exception_path,
                frontend_directory=frontend,
                today=date(2026, 8, 2),
            )

        self.assertEqual(result["status"], "passed")

    def test_react_router_audit_exception_rejects_json_ssr_config(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            exception_path = root / "exception.json"
            frontend = root / "frontend"
            self._write_react_router_exception(exception_path)
            self._write_frontend_fixture(frontend)
            (frontend / "react-router.config.ts").write_text(
                '{"ssr": true}',
                encoding="utf-8",
            )

            result = evaluate_npm_audit_exception(
                self._react_router_audit_report(),
                exception_path=exception_path,
                frontend_directory=frontend,
                today=date(2026, 8, 2),
            )

        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["error_code"], "NPM_AUDIT_EXCEPTION_SCOPE_VIOLATION")

    def test_react_router_audit_exception_rejects_unhashable_advisory_sources(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            exception_path = root / "exception.json"
            frontend = root / "frontend"
            self._write_react_router_exception(exception_path)
            exception = json.loads(exception_path.read_text(encoding="utf-8"))
            exception["advisory_sources"] = [{"source": 1124282}]
            exception_path.write_text(json.dumps(exception), encoding="utf-8")
            self._write_frontend_fixture(frontend)

            result = evaluate_npm_audit_exception(
                self._react_router_audit_report(),
                exception_path=exception_path,
                frontend_directory=frontend,
                today=date(2026, 8, 2),
            )

        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["error_code"], "NPM_AUDIT_EXCEPTION_INVALID")

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

    def test_run_all_allows_only_the_reviewed_npm_audit_exception(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            exception_path = root / "exception.json"
            output = root / "security.json"
            self._write_react_router_exception(exception_path)
            with (
                patch.dict(
                    "tools.security_scans.os.environ",
                    {"ACCEPTANCE_IMAGE": "ml-platform-backend:test"},
                    clear=False,
                ),
                patch(
                    "tools.security_scans.run_scan",
                    return_value={"status": "passed"},
                ),
                patch("tools.security_scans.subprocess.run") as run,
                patch(
                    "tools.security_scans._frontend_package_versions",
                    return_value={
                        "react-router": "7.18.1",
                        "react-router-dom": "7.18.1",
                    },
                ),
                patch(
                    "tools.security_scans._frontend_uses_react_router_server_api",
                    return_value=False,
                ),
            ):
                run.return_value.returncode = 1
                run.return_value.stdout = json.dumps(self._react_router_audit_report())
                run.return_value.stderr = ""
                result = run_all(output, npm_audit_exception=exception_path)

        self.assertEqual(result["status"], "passed")
        self.assertEqual(
            result["gates"]["frontend_dependencies"]["exception"]["id"],
            "react-router-rsc-mode-csrf",
        )
        self.assertEqual(run.call_args.args[0][0], "npm")

    def test_frontend_scan_runs_from_frontend_package_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "security.json"
            with patch(
                "tools.security_scans.run_scan",
                return_value={"status": "passed"},
            ) as run_scan:
                run_all(output)
        frontend_command = next(
            call.args[0]
            for call in run_scan.call_args_list
            if call.args[0][0] == "npm"
        )
        self.assertIn("--prefix", frontend_command)
        self.assertIn("frontend", frontend_command[frontend_command.index("--prefix") + 1])

    def test_run_all_scans_the_repository_for_filesystem_and_secret_findings(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "security.json"
            with patch(
                "tools.security_scans.run_scan",
                return_value={"status": "passed"},
            ) as run_scan:
                run_all(output)

        repository_root = Path(__file__).resolve().parents[3]
        frontend_directory = repository_root / "ml-platform" / "frontend"
        commands = [call.args[0] for call in run_scan.call_args_list]
        filesystem_command = next(command for command in commands if command[:2] == ["trivy", "fs"])
        gitleaks_command = next(command for command in commands if command[:2] == ["gitleaks", "detect"])
        self.assertEqual(Path(filesystem_command[-1]).resolve(), repository_root)
        self.assertNotIn("--skip-dirs", filesystem_command)
        self.assertTrue(frontend_directory.is_dir())
        self.assertIn("--source", gitleaks_command)
        self.assertEqual(
            Path(gitleaks_command[gitleaks_command.index("--source") + 1]).resolve(),
            repository_root,
        )

    def test_run_all_writes_redacted_json_evidence_for_each_required_scanner(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "security" / "security.json"
            with (
                patch.dict(
                    "tools.security_scans.os.environ",
                    {"ACCEPTANCE_IMAGE": "ml-platform-backend:test"},
                    clear=False,
                ),
                patch(
                    "tools.security_scans.run_scan",
                    return_value={"status": "passed", "stdout": "token=must-not-appear"},
                ) as run_scan,
            ):
                run_all(output)

            evidence_dir = output.parent
            report_names = (
                "pip-audit.json",
                "bandit.json",
                "npm-audit.json",
                "trivy-fs.json",
                "trivy-image.json",
                "gitleaks.json",
            )
            report_paths = {name: evidence_dir / name for name in report_names}

            self.assertTrue(all(path.is_file() for path in report_paths.values()))
            reports = {
                name: json.loads(path.read_text(encoding="utf-8"))
                for name, path in report_paths.items()
            }
            commands = [call.args[0] for call in run_scan.call_args_list]

        self.assertEqual(set(reports), set(report_names))
        self.assertNotIn("must-not-appear", json.dumps(reports))
        pip_audit = next(command for command in commands if "pip_audit" in command)
        bandit = next(command for command in commands if command[0] == "bandit")
        npm_audit = next(command for command in commands if command[0] == "npm")
        trivy_filesystem = next(command for command in commands if command[:2] == ["trivy", "fs"])
        trivy_image = next(command for command in commands if command[:2] == ["trivy", "image"])
        gitleaks = next(command for command in commands if command[:2] == ["gitleaks", "detect"])
        self.assertIn("--format", pip_audit)
        self.assertIn("json", pip_audit)
        self.assertIn("--output", pip_audit)
        self.assertEqual(bandit[bandit.index("-f") + 1], "json")
        self.assertIn("-o", bandit)
        self.assertIn("--json", npm_audit)
        self.assertIn("--format", trivy_filesystem)
        self.assertIn("json", trivy_filesystem)
        self.assertIn("--output", trivy_filesystem)
        self.assertIn("--format", trivy_image)
        self.assertIn("json", trivy_image)
        self.assertIn("--output", trivy_image)
        self.assertIn("--report-format", gitleaks)
        self.assertIn("json", gitleaks)
        self.assertIn("--report-path", gitleaks)

    def test_run_all_treats_high_bandit_findings_as_the_blocking_source_gate(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "security.json"
            with patch(
                "tools.security_scans.run_scan",
                return_value={"status": "passed"},
            ) as run_scan:
                run_all(output)

        bandit_command = next(
            call.args[0]
            for call in run_scan.call_args_list
            if call.args[0][0] == "bandit"
        )
        self.assertEqual(bandit_command[:6], ["bandit", "-r", "app", "-q", "-lll", "-f"])
        self.assertEqual(bandit_command[6], "json")
        self.assertIn("-o", bandit_command)

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

    @staticmethod
    def _write_complete_security_evidence(root: Path) -> None:
        report_names = {
            "python_dependencies": "pip-audit.json",
            "source_bandit": "bandit.json",
            "frontend_dependencies": "npm-audit.json",
            "filesystem_trivy": "trivy-fs.json",
            "container_image": "trivy-image.json",
            "secret_gitleaks": "gitleaks.json",
        }
        for filename in report_names.values():
            (root / filename).write_text('{"scanner": "passed"}', encoding="utf-8")
        (root / "security.json").write_text(
            json.dumps(
                {
                    "status": "passed",
                    "gates": {
                        name: {"status": "passed"}
                        for name in report_names
                    },
                },
            ),
            encoding="utf-8",
        )
        (root / "web.json").write_text(
            json.dumps(
                {
                    "status": "passed",
                    "gates": {
                        name: {"status": "passed"}
                        for name in WEB_SECURITY_GATE_NAMES
                    },
                },
            ),
            encoding="utf-8",
        )

    def test_summary_binds_each_required_gate_to_a_relative_raw_evidence_path(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._write_complete_security_evidence(root)
            output = root / "summary.json"
            exit_code = security_scans_main(
                ["summarize", "--input-dir", str(root), "--output", str(output)],
            )
            result = json.loads(output.read_text(encoding="utf-8"))

        expected_paths = {
            "python_dependencies": "pip-audit.json",
            "source_bandit": "bandit.json",
            "frontend_dependencies": "npm-audit.json",
            "filesystem_trivy": "trivy-fs.json",
            "container_image": "trivy-image.json",
            "secret_gitleaks": "gitleaks.json",
            "web_security": "web.json",
        }
        self.assertEqual(exit_code, 0)
        self.assertEqual(set(result["gates"]), REQUIRED_SCAN_GATES)
        self.assertTrue(all("evidence_path" in gate for gate in result["gates"].values()))
        self.assertEqual(
            {
                name: gate.get("evidence_path")
                for name, gate in result["gates"].items()
            },
            expected_paths,
        )
        self.assertNotIn(str(root), json.dumps(result))

    def test_summary_fails_closed_when_a_required_raw_evidence_report_is_missing(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._write_complete_security_evidence(root)
            (root / "trivy-image.json").unlink()
            output = root / "summary.json"
            exit_code = security_scans_main(
                ["summarize", "--input-dir", str(root), "--output", str(output)],
            )
            result = json.loads(output.read_text(encoding="utf-8"))

        self.assertEqual(exit_code, 1)
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["gates"]["container_image"]["evidence_path"], "trivy-image.json")
        self.assertEqual(result["gates"]["container_image"]["error_code"], "SECURITY_EVIDENCE_MISSING")

    def test_summary_rejects_raw_evidence_symlinked_outside_input_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            root = parent / "security"
            root.mkdir()
            self._write_complete_security_evidence(root)
            external = parent / "outside-trivy-image.json"
            external.write_text('{"scanner": "external"}', encoding="utf-8")
            report = root / "trivy-image.json"
            report.unlink()
            try:
                report.symlink_to(external)
            except OSError as error:
                report.write_text('{"scanner": "in-root"}', encoding="utf-8")
                original_lstat = os.lstat

                def linked_lstat(path):
                    result = original_lstat(path)
                    if Path(path) == report:
                        return SimpleNamespace(
                            st_mode=stat.S_IFLNK,
                            st_nlink=1,
                            st_file_attributes=0,
                        )
                    return result

                with patch("tools.security_scans.os.lstat", side_effect=linked_lstat):
                    output = root / "summary.json"
                    exit_code = security_scans_main(
                        ["summarize", "--input-dir", str(root), "--output", str(output)],
                    )
                    result = json.loads(output.read_text(encoding="utf-8"))
            else:
                output = root / "summary.json"
                exit_code = security_scans_main(
                    ["summarize", "--input-dir", str(root), "--output", str(output)],
                )
                result = json.loads(output.read_text(encoding="utf-8"))

        self.assertEqual(exit_code, 1)
        self.assertEqual(result["gates"]["container_image"]["error_code"], "SECURITY_EVIDENCE_INVALID")

    def test_summary_rejects_hard_linked_raw_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            root = parent / "security"
            root.mkdir()
            self._write_complete_security_evidence(root)
            external = parent / "outside-trivy-image.json"
            external.write_text('{"scanner": "external"}', encoding="utf-8")
            report = root / "trivy-image.json"
            report.unlink()
            try:
                os.link(external, report)
            except OSError as error:
                self.skipTest(f"hard links are unavailable: {error}")
            output = root / "summary.json"
            exit_code = security_scans_main(
                ["summarize", "--input-dir", str(root), "--output", str(output)],
            )
            result = json.loads(output.read_text(encoding="utf-8"))

        self.assertEqual(exit_code, 1)
        self.assertEqual(result["gates"]["container_image"]["error_code"], "SECURITY_EVIDENCE_INVALID")

    def test_summary_does_not_read_a_reparse_candidate_during_enumeration(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._write_complete_security_evidence(root)
            report = root / "trivy-image.json"
            original_lstat = os.lstat
            original_read_text = Path.read_text
            reads: list[Path] = []

            def linked_lstat(path):
                result = original_lstat(path)
                if Path(path) == report:
                    return SimpleNamespace(
                        st_mode=stat.S_IFLNK,
                        st_nlink=1,
                        st_file_attributes=0,
                    )
                return result

            def guarded_read_text(path, *args, **kwargs):
                if Path(path) == report:
                    reads.append(Path(path))
                return original_read_text(path, *args, **kwargs)

            output = root / "summary.json"
            with (
                patch("tools.security_scans.os.lstat", side_effect=linked_lstat),
                patch.object(Path, "read_text", autospec=True, side_effect=guarded_read_text),
            ):
                exit_code = security_scans_main(
                    ["summarize", "--input-dir", str(root), "--output", str(output)],
                )
                result = json.loads(output.read_text(encoding="utf-8"))

        self.assertEqual(exit_code, 1)
        self.assertEqual(reads, [])
        self.assertEqual(result["gates"]["container_image"]["error_code"], "SECURITY_EVIDENCE_INVALID")

    def test_summary_rejects_hard_linked_aggregate_before_reading_gate_status(self):
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            root = parent / "security"
            root.mkdir()
            self._write_complete_security_evidence(root)
            external = parent / "outside-security.json"
            external.write_text(
                json.dumps(
                    {
                        "status": "passed",
                        "gates": {
                            name: {"status": "passed"}
                            for name in REQUIRED_SCAN_GATES
                            if name != "web_security"
                        },
                    },
                ),
                encoding="utf-8",
            )
            aggregate = root / "security.json"
            aggregate.unlink()
            os.link(external, aggregate)
            output = root / "summary.json"
            exit_code = security_scans_main(
                ["summarize", "--input-dir", str(root), "--output", str(output)],
            )
            result = json.loads(output.read_text(encoding="utf-8"))

        self.assertEqual(exit_code, 1)
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["gates"]["python_dependencies"]["error_code"], "SECURITY_EVIDENCE_INVALID")

    def test_summary_rejects_nested_unsafe_aggregate_before_reading_gate_status(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._write_complete_security_evidence(root)
            nested = root / "nested"
            nested.mkdir()
            aggregate = nested / "security.json"
            aggregate.write_text(
                json.dumps(
                    {
                        "status": "passed",
                        "gates": {
                            "python_dependencies": {"status": "passed"},
                        },
                    },
                ),
                encoding="utf-8",
            )
            original_lstat = os.lstat
            original_read_text = Path.read_text
            reads: list[Path] = []

            def unsafe_lstat(path):
                result = original_lstat(path)
                if Path(path) == aggregate:
                    return SimpleNamespace(
                        st_mode=stat.S_IFLNK,
                        st_nlink=1,
                        st_file_attributes=0,
                    )
                return result

            def guarded_read_text(path, *args, **kwargs):
                if Path(path) == aggregate:
                    reads.append(Path(path))
                return original_read_text(path, *args, **kwargs)

            output = root / "summary.json"
            with (
                patch("tools.security_scans.os.lstat", side_effect=unsafe_lstat),
                patch.object(Path, "read_text", autospec=True, side_effect=guarded_read_text),
            ):
                exit_code = security_scans_main(
                    ["summarize", "--input-dir", str(root), "--output", str(output)],
                )
                result = json.loads(output.read_text(encoding="utf-8"))

        self.assertEqual(exit_code, 1)
        self.assertEqual(reads, [])
        self.assertEqual(result["gates"]["python_dependencies"]["error_code"], "SECURITY_EVIDENCE_INVALID")

    def test_summary_rejects_unsafe_web_evidence_with_the_stable_invalid_error(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._write_complete_security_evidence(root)
            evidence = root / "web.json"
            original_lstat = os.lstat
            original_read_text = Path.read_text
            reads: list[Path] = []

            def unsafe_lstat(path):
                result = original_lstat(path)
                if Path(path) == evidence:
                    return SimpleNamespace(
                        st_mode=stat.S_IFLNK,
                        st_nlink=1,
                        st_file_attributes=0,
                    )
                return result

            def guarded_read_text(path, *args, **kwargs):
                if Path(path) == evidence:
                    reads.append(Path(path))
                return original_read_text(path, *args, **kwargs)

            output = root / "summary.json"
            with (
                patch("tools.security_scans.os.lstat", side_effect=unsafe_lstat),
                patch.object(Path, "read_text", autospec=True, side_effect=guarded_read_text),
            ):
                exit_code = security_scans_main(
                    ["summarize", "--input-dir", str(root), "--output", str(output)],
                )
                result = json.loads(output.read_text(encoding="utf-8"))

        self.assertEqual(exit_code, 1)
        self.assertEqual(reads, [])
        self.assertEqual(
            result["gates"]["web_security"]["error_code"],
            "SECURITY_EVIDENCE_INVALID",
        )

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
