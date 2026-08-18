import hashlib
import json
import os
import stat
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools.evidence_manifest import MIGRATION_HEAD, generate
from tools.playwright_evidence import summarize_report
from tools.security_scans import (
    REQUIRED_SCAN_GATES,
    WEB_SECURITY_GATE_NAMES,
    summarize_scans,
)
from tools.upgrade_fixture import EXPECTED_N_MINUS_ONE
from tools.week11_performance import (
    SCENARIO_EXPECTED_LOAD,
    SCENARIO_REQUIRED_ITERATIONS,
    summarize_results,
    write_result,
)


class EvidenceManifestTests(unittest.TestCase):
    _COMMIT = "a" * 40
    _IMAGE_DIGEST = "sha256:" + "c" * 64

    @staticmethod
    def _gitleaks_receipt_binding() -> dict[str, str]:
        repository_root = Path(__file__).resolve().parents[3]
        config_path = repository_root / ".gitleaks.toml"
        return {
            "execution_root": ".",
            "execution_root_sha256": hashlib.sha256(
                str(repository_root.resolve()).encode("utf-8")
            ).hexdigest(),
            "config_path": ".gitleaks.toml",
            "config_sha256": hashlib.sha256(config_path.read_bytes()).hexdigest(),
            "source_tree_sha256": EvidenceManifestTests._gitleaks_source_scope_digest(
                repository_root
            ),
            "scan_context": "isolated_read_only_snapshot",
        }

    @staticmethod
    def _gitleaks_source_scope_digest(root: Path) -> str:
        digest = hashlib.sha256()
        digest.update(b"gitleaks-source-scope-v1\0")

        def excluded(parts: tuple[str, ...]) -> bool:
            return (
                (parts and parts[0] == ".git")
                or "tmp" in parts
                or "temp_test" in parts
                or "docs2" in parts
                or "__pycache__" in parts
                or any(part in {"artifact_store", "uploads", "exports"} for part in parts)
                or parts[-1].endswith((".db", ".db-shm", ".db-wal"))
                or parts[:3] == ("ml-platform", "backend", "data")
                or any(
                    parts[index : index + 3]
                    == ("ml-platform", "frontend", "node_modules")
                    for index in range(len(parts) - 2)
                )
            )

        def record(kind: bytes, relative_path: Path, contents: bytes = b"") -> None:
            digest.update(kind)
            for value in (relative_path.as_posix().encode("utf-8"), contents):
                digest.update(len(value).to_bytes(8, "big"))
                digest.update(value)

        def visit(directory: Path) -> None:
            for candidate in sorted(directory.iterdir(), key=lambda item: item.name):
                relative_path = candidate.relative_to(root)
                if excluded(relative_path.parts):
                    continue
                metadata = candidate.lstat()
                if stat.S_ISDIR(metadata.st_mode):
                    record(b"D", relative_path)
                    visit(candidate)
                elif stat.S_ISREG(metadata.st_mode):
                    record(b"F", relative_path, candidate.read_bytes())
                else:
                    raise AssertionError(f"unsafe test source: {candidate}")

        visit(root)
        return digest.hexdigest()

    @classmethod
    def _write_gitleaks_source_root(cls, root: Path) -> Path:
        config_source = Path(__file__).resolve().parents[3] / ".gitleaks.toml"
        root.mkdir(parents=True)
        (root / ".gitleaks.toml").write_bytes(config_source.read_bytes())
        source_path = root / "ml-platform" / "backend" / "app.py"
        source_path.parent.mkdir(parents=True)
        source_path.write_text("safe_value = 'before-receipt'\n", encoding="utf-8")
        return source_path

    @classmethod
    def _gitleaks_receipt_binding_for(cls, root: Path) -> dict[str, str]:
        config_path = root / ".gitleaks.toml"
        return {
            "execution_root": ".",
            "execution_root_sha256": hashlib.sha256(
                str(root.resolve()).encode("utf-8")
            ).hexdigest(),
            "config_path": ".gitleaks.toml",
            "config_sha256": hashlib.sha256(config_path.read_bytes()).hexdigest(),
            "source_tree_sha256": cls._gitleaks_source_scope_digest(root),
            "scan_context": "isolated_read_only_snapshot",
        }

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

    @staticmethod
    def _replace_with_hard_link(path: Path, outside: Path) -> None:
        outside.write_bytes(path.read_bytes())
        path.unlink()
        os.link(outside, path)

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
                    result.update(
                        {
                            "duration_ms": 1000.0,
                            "completed_requests": requests,
                            "terminal_status_counts": {"completed": requests},
                            "completion_samples_ms": [1000.0] * requests,
                        },
                    )
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
                "from_revision": EXPECTED_N_MINUS_ONE,
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
        image_receipts = self._write_security_evidence(root)
        self._write_json(
            root,
            "security/runtime-images.json",
            {
                "schema_version": 1,
                "source_commit": self._COMMIT,
                "components": [
                    {
                        "component": receipt["component"],
                        "services": {
                            "backend": ["migrate", "backend"],
                            "worker": ["worker", "scheduler"],
                            "inference": ["inference-runtime"],
                            "tensorboard": ["tensorboard-gateway"],
                        }[str(receipt["component"])],
                        "reference": receipt["reference"],
                        "image_id": receipt["image_id"],
                        "revision": receipt["revision"],
                    }
                    for receipt in image_receipts
                ],
            },
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

    def _write_security_evidence(self, root: Path) -> list[dict[str, object]]:
        security_root = root / "security"
        image_components = ("backend", "worker", "inference", "tensorboard")
        image_references = tuple(
            f"ml-platform-{component}:test" for component in image_components
        )
        image_ids = tuple(
            f"sha256:{index:064x}"
            for index in range(1, len(image_components) + 1)
        )
        image_receipts = [
            {
                "component": component,
                "reference": reference,
                "evidence_path": (
                    "trivy-image.json"
                    if index == 0
                    else f"trivy-image-{index}.json"
                ),
                "image_id": image_ids[index],
                "revision": self._COMMIT,
                "command": [
                    "trivy",
                    "image",
                    "--exit-code",
                    "1",
                    "--severity",
                    "HIGH,CRITICAL",
                    "--format",
                    "json",
                    "--output",
                    str(
                        "trivy-image.json"
                        if index == 0
                        else f"trivy-image-{index}.json"
                    ),
                    reference,
                ],
                "returncode": 0,
                "status": "passed",
            }
            for index, (component, reference) in enumerate(
                zip(image_components, image_references)
            )
        ]
        scan_gates = {
            "python_dependencies": {
                "status": "passed",
                "returncode": 0,
                "command": [
                    "python", "-m", "pip_audit", "-r", "requirements.txt",
                    "--format", "json", "--output", "pip-audit.json",
                ],
            },
            "source_bandit": {
                "status": "passed",
                "returncode": 0,
                "command": [
                    "bandit", "-r", "app", "-q", "-lll", "-f", "json",
                    "-o", "bandit.json",
                ],
            },
            "frontend_dependencies": {
                "status": "passed",
                "returncode": 0,
                "command": [
                    "npm", "--prefix", "ml-platform/frontend", "audit",
                    "--audit-level=high", "--registry=https://registry.npmjs.org", "--json",
                ],
            },
            "filesystem_trivy": {
                "status": "passed",
                "returncode": 0,
                "command": [
                    "trivy", "fs", "--exit-code", "1", "--severity", "HIGH,CRITICAL",
                    "--format", "json",
                    "--skip-dirs", "tmp",
                    "--skip-dirs", "temp_test",
                    "--skip-dirs", "docs2",
                    "--skip-dirs", "ml-platform/frontend/node_modules",
                    "--output", "trivy-fs.json", ".",
                ],
            },
            "secret_gitleaks": {
                "status": "passed",
                "returncode": 0,
                "command": [
                    "gitleaks", "detect", "--no-git", "--config", ".gitleaks.toml", "--no-banner", "--redact", "--report-format", "json",
                    "--report-path", "gitleaks.json", "--source", ".",
                ],
                **self._gitleaks_receipt_binding(),
            },
        }
        scan_gates["container_image"] = {
            "status": "passed",
            "source_commit": self._COMMIT,
            "images": image_receipts,
        }
        self._write_json(
            security_root,
            "security.json",
            {"status": "passed", "gates": scan_gates},
        )
        raw_reports = {
            "pip-audit.json": {
                "dependencies": [
                    {"name": "cryptography", "version": "50.0.0", "vulns": []},
                    {"name": "jaraco-context", "version": "6.1.0", "vulns": []},
                    {"name": "wheel", "version": "0.46.2", "vulns": []},
                ],
            },
            "bandit.json": {"errors": [], "metrics": {"_totals": {}}, "results": []},
            "npm-audit.json": {
                "auditReportVersion": 2,
                "metadata": {"vulnerabilities": {"high": 0, "critical": 0}},
                "vulnerabilities": {},
            },
            "trivy-fs.json": {
                "SchemaVersion": 2,
                "ArtifactName": ".",
                "ArtifactType": "filesystem",
                "Results": [],
            },
            "gitleaks.json": [],
        }
        for relative_path, report in raw_reports.items():
            self._write_json(security_root, relative_path, report)
        for receipt in image_receipts:
            self._write_json(
                security_root,
                str(receipt["evidence_path"]),
                {
                    "SchemaVersion": 2,
                    "ArtifactName": receipt["reference"],
                    "ArtifactType": "container_image",
                    "Metadata": {"ImageID": receipt["image_id"]},
                    "Results": [],
                },
            )
        self._write_json(
            security_root,
            "web.json",
            {
                "status": "passed",
                "gates": {
                    name: {"status": "passed"}
                    for name in WEB_SECURITY_GATE_NAMES
                },
            },
        )
        summarize_scans(
            security_root,
            security_root / "summary.json",
            source_commit=self._COMMIT,
        )
        return image_receipts

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
            self._write_json(
                root,
                "security/runtime-images.json",
                {
                    "schema_version": 1,
                    "source_commit": self._COMMIT,
                    "components": [],
                },
            )
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
        self.assertEqual(payload["migration_head"], "20260815_11")
        paths = [item["path"] for item in payload["files"]]
        self.assertEqual(paths, sorted(paths))
        self.assertIn("environment.json", paths)
        entry = next(item for item in payload["files"] if item["path"] == "environment.json")
        self.assertEqual(
            entry["sha256"],
            environment_hash,
        )

    def test_manifest_targets_the_current_release_merge_head(self):
        self.assertEqual(MIGRATION_HEAD, "20260815_11")

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

    def test_generate_requires_runtime_image_provenance_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            evidence_dir = Path(directory) / "evidence"
            self._write_required_evidence(
                evidence_dir,
                include_environment=True,
                semantic=True,
            )
            (evidence_dir / "security" / "runtime-images.json").unlink()
            output = Path(directory) / "manifest.json"

            with patch("tools.evidence_manifest._git_commit", return_value=self._COMMIT):
                with self.assertRaisesRegex(FileNotFoundError, "security/runtime-images.json"):
                    generate(
                        evidence_dir,
                        output,
                        remote_ci_run_url="https://github.example.invalid/actions/runs/1",
                        image_digest=self._IMAGE_DIGEST,
                    )

    def test_generate_rejects_runtime_image_provenance_that_does_not_match_receipts(self):
        for component, field, value in (
            ("backend", "reference", "ml-platform-backend:tampered"),
            ("worker", "image_id", "sha256:" + "f" * 64),
            ("inference", "revision", "b" * 40),
            ("tensorboard", "image_id", "sha256:" + "e" * 64),
        ):
            with self.subTest(component=component, field=field), tempfile.TemporaryDirectory() as directory:
                evidence_dir = Path(directory) / "evidence"
                self._write_required_evidence(
                    evidence_dir,
                    include_environment=True,
                    semantic=True,
                )
                provenance_path = evidence_dir / "security" / "runtime-images.json"
                provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
                entry = next(
                    item
                    for item in provenance["components"]
                    if item["component"] == component
                )
                entry[field] = value
                provenance_path.write_text(json.dumps(provenance), encoding="utf-8")
                output = Path(directory) / "manifest.json"

                with patch("tools.evidence_manifest._git_commit", return_value=self._COMMIT):
                    with self.assertRaisesRegex(RuntimeError, "runtime image provenance invalid"):
                        generate(
                            evidence_dir,
                            output,
                            remote_ci_run_url="https://github.example.invalid/actions/runs/1",
                            image_digest=self._IMAGE_DIGEST,
                        )

    def test_generate_rejects_malformed_runtime_image_provenance(self):
        cases = {
            "wrong source commit": lambda value: value.__setitem__("source_commit", "b" * 40),
            "extra component": lambda value: value["components"].append(
                {
                    "component": "unknown",
                    "services": ["unknown"],
                    "reference": "ml-platform-backend:test",
                    "image_id": "sha256:" + "f" * 64,
                    "revision": self._COMMIT,
                },
            ),
            "duplicate component": lambda value: value["components"].__setitem__(
                1,
                {
                    **value["components"][1],
                    "component": "backend",
                },
            ),
            "invalid worker services": lambda value: value["components"][1].__setitem__(
                "services",
                ["worker", "worker"],
            ),
            "uncontrolled field": lambda value: value["components"][0].__setitem__(
                "unrecognized",
                "value",
            ),
        }
        for description, mutate in cases.items():
            with self.subTest(description=description), tempfile.TemporaryDirectory() as directory:
                evidence_dir = Path(directory) / "evidence"
                self._write_required_evidence(
                    evidence_dir,
                    include_environment=True,
                    semantic=True,
                )
                provenance_path = evidence_dir / "security" / "runtime-images.json"
                provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
                mutate(provenance)
                provenance_path.write_text(json.dumps(provenance), encoding="utf-8")
                output = Path(directory) / "manifest.json"

                with patch("tools.evidence_manifest._git_commit", return_value=self._COMMIT):
                    with self.assertRaisesRegex(RuntimeError, "runtime image provenance invalid"):
                        generate(
                            evidence_dir,
                            output,
                            remote_ci_run_url="https://github.example.invalid/actions/runs/1",
                            image_digest=self._IMAGE_DIGEST,
                        )

    def test_generate_rejects_sensitive_or_absolute_runtime_image_provenance(self):
        cases = {
            "absolute reference": (
                lambda value: value["components"][0].__setitem__("reference", "/tmp/image"),
                ValueError,
                "absolute path",
            ),
            "secret field": (
                lambda value: value["components"][0].__setitem__("api_key", "secret"),
                ValueError,
                "sensitive value",
            ),
        }
        for description, (mutate, error, message) in cases.items():
            with self.subTest(description=description), tempfile.TemporaryDirectory() as directory:
                evidence_dir = Path(directory) / "evidence"
                self._write_required_evidence(
                    evidence_dir,
                    include_environment=True,
                    semantic=True,
                )
                provenance_path = evidence_dir / "security" / "runtime-images.json"
                provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
                mutate(provenance)
                provenance_path.write_text(json.dumps(provenance), encoding="utf-8")
                output = Path(directory) / "manifest.json"

                with patch("tools.evidence_manifest._git_commit", return_value=self._COMMIT):
                    with self.assertRaisesRegex(error, message):
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

    def test_generate_rejects_hard_linked_security_summary_and_raw_reports(self):
        for relative_path in (
            "security/summary.json",
            "security/pip-audit.json",
            "security/bandit.json",
            "security/npm-audit.json",
            "security/trivy-fs.json",
            "security/gitleaks.json",
            "security/web.json",
        ):
            with self.subTest(relative_path=relative_path), tempfile.TemporaryDirectory() as directory:
                evidence_dir = Path(directory) / "evidence"
                self._write_required_evidence(
                    evidence_dir,
                    include_environment=True,
                    semantic=True,
                )
                path = evidence_dir / relative_path
                self._replace_with_hard_link(path, Path(directory) / "outside.json")
                output = Path(directory) / "manifest.json"

                with patch("tools.evidence_manifest._git_commit", return_value=self._COMMIT):
                    with self.assertRaises((FileNotFoundError, RuntimeError)):
                        generate(
                            evidence_dir,
                            output,
                            remote_ci_run_url="https://github.example.invalid/actions/runs/1",
                            image_digest=self._IMAGE_DIGEST,
                        )

    def test_generate_rejects_hard_linked_container_image_receipts(self):
        for relative_path in (
            "security/trivy-image.json",
            "security/trivy-image-1.json",
            "security/trivy-image-2.json",
            "security/trivy-image-3.json",
        ):
            with self.subTest(relative_path=relative_path), tempfile.TemporaryDirectory() as directory:
                evidence_dir = Path(directory) / "evidence"
                self._write_required_evidence(
                    evidence_dir,
                    include_environment=True,
                    semantic=True,
                )
                path = evidence_dir / relative_path
                self._replace_with_hard_link(path, Path(directory) / "outside.json")
                output = Path(directory) / "manifest.json"

                with patch("tools.evidence_manifest._git_commit", return_value=self._COMMIT):
                    with self.assertRaises(RuntimeError):
                        generate(
                            evidence_dir,
                            output,
                            remote_ci_run_url="https://github.example.invalid/actions/runs/1",
                            image_digest=self._IMAGE_DIGEST,
                        )

    def test_generate_rejects_weakened_security_scan_commands(self):
        mutations = (
            ("source_bandit", lambda command: command.__setitem__(4, "-ll")),
            ("filesystem_trivy", lambda command: command.__setitem__(5, "LOW")),
            ("filesystem_trivy", lambda command: command.__setitem__(3, "0")),
            ("filesystem_trivy", lambda command: command.remove("temp_test")),
            ("secret_gitleaks", lambda command: command.remove("--no-git")),
            ("secret_gitleaks", lambda command: command.remove("--config")),
            (
                "secret_gitleaks",
                lambda command: command.__setitem__(
                    command.index(".gitleaks.toml"),
                    ".gitleaks-relaxed.toml",
                ),
            ),
            ("container_image", lambda command: command.__setitem__(5, "LOW")),
            ("container_image", lambda command: command.__setitem__(3, "0")),
        )
        for gate_name, mutate in mutations:
            with self.subTest(gate_name=gate_name), tempfile.TemporaryDirectory() as directory:
                evidence_dir = Path(directory) / "evidence"
                self._write_required_evidence(
                    evidence_dir,
                    include_environment=True,
                    semantic=True,
                )
                security_path = evidence_dir / "security" / "summary.json"
                security = json.loads(security_path.read_text(encoding="utf-8"))
                if gate_name == "container_image":
                    command = security["gates"][gate_name]["images"][0]["command"]
                else:
                    command = security["gates"][gate_name]["command"]
                mutate(command)
                security_path.write_text(json.dumps(security), encoding="utf-8")
                output = Path(directory) / "manifest.json"

                with patch("tools.evidence_manifest._git_commit", return_value=self._COMMIT):
                    with self.assertRaisesRegex(RuntimeError, "scanner receipt invalid"):
                        generate(
                            evidence_dir,
                            output,
                        remote_ci_run_url="https://github.example.invalid/actions/runs/1",
                        image_digest=self._IMAGE_DIGEST,
                    )

    def test_generate_rejects_trivy_subdirectory_scope_receipt(self):
        with tempfile.TemporaryDirectory() as directory:
            evidence_dir = Path(directory) / "evidence"
            self._write_required_evidence(
                evidence_dir,
                include_environment=True,
                semantic=True,
            )
            summary_path = evidence_dir / "security" / "summary.json"
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
            summary["gates"]["filesystem_trivy"]["command"][-1] = (
                "ml-platform/backend/app"
            )
            summary_path.write_text(json.dumps(summary), encoding="utf-8")
            raw_path = evidence_dir / "security" / "trivy-fs.json"
            raw = json.loads(raw_path.read_text(encoding="utf-8"))
            raw["ArtifactName"] = "ml-platform/backend/app"
            raw_path.write_text(json.dumps(raw), encoding="utf-8")
            output = Path(directory) / "manifest.json"

            with patch("tools.evidence_manifest._git_commit", return_value=self._COMMIT):
                with self.assertRaisesRegex(
                    RuntimeError,
                    "filesystem_trivy scanner receipt invalid",
                ):
                    generate(
                        evidence_dir,
                        output,
                        remote_ci_run_url="https://github.example.invalid/actions/runs/1",
                        image_digest=self._IMAGE_DIGEST,
                    )
            self.assertFalse(output.exists())

    def test_generate_rejects_tampered_gitleaks_root_or_config_binding_after_resummarize(self):
        mutations = (
            ("execution_root", "ml-platform"),
            ("execution_root_sha256", "0" * 64),
            ("config_path", "child/.gitleaks.toml"),
            ("config_sha256", "0" * 64),
            ("source_tree_sha256", "0" * 64),
            ("scan_context", "live_repository"),
        )
        for field, value in mutations:
            with self.subTest(field=field), tempfile.TemporaryDirectory() as directory:
                evidence_dir = Path(directory) / "evidence"
                self._write_required_evidence(
                    evidence_dir,
                    include_environment=True,
                    semantic=True,
                )
                security_root = evidence_dir / "security"
                security_path = security_root / "security.json"
                security = json.loads(security_path.read_text(encoding="utf-8"))
                security["gates"]["secret_gitleaks"][field] = value
                security_path.write_text(json.dumps(security), encoding="utf-8")
                summary = summarize_scans(
                    security_root,
                    security_root / "summary.json",
                    source_commit=self._COMMIT,
                )
                output = Path(directory) / "manifest.json"

                self.assertEqual(summary["status"], "failed")
                with patch("tools.evidence_manifest._git_commit", return_value=self._COMMIT):
                    with self.assertRaisesRegex(RuntimeError, "required evidence did not pass"):
                        generate(
                            evidence_dir,
                            output,
                        remote_ci_run_url="https://github.example.invalid/actions/runs/1",
                        image_digest=self._IMAGE_DIGEST,
                    )

    def test_generate_rejects_directly_tampered_gitleaks_receipt_binding(self):
        mutations = (
            ("execution_root", "ml-platform"),
            ("execution_root_sha256", "0" * 64),
            ("config_path", "child/.gitleaks.toml"),
            ("config_sha256", "0" * 64),
            ("source_tree_sha256", "0" * 64),
            ("scan_context", "live_repository"),
        )
        for field, value in mutations:
            with self.subTest(field=field), tempfile.TemporaryDirectory() as directory:
                evidence_dir = Path(directory) / "evidence"
                self._write_required_evidence(
                    evidence_dir,
                    include_environment=True,
                    semantic=True,
                )
                summary_path = evidence_dir / "security" / "summary.json"
                summary = json.loads(summary_path.read_text(encoding="utf-8"))
                summary["gates"]["secret_gitleaks"][field] = value
                summary_path.write_text(json.dumps(summary), encoding="utf-8")
                output = Path(directory) / "manifest.json"

                with patch("tools.evidence_manifest._git_commit", return_value=self._COMMIT):
                    with self.assertRaisesRegex(
                        RuntimeError,
                        "secret_gitleaks scanner receipt invalid",
                    ):
                        generate(
                            evidence_dir,
                            output,
                            remote_ci_run_url="https://github.example.invalid/actions/runs/1",
                            image_digest=self._IMAGE_DIGEST,
                )
                self.assertFalse(output.exists())

    def test_generate_rejects_gitleaks_stale_source_tree_binding(self):
        with tempfile.TemporaryDirectory() as directory:
            repository_root = Path(directory) / "repository"
            source_path = self._write_gitleaks_source_root(repository_root)
            evidence_dir = Path(directory) / "evidence"
            self._write_required_evidence(
                evidence_dir,
                include_environment=True,
                semantic=True,
            )
            summary_path = evidence_dir / "security" / "summary.json"
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
            summary["gates"]["secret_gitleaks"].update(
                self._gitleaks_receipt_binding_for(repository_root)
            )
            summary_path.write_text(json.dumps(summary), encoding="utf-8")
            source_path.write_text(
                "safe_value = 'changed-after-receipt'\n",
                encoding="utf-8",
            )
            output = Path(directory) / "manifest.json"
            module_path = (
                repository_root
                / "ml-platform"
                / "backend"
                / "tools"
                / "evidence_manifest.py"
            )

            with (
                patch("tools.evidence_manifest.__file__", str(module_path)),
                patch("tools.evidence_manifest._git_commit", return_value=self._COMMIT),
                self.assertRaisesRegex(
                    RuntimeError,
                    "secret_gitleaks scanner receipt invalid",
                ),
            ):
                generate(
                    evidence_dir,
                    output,
                    remote_ci_run_url="https://github.example.invalid/actions/runs/1",
                    image_digest=self._IMAGE_DIGEST,
                )
            self.assertFalse(output.exists())

    def test_generate_rejects_container_gate_without_each_image_scanner_receipt(self):
        with tempfile.TemporaryDirectory() as directory:
            evidence_dir = Path(directory) / "evidence"
            self._write_required_evidence(
                evidence_dir,
                include_environment=True,
                semantic=True,
            )
            security_path = evidence_dir / "security" / "summary.json"
            security = json.loads(security_path.read_text(encoding="utf-8"))
            security["gates"]["container_image"]["images"] = [
                {"component": component, "status": "passed"}
                for component in ("backend", "worker", "inference", "tensorboard")
            ]
            security_path.write_text(json.dumps(security), encoding="utf-8")
            output = Path(directory) / "manifest.json"

            with patch("tools.evidence_manifest._git_commit", return_value=self._COMMIT):
                with self.assertRaisesRegex(RuntimeError, "container_image scanner receipt missing"):
                    generate(
                        evidence_dir,
                        output,
                        remote_ci_run_url="https://github.example.invalid/actions/runs/1",
                        image_digest=self._IMAGE_DIGEST,
                    )

    def test_generate_rejects_unbound_container_image_scanner_receipts(self):
        mutations = (
            ("component", "backend"),
            ("reference", "ml-platform-backend:test"),
            ("evidence_path", "trivy-image-9.json"),
            ("image_id", "sha256:" + ("f" * 64)),
            ("revision", "b" * 40),
            ("command", "ml-platform-backend:test"),
            ("source_commit", "b" * 40),
        )
        for field, value in mutations:
            with self.subTest(field=field), tempfile.TemporaryDirectory() as directory:
                evidence_dir = Path(directory) / "evidence"
                self._write_required_evidence(
                    evidence_dir,
                    include_environment=True,
                    semantic=True,
                )
                security_path = evidence_dir / "security" / "summary.json"
                security = json.loads(security_path.read_text(encoding="utf-8"))
                container_gate = security["gates"]["container_image"]
                if field == "source_commit":
                    container_gate[field] = value
                elif field == "command":
                    container_gate["images"][1]["command"][-1] = value
                else:
                    container_gate["images"][1][field] = value
                security_path.write_text(json.dumps(security), encoding="utf-8")
                output = Path(directory) / "manifest.json"

                with patch("tools.evidence_manifest._git_commit", return_value=self._COMMIT):
                    with self.assertRaisesRegex(
                        RuntimeError,
                        "container_image scanner receipt invalid",
                    ):
                        generate(
                            evidence_dir,
                            output,
                            remote_ci_run_url="https://github.example.invalid/actions/runs/1",
                            image_digest=self._IMAGE_DIGEST,
                        )

    def test_generate_rejects_absolute_paths_in_security_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            evidence_dir = Path(directory) / "evidence"
            self._write_required_evidence(
                evidence_dir,
                include_environment=True,
                semantic=True,
            )
            security_path = evidence_dir / "security" / "summary.json"
            security = json.loads(security_path.read_text(encoding="utf-8"))
            security["gates"]["source_bandit"]["command"] = [
                "bandit",
                r"C:\acceptance\bandit.json",
            ]
            security_path.write_text(json.dumps(security), encoding="utf-8")
            output = Path(directory) / "manifest.json"

            with patch("tools.evidence_manifest._git_commit", return_value=self._COMMIT):
                with self.assertRaisesRegex(ValueError, "absolute path"):
                    generate(
                        evidence_dir,
                        output,
                        remote_ci_run_url="https://github.example.invalid/actions/runs/1",
                    image_digest=self._IMAGE_DIGEST,
                )

    def test_generate_rejects_quoted_absolute_path_in_security_receipt(self):
        with tempfile.TemporaryDirectory() as directory:
            evidence_dir = Path(directory) / "evidence"
            self._write_required_evidence(
                evidence_dir,
                include_environment=True,
                semantic=True,
            )
            security_path = evidence_dir / "security" / "summary.json"
            security = json.loads(security_path.read_text(encoding="utf-8"))
            security["gates"]["source_bandit"]["command"] = [
                "bandit",
                r"--output='C:\acceptance\bandit.json'",
            ]
            security_path.write_text(json.dumps(security), encoding="utf-8")
            output = Path(directory) / "manifest.json"

            with patch("tools.evidence_manifest._git_commit", return_value=self._COMMIT):
                with self.assertRaisesRegex(ValueError, "absolute path"):
                    generate(
                        evidence_dir,
                        output,
                        remote_ci_run_url="https://github.example.invalid/actions/runs/1",
                        image_digest=self._IMAGE_DIGEST,
                    )

    def test_generate_rejects_missing_raw_scanner_evidence_after_summary(self):
        with tempfile.TemporaryDirectory() as directory:
            evidence_dir = Path(directory) / "evidence"
            self._write_required_evidence(
                evidence_dir,
                include_environment=True,
                semantic=True,
            )
            (evidence_dir / "security" / "bandit.json").unlink()
            output = Path(directory) / "manifest.json"

            with patch("tools.evidence_manifest._git_commit", return_value=self._COMMIT):
                with self.assertRaisesRegex(
                    RuntimeError,
                    "source_bandit raw scanner evidence invalid",
                ):
                    generate(
                        evidence_dir,
                        output,
                        remote_ci_run_url="https://github.example.invalid/actions/runs/1",
                        image_digest=self._IMAGE_DIGEST,
                    )

    def test_generate_rejects_raw_trivy_finding_after_passing_summary(self):
        with tempfile.TemporaryDirectory() as directory:
            evidence_dir = Path(directory) / "evidence"
            self._write_required_evidence(
                evidence_dir,
                include_environment=True,
                semantic=True,
            )
            self._write_json(
                evidence_dir,
                "security/trivy-fs.json",
                {
                    "SchemaVersion": 2,
                    "ArtifactName": ".",
                    "ArtifactType": "filesystem",
                    "Results": {
                        "Vulnerabilities": [{"Severity": "HIGH"}],
                    },
                },
            )
            output = Path(directory) / "manifest.json"

            with patch("tools.evidence_manifest._git_commit", return_value=self._COMMIT):
                with self.assertRaisesRegex(
                    RuntimeError,
                    "filesystem_trivy raw scanner evidence invalid",
                ):
                    generate(
                        evidence_dir,
                        output,
                        remote_ci_run_url="https://github.example.invalid/actions/runs/1",
                    image_digest=self._IMAGE_DIGEST,
                )

    def test_generate_rejects_container_raw_trivy_finding_after_passing_summary(self):
        with tempfile.TemporaryDirectory() as directory:
            evidence_dir = Path(directory) / "evidence"
            self._write_required_evidence(
                evidence_dir,
                include_environment=True,
                semantic=True,
            )
            self._write_json(
                evidence_dir,
                "security/trivy-image-1.json",
                {
                    "SchemaVersion": 2,
                    "ArtifactName": "ml-platform-worker:test",
                    "ArtifactType": "container_image",
                    "Metadata": {"ImageID": "sha256:" + ("2" * 64)},
                    "Results": [{"Vulnerabilities": [{"Severity": "HIGH"}]}],
                },
            )
            output = Path(directory) / "manifest.json"

            with patch("tools.evidence_manifest._git_commit", return_value=self._COMMIT):
                with self.assertRaisesRegex(
                    RuntimeError,
                    "container_image scanner receipt invalid",
                ):
                    generate(
                        evidence_dir,
                        output,
                        remote_ci_run_url="https://github.example.invalid/actions/runs/1",
                        image_digest=self._IMAGE_DIGEST,
                    )

    def test_generate_rejects_incomplete_raw_web_gate_after_passing_summary(self):
        with tempfile.TemporaryDirectory() as directory:
            evidence_dir = Path(directory) / "evidence"
            self._write_required_evidence(
                evidence_dir,
                include_environment=True,
                semantic=True,
            )
            raw_path = evidence_dir / "security" / "web.json"
            raw = json.loads(raw_path.read_text(encoding="utf-8"))
            raw["gates"].pop("viewer_read")
            raw_path.write_text(json.dumps(raw), encoding="utf-8")
            output = Path(directory) / "manifest.json"

            with patch("tools.evidence_manifest._git_commit", return_value=self._COMMIT):
                with self.assertRaisesRegex(
                    RuntimeError,
                    "web_security raw scanner evidence invalid",
                ):
                    generate(
                        evidence_dir,
                        output,
                        remote_ci_run_url="https://github.example.invalid/actions/runs/1",
                        image_digest=self._IMAGE_DIGEST,
                    )

    def test_generate_rejects_absolute_paths_in_raw_security_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            evidence_dir = Path(directory) / "evidence"
            self._write_required_evidence(
                evidence_dir,
                include_environment=True,
                semantic=True,
            )
            raw_path = evidence_dir / "security" / "trivy-fs.json"
            raw = json.loads(raw_path.read_text(encoding="utf-8"))
            raw["ArtifactName"] = r"C:\acceptance\repository"
            raw_path.write_text(json.dumps(raw), encoding="utf-8")
            output = Path(directory) / "manifest.json"

            with patch("tools.evidence_manifest._git_commit", return_value=self._COMMIT):
                with self.assertRaisesRegex(ValueError, "absolute path"):
                    generate(
                        evidence_dir,
                        output,
                        remote_ci_run_url="https://github.example.invalid/actions/runs/1",
                    image_digest=self._IMAGE_DIGEST,
                )

    def test_generate_rejects_embedded_absolute_paths_in_raw_security_evidence(self):
        for artifact_name in (
            "scan failed at /tmp/acceptance/repository",
            r"scan failed at \\server\share\repository",
        ):
            with self.subTest(artifact_name=artifact_name), tempfile.TemporaryDirectory() as directory:
                evidence_dir = Path(directory) / "evidence"
                self._write_required_evidence(
                    evidence_dir,
                    include_environment=True,
                    semantic=True,
                )
                raw_path = evidence_dir / "security" / "trivy-fs.json"
                raw = json.loads(raw_path.read_text(encoding="utf-8"))
                raw["ArtifactName"] = artifact_name
                raw_path.write_text(json.dumps(raw), encoding="utf-8")
                output = Path(directory) / "manifest.json"

                with patch("tools.evidence_manifest._git_commit", return_value=self._COMMIT):
                    with self.assertRaisesRegex(ValueError, "absolute path"):
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
