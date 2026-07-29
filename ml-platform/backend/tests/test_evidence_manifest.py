import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools.evidence_manifest import MIGRATION_HEAD, generate
from tools.playwright_evidence import summarize_report
from tools.security_scans import REQUIRED_SCAN_GATES
from tools.week11_performance import (
    SCENARIO_EXPECTED_LOAD,
    SCENARIO_REQUIRED_ITERATIONS,
    summarize_results,
    write_result,
)


class EvidenceManifestTests(unittest.TestCase):
    _COMMIT = "a" * 40
    _IMAGE_DIGEST = "sha256:" + "c" * 64

    def _environment(
        self,
        commit: str | None = None,
        image_digest: str | None = None,
    ) -> dict[str, object]:
        return {
            "runtime": {
                "python": "3.12.0",
                "platform": "test-platform",
                "cpu_count": 4,
                "memory_bytes": 8 * 1024 * 1024 * 1024,
            },
            "git": {"commit": commit or self._COMMIT},
            "migration": {"current": f"{MIGRATION_HEAD} (head)"},
            "container": {"image_digest": image_digest or self._IMAGE_DIGEST, "compose": "[]"},
            "configuration": {"APP_MODE": "production"},
        }

    @staticmethod
    def _write_json(root: Path, relative_path: str, value: object) -> None:
        path = root / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value, sort_keys=True), encoding="utf-8")

    def _write_semantic_evidence(self, root: Path) -> None:
        performance_root = root / "performance"
        for scenario, iterations in SCENARIO_REQUIRED_ITERATIONS.items():
            load = SCENARIO_EXPECTED_LOAD[scenario]
            requests = load["concurrency"] * load["requests_per_worker"]
            for iteration in sorted(iterations):
                result: dict[str, object] = {
                    "concurrency": load["concurrency"],
                    "requests_per_worker": load["requests_per_worker"],
                    "requests": requests,
                    "errors": 0,
                    "error_rate": 0.0,
                    "status_counts": {"200": requests},
                    "p95_ms": 10.0,
                    "p99_ms": 12.0,
                    "scenario": scenario,
                    "iteration": iteration,
                    "commit": self._COMMIT,
                }
                if scenario == "welding-e2e":
                    result["duration_ms"] = 1000.0
                write_result(performance_root / f"{scenario}-{iteration}.json", result)
        with patch("tools.week11_performance._git_commit", return_value=self._COMMIT):
            summarize_results(performance_root, performance_root / "summary.json")

        self._write_json(
            root,
            "backup/restore-result.json",
            {
                "status": "passed",
                "row_counts_equal": True,
                "source_table_counts": {"projects": 1},
                "restored_table_counts": {"projects": 1},
                "foreign_key_violations": [],
                "object_hashes": {"status": "passed", "checked": 1, "mismatches": []},
                "restore_returncode": 0,
                "minio_restore_returncode": 0,
                "rto_seconds": 10.0,
                "rto_passed": True,
                "rpo_seconds": 10.0,
                "rpo_passed": True,
            },
        )
        self._write_json(
            root,
            "upgrade/result.json",
            {
                "status": "passed",
                "from_revision": "20260718_08",
                "to_revision": MIGRATION_HEAD,
                "first_upgrade": "ok",
                "second_upgrade": "ok",
                "alembic_check": "ok",
                "pre_upgrade_snapshot_valid": True,
                "post_upgrade_snapshot_valid": True,
                "row_counts_equal": True,
                "business_data_loss": False,
                "foreign_key_violations": [],
                "before_table_counts": {"projects": 1},
                "after_table_counts": {"projects": 1, "notification_outbox": 0},
            },
        )
        security_gates = {
            name: (
                {"status": "passed", "gates": {"access_boundary": {"status": "passed"}}}
                if name == "web_security"
                else {"status": "passed", "returncode": 0, "command": ["scanner", name]}
            )
            for name in REQUIRED_SCAN_GATES
        }
        self._write_json(
            root,
            "security/summary.json",
            {"status": "passed", "gates": security_gates},
        )
        self._write_json(
            root,
            "playwright/result.json",
            {
                "status": "passed",
                "project": "chromium",
                "tests": {"total": 1, "passed": 1, "failed": 0},
            },
        )

    def _write_required_evidence(
        self,
        root: Path,
        *,
        status: str = "passed",
        include_environment: bool = False,
        semantic: bool = False,
    ) -> None:
        if semantic and status == "passed":
            self._write_semantic_evidence(root)
        else:
            for relative_path in (
                "performance/summary.json",
                "backup/restore-result.json",
                "upgrade/result.json",
                "security/summary.json",
                "playwright/result.json",
            ):
                self._write_json(root, relative_path, {"status": status})
        if include_environment:
            self._write_json(root, "environment.json", self._environment())

    def test_generate_binds_required_evidence_with_relative_hashes(self):
        with tempfile.TemporaryDirectory() as directory:
            evidence_dir = Path(directory) / "evidence"
            self._write_required_evidence(
                evidence_dir,
                include_environment=True,
                semantic=True,
            )
            extra = evidence_dir / "environment.json"
            environment_hash = hashlib.sha256(extra.read_bytes()).hexdigest()
            output = Path(directory) / "manifest.json"

            with patch("tools.evidence_manifest._git_commit", return_value=self._COMMIT):
                manifest = generate(
                    evidence_dir,
                    output,
                    remote_ci_run_url="https://github.example.invalid/actions/runs/1",
                    image_digest=self._IMAGE_DIGEST,
                    generated_at="2026-07-29T00:00:00+00:00",
                )

            payload = json.loads(output.read_text(encoding="utf-8"))
        self.assertEqual(manifest["status"], "passed")
        self.assertEqual(payload["commit"], self._COMMIT)
        self.assertEqual(payload["migration_head"], "20260720_10_security_notifications")
        paths = [item["path"] for item in payload["files"]]
        self.assertEqual(paths, sorted(paths))
        self.assertIn("environment.json", paths)
        entry = next(item for item in payload["files"] if item["path"] == "environment.json")
        self.assertEqual(
            entry["sha256"],
            environment_hash,
        )

    def test_generate_fails_closed_for_missing_or_failed_required_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            evidence_dir = Path(directory) / "evidence"
            self._write_required_evidence(
                evidence_dir,
                status="failed",
                include_environment=True,
            )
            output = Path(directory) / "manifest.json"
            with patch("tools.evidence_manifest._git_commit", return_value=self._COMMIT):
                with self.assertRaisesRegex(RuntimeError, "did not pass"):
                    generate(
                        evidence_dir,
                        output,
                        remote_ci_run_url="https://github.example.invalid/actions/runs/1",
                        image_digest=self._IMAGE_DIGEST,
                    )

    def test_generate_requires_environment_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            evidence_dir = Path(directory) / "evidence"
            self._write_required_evidence(evidence_dir)
            output = Path(directory) / "manifest.json"

            with patch("tools.evidence_manifest._git_commit", return_value=self._COMMIT):
                with self.assertRaisesRegex(FileNotFoundError, "environment.json"):
                    generate(
                        evidence_dir,
                        output,
                        remote_ci_run_url="https://github.example.invalid/actions/runs/1",
                        image_digest=self._IMAGE_DIGEST,
                    )

            (evidence_dir / "security" / "summary.json").unlink()
            with self.assertRaisesRegex(FileNotFoundError, "missing required evidence"):
                generate(
                    evidence_dir,
                    output,
                    remote_ci_run_url="https://github.example.invalid/actions/runs/1",
                    image_digest=self._IMAGE_DIGEST,
                )

    def test_generate_rejects_sensitive_values_in_evidence_or_metadata(self):
        with tempfile.TemporaryDirectory() as directory:
            evidence_dir = Path(directory) / "evidence"
            self._write_required_evidence(evidence_dir)
            (evidence_dir / "environment.json").write_text(
                '{"token": "secret-probe"}',
                encoding="utf-8",
            )
            output = Path(directory) / "manifest.json"
            with self.assertRaisesRegex(ValueError, "sensitive"):
                generate(
                    evidence_dir,
                    output,
                    remote_ci_run_url="https://github.example.invalid/actions/runs/1",
                    image_digest=self._IMAGE_DIGEST,
                )

    def test_generate_rejects_status_only_required_evidence_shells(self):
        with tempfile.TemporaryDirectory() as directory:
            evidence_dir = Path(directory) / "evidence"
            self._write_required_evidence(
                evidence_dir,
                status="passed",
                include_environment=True,
            )
            output = Path(directory) / "manifest.json"

            with patch("tools.evidence_manifest._git_commit", return_value="a" * 40):
                with self.assertRaisesRegex(RuntimeError, "contract"):
                    generate(
                        evidence_dir,
                        output,
                        remote_ci_run_url="https://github.example.invalid/actions/runs/1",
                        image_digest=self._IMAGE_DIGEST,
                    )

    def test_generate_rejects_environment_metadata_mismatch(self):
        with tempfile.TemporaryDirectory() as directory:
            evidence_dir = Path(directory) / "evidence"
            self._write_required_evidence(evidence_dir, status="passed")
            (evidence_dir / "environment.json").write_text(
                json.dumps(self._environment("b" * 40)),
                encoding="utf-8",
            )
            output = Path(directory) / "manifest.json"

            with patch("tools.evidence_manifest._git_commit", return_value=self._COMMIT):
                with self.assertRaisesRegex(RuntimeError, "environment"):
                    generate(
                        evidence_dir,
                        output,
                        remote_ci_run_url="https://github.example.invalid/actions/runs/1",
                        image_digest=self._IMAGE_DIGEST,
                    )

    def test_generate_rejects_placeholder_image_digest(self):
        with tempfile.TemporaryDirectory() as directory:
            evidence_dir = Path(directory) / "evidence"
            self._write_required_evidence(
                evidence_dir,
                include_environment=True,
                semantic=True,
            )
            (evidence_dir / "environment.json").write_text(
                json.dumps(self._environment(image_digest="unavailable")),
                encoding="utf-8",
            )
            output = Path(directory) / "manifest.json"

            with patch("tools.evidence_manifest._git_commit", return_value=self._COMMIT):
                with self.assertRaisesRegex(ValueError, "image_digest"):
                    generate(
                        evidence_dir,
                        output,
                        remote_ci_run_url="https://github.example.invalid/actions/runs/1",
                        image_digest="unavailable",
                    )

    def test_generate_requires_retained_business_rows_for_upgrade_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            evidence_dir = Path(directory) / "evidence"
            self._write_required_evidence(
                evidence_dir,
                include_environment=True,
                semantic=True,
            )
            upgrade_path = evidence_dir / "upgrade" / "result.json"
            upgrade = json.loads(upgrade_path.read_text(encoding="utf-8"))
            upgrade["before_table_counts"] = {"platform_audit_events": 1}
            upgrade["after_table_counts"] = {"platform_audit_events": 1}
            upgrade_path.write_text(json.dumps(upgrade), encoding="utf-8")
            output = Path(directory) / "manifest.json"

            with patch("tools.evidence_manifest._git_commit", return_value=self._COMMIT):
                with self.assertRaisesRegex(RuntimeError, "business rows"):
                    generate(
                        evidence_dir,
                        output,
                        remote_ci_run_url="https://github.example.invalid/actions/runs/1",
                        image_digest=self._IMAGE_DIGEST,
                    )

    def test_playwright_summary_accepts_only_completed_chromium_tests(self):
        raw_report = {
            "suites": [
                {
                    "specs": [
                        {
                            "tests": [
                                {
                                    "projectName": "chromium",
                                    "results": [{"status": "passed"}],
                                },
                                {
                                    "projectName": "firefox",
                                    "results": [{"status": "failed"}],
                                },
                            ],
                        },
                    ],
                },
            ],
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "playwright-report.json"
            output = root / "result.json"
            source.write_text(json.dumps(raw_report), encoding="utf-8")
            result = summarize_report(source, output, project="chromium")
            serialized = json.loads(output.read_text(encoding="utf-8"))

        self.assertEqual(result["status"], "passed")
        self.assertEqual(serialized["tests"], {"total": 1, "passed": 1, "failed": 0})

    def test_playwright_summary_rejects_skipped_or_missing_chromium_results(self):
        raw_report = {
            "suites": [
                {
                    "specs": [
                        {
                            "tests": [
                                {
                                    "projectName": "chromium",
                                    "results": [{"status": "skipped"}],
                                },
                            ],
                        },
                    ],
                },
            ],
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "playwright-report.json"
            output = root / "result.json"
            source.write_text(json.dumps(raw_report), encoding="utf-8")
            result = summarize_report(source, output, project="chromium")

        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["tests"], {"total": 1, "passed": 0, "failed": 0})


if __name__ == "__main__":
    unittest.main()
