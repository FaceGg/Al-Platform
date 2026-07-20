# Weeks 11-12 Integration and Acceptance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build reproducible performance, backup/restore, N-1 upgrade, security-scan, browser-E2E, and evidence-manifest tooling for the Week 9-12 MLOps core, then run the final gates against one frozen application version.

**Architecture:** Independent verification tools write only to `temp_test/week11-12` and consume stable HTTP, PostgreSQL, MinIO, Alembic, and notification-receiver contracts. Week 11 tools may be implemented immediately; measured performance and Week 12 conclusions wait for the Week 9 release contract and the Week 10 security/notification migration `20260720_10_security_notifications` to be frozen. Changes to Compose, CI, manifests, and status documents are serialized through the primary integrator.

**Tech Stack:** Python 3.11, `unittest`, FastAPI `TestClient`/HTTPX, PostgreSQL 16, MinIO, Redis/Celery, Alembic, Playwright Chromium, npm audit, pip-audit, Trivy, Gitleaks, and GitHub Actions.

---

## Scope and Gates

The current repository already contains `ml-platform/backend/run_suite.py`, Week 1-8 ownership in `tests/week_manifest.py`, `tests/test_production_stack.py`, `tests/test_inference_production_stack.py`, `frontend/playwright.config.ts`, and a production Compose/CI stack. Do not duplicate those tests. Add only the Week 11-12 verification modules listed below.

Work is classified as follows:

| Classification | Work | Earliest start | Completion gate |
|---|---|---:|---|
| Immediate | Harness contracts, environment manifest, backup/restore code, N-1 fixture, scan wrapper, receiver fixture, report schemas | Now | Unit tests pass without Week 9/10 services |
| Wait for freeze | HTTP load scenarios, rollout/rollback assertions, notification E2E, final migration assertions | After Week 9 API/schema freeze and Week 10 `20260720_10_security_notifications` | Contract tests and isolated stack pass |
| Final only | Three-run threshold decision, restore/RTO result, N-1 result, remote CI result, status/document updates | After all upstream gates | Evidence manifest is complete and reproducible |

The final implementation must prove these thresholds on a fixed 4-vCPU/8-GiB Linux environment, using three measured iterations after warmup:

- Core read APIs at 20 concurrent users: p95 <= 300 ms, p99 <= 800 ms, error rate < 0.1%.
- Warm single-record inference at 20 concurrent users: p95 <= 200 ms, p99 <= 500 ms, error rate < 0.1%.
- Task enqueue p95 <= 1 s.
- Full welding workflow succeeds 10/10 and completes within 90 s.
- Rollout/rollback 5xx < 1%, no continuous outage > 5 s, automatic recovery <= 2 min.
- PostgreSQL + MinIO restore RTO <= 30 min and documented RPO <= 24 h.

## File Map

**Create immediately:**

- `ml-platform/backend/tools/week11_performance.py`: deterministic HTTP/load runner, percentile summaries, threshold evaluation, and JSON output.
- `ml-platform/backend/tools/acceptance_environment.py`: non-secret environment, Git, image, migration, and dependency manifest collector.
- `ml-platform/backend/tools/backup_restore.py`: PostgreSQL custom-format dump/restore and MinIO mirror/restore orchestration with SHA-256 manifest.
- `ml-platform/backend/tools/upgrade_fixture.py`: N-1 database fixture creation, upgrade-to-head, repeatability, and compatibility checks.
- `ml-platform/backend/tools/security_scans.py`: dependency/source/container/secret scan command runner with redacted result records.
- `ml-platform/backend/tools/notification_receiver.py`: loopback test receiver for controlled WeCom/Webhook/email test adapters.
- `ml-platform/backend/tests/test_week11_12_tools.py`: unit tests for all immediate tools and redaction behavior.
- `ml-platform/backend/tests/test_week12_security_gates.py`: scan-command and evidence-secret regression tests.

**Create after Week 9/10 freeze:**

- `ml-platform/backend/tests/test_week11_contracts.py`: rollout, inference, enqueue, and notification contract checks against the frozen API.
- `ml-platform/frontend/e2e/week12-acceptance.spec.ts`: four-role/outsider browser acceptance, rollout/rollback, rate limiting, audit, and notification flows.

**Create at final integration:**

- `docs/week11-performance-baseline.md`: reviewed three-run measurements and threshold decision.
- `docs/week12-acceptance.md`: final acceptance report with local/remote evidence and residual risk.
- `docs/evidence/week11-12-manifest.json`: machine-readable hashes and provenance for every evidence file.
- `ml-platform/backend/tools/evidence_manifest.py`: deterministic final evidence hashing and provenance CLI.

**Modify only in the primary integration lane:**

- `.github/workflows/ci.yml`: add Week 11 performance, Week 12 scans, backup/restore, N-1, and browser evidence jobs.
- `docker-compose.yml`: add only the receiver/backup test overrides required by the frozen notification stack; preserve the production service graph.
- `ml-platform/backend/tests/week_manifest.py`: register new modules exactly once under Weeks 11 and 12 after they exist.
- `DEVELOPMENT_PLAN.md`, `PLATFORM_STATUS.md`, and delivery docs: update only after gates and evidence are complete.

## Tasks

### Task 1: Freeze Tool Contracts and Output Layout

**Files:**
- Create: `ml-platform/backend/tools/week11_performance.py`
- Create: `ml-platform/backend/tools/acceptance_environment.py`
- Create: `ml-platform/backend/tests/test_week11_12_tools.py`

- [ ] **Step 1 (2-5 min): Write the failing percentile and output-contract tests.**

```python
import json
import tempfile
import unittest
from pathlib import Path

from tools.week11_performance import percentile, evaluate_thresholds, write_result


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

    def test_write_result_creates_machine_readable_json(self):
        with tempfile.TemporaryDirectory() as directory:
            path = write_result(Path(directory) / "run.json", {"status": "passed"})
            self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["status"], "passed")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2 (2-5 min): Run the tests and verify the new tool is absent.**

Run: `python -m unittest tests.test_week11_12_tools.PerformanceToolContractTests -v`

Expected: `ImportError: cannot import name 'percentile' from 'tools.week11_performance'`.

- [ ] **Step 3 (2-5 min): Implement the deterministic utility functions.**

```python
import json
import math
from pathlib import Path


def percentile(values: list[float], quantile: float) -> float:
    if not values or not 0.0 <= quantile <= 1.0:
        raise ValueError("values and quantile are required")
    ordered = sorted(float(value) for value in values)
    position = (len(ordered) - 1) * quantile
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    fraction = position - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * fraction


def evaluate_thresholds(metrics: dict[str, float], limits: dict[str, float]) -> dict:
    gates = {
        name: {"value": metrics[name], "limit": limits[name], "passed": metrics[name] <= limits[name]}
        for name in limits
    }
    return {"status": "passed" if all(item["passed"] for item in gates.values()) else "failed", "gates": gates}


def write_result(path: Path, result: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, ensure_ascii=True, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path
```

- [ ] **Step 4 (2-5 min): Add the environment-manifest contract and test its redaction.**

```python
from tools.acceptance_environment import collect_environment


class EnvironmentManifestTests(unittest.TestCase):
    def test_manifest_contains_versions_but_no_secret_values(self):
        manifest = collect_environment({"SECRET_KEY": "test-secret", "DATABASE_URL": "postgresql://u:p@db/app"})
        serialized = json.dumps(manifest)
        self.assertIn("python", manifest["runtime"])
        self.assertNotIn("test-secret", serialized)
        self.assertNotIn("u:p@", serialized)
```

Implement `collect_environment` with `platform.platform()`, `sys.version`, `git rev-parse HEAD`, package versions, `alembic current`, and an allowlist of non-secret environment keys; replace credentials and URL userinfo with `[redacted]` before serialization.

```python
import os
import platform
import subprocess
import sys
import argparse
import json
from pathlib import Path
import psutil


def _command_output(command: list[str]) -> str:
    completed = subprocess.run(command, capture_output=True, text=True, check=False)
    return completed.stdout.strip() if completed.returncode == 0 else "unavailable"


def collect_environment(environment: dict[str, str] | None = None) -> dict:
    values = environment or os.environ
    allowed = {name: values[name] for name in ("APP_MODE", "TASK_BACKEND", "ARTIFACT_STORAGE_BACKEND") if name in values}
    return {
        "runtime": {
            "python": sys.version.split()[0],
            "platform": platform.platform(),
            "cpu_count": os.cpu_count(),
            "memory_bytes": psutil.virtual_memory().total,
        },
        "git": {"commit": _command_output(["git", "rev-parse", "HEAD"])},
        "migration": {"current": _command_output(["alembic", "current"])},
        "container": {
            "image_digest": values.get("ACCEPTANCE_IMAGE_DIGEST", "unavailable"),
            "compose": _command_output(["docker", "compose", "ps", "--format", "json"]),
        },
        "configuration": allowed,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(collect_environment(), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 5 (2-5 min): Run the focused tool tests and record the expected GREEN result.**

Run: `python -m unittest tests.test_week11_12_tools -v`

Expected: all utility, JSON, and environment-redaction tests pass; no secret literal appears in `temp_test/week11-12`.

### Task 2: Implement the Reproducible Performance Harness

**Files:**
- Modify: `ml-platform/backend/tools/week11_performance.py`
- Modify: `ml-platform/backend/tests/test_week11_12_tools.py`

- [ ] **Step 1 (2-5 min): Add a failing HTTP scenario test using an in-process fake server.**

```python
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import threading
from tools.week11_performance import run_http_scenario


class _OkHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"{}")
    def log_message(self, *_args):
        return


class PerformanceScenarioTests(unittest.TestCase):
    def test_scenario_records_status_latency_and_error_rate(self):
        server = ThreadingHTTPServer(("127.0.0.1", 0), _OkHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            result = run_http_scenario(f"http://127.0.0.1:{server.server_port}/", concurrency=2, requests_per_worker=3)
        finally:
            server.shutdown()
            thread.join()
        self.assertEqual(result["requests"], 6)
        self.assertEqual(result["errors"], 0)
        self.assertIn("p95_ms", result)
```

- [ ] **Step 2 (2-5 min): Run the scenario test and verify the missing runner failure.**

Run: `python -m unittest tests.test_week11_12_tools.PerformanceScenarioTests -v`

Expected: `ImportError` for `run_http_scenario`.

- [ ] **Step 3 (2-5 min): Implement the bounded concurrent runner and CLI.**

```python
import argparse
import concurrent.futures
import os
import time
from urllib.request import Request, urlopen


def _request(url: str, timeout: float, method: str, body: bytes | None, headers: dict[str, str]) -> tuple[float, int]:
    started = time.perf_counter()
    try:
        request_headers = {"User-Agent": "ml-platform-week11", **headers}
        with urlopen(Request(url, data=body, headers=request_headers, method=method), timeout=timeout) as response:
            response.read(1024)
            return (time.perf_counter() - started) * 1000.0, response.status
    except Exception:
        return (time.perf_counter() - started) * 1000.0, 599


def run_http_scenario(url: str, concurrency: int, requests_per_worker: int, timeout: float = 10.0, method: str = "GET", body: bytes | None = None, headers: dict[str, str] | None = None) -> dict:
    if concurrency < 1 or requests_per_worker < 1:
        raise ValueError("concurrency and requests_per_worker must be positive")
    total = concurrency * requests_per_worker
    with concurrent.futures.ThreadPoolExecutor(max_workers=concurrency) as pool:
        samples = list(pool.map(lambda _: _request(url, timeout, method, body, headers or {}), range(total)))
    latencies = [latency for latency, _ in samples]
    errors = sum(1 for _, status in samples if status >= 400)
    return {
        "requests": total,
        "errors": errors,
        "error_rate": errors / total,
        "p95_ms": percentile(latencies, 0.95),
        "p99_ms": percentile(latencies, 0.99),
        "samples_ms": latencies,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    run = subparsers.add_parser("run")
    run.add_argument("--url", required=True)
    run.add_argument("--concurrency", type=int, default=20)
    run.add_argument("--requests-per-worker", type=int, default=100)
    run.add_argument("--warmup", type=int, default=0)
    run.add_argument("--scenario", required=True)
    run.add_argument("--iteration", type=int, required=True)
    run.add_argument("--method", choices=("GET", "POST"), default="GET")
    run.add_argument("--body-file", type=Path)
    run.add_argument("--bearer-env")
    run.add_argument("--api-key-env")
    run.add_argument("--output", type=Path, required=True)
    summary = subparsers.add_parser("summarize")
    summary.add_argument("--input-dir", type=Path, required=True)
    summary.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "summarize":
        results = [json.loads(path.read_text(encoding="utf-8")) for path in sorted(args.input_dir.glob("*.json")) if path.name != args.output.name]
        write_result(args.output, {"status": "passed" if results and all(item.get("errors", 1) == 0 for item in results) else "failed", "iterations": results})
        return 0
    body = args.body_file.read_bytes() if args.body_file else None
    headers = {"Content-Type": "application/json"} if body else {}
    if args.bearer_env:
        headers["Authorization"] = f"Bearer {os.environ[args.bearer_env]}"
    if args.api_key_env:
        headers["X-API-Key"] = os.environ[args.api_key_env]
    if args.warmup:
        run_http_scenario(args.url, args.concurrency, args.warmup, method=args.method, body=body, headers=headers)
    result = run_http_scenario(args.url, args.concurrency, args.requests_per_worker, method=args.method, body=body, headers=headers)
    result.update({"scenario": args.scenario, "iteration": args.iteration})
    write_result(args.output, result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4 (2-5 min): Run the focused harness tests.**

Run: `python -m unittest tests.test_week11_12_tools -v`

Expected: all harness tests pass, with `requests=6` for the fake-server test and finite p95/p99 values.

### Task 3: Add Backup, Restore, and Integrity Verification

**Files:**
- Create: `ml-platform/backend/tools/backup_restore.py`
- Modify: `ml-platform/backend/tests/test_week11_12_tools.py`

- [ ] **Step 1 (2-5 min): Write failing subprocess and manifest tests.**

```python
from unittest.mock import patch
from tools.backup_restore import create_backup_manifest, run_backup_command


class BackupRestoreTests(unittest.TestCase):
    def test_backup_command_rejects_credentials_in_output(self):
        with patch("tools.backup_restore.subprocess.run") as run:
            run.return_value.stdout = "dump completed"
            run.return_value.returncode = 0
            result = run_backup_command(["pg_dump", "--file", "backup.dump"])
        self.assertEqual(result["returncode"], 0)
        self.assertNotIn("password", json.dumps(result).lower())

    def test_manifest_contains_sha256_and_relative_paths(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "dump.bin"
            path.write_bytes(b"backup")
            manifest = create_backup_manifest(Path(directory), "20260720T120000Z")
        self.assertEqual(manifest["files"][0]["path"], "dump.bin")
        self.assertEqual(len(manifest["files"][0]["sha256"]), 64)
```

- [ ] **Step 2 (2-5 min): Run the tests and verify the missing backup module failure.**

Run: `python -m unittest tests.test_week11_12_tools.BackupRestoreTests -v`

Expected: `ImportError: cannot import name 'create_backup_manifest'`.

- [ ] **Step 3 (2-5 min): Implement safe PostgreSQL/MinIO commands and SHA-256 manifesting.**

```python
import argparse
import hashlib
import json
import os
import subprocess
from pathlib import Path


def run_backup_command(command: list[str]) -> dict:
    if any("password" in item.lower() or "secret" in item.lower() for item in command):
        raise ValueError("credentials must be passed through the environment")
    completed = subprocess.run(command, capture_output=True, text=True, check=False)
    safe_command = [Path(command[0]).name]
    for item in command[1:]:
        safe_command.append("[redacted-url]" if "://" in item else item)
    return {"command": safe_command, "returncode": completed.returncode, "stdout": completed.stdout[-2000:]}


def create_backup_manifest(root: Path, created_at: str) -> dict:
    files = []
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        files.append({"path": path.relative_to(root).as_posix(), "size": path.stat().st_size, "sha256": digest})
    manifest = {"created_at": created_at, "files": files}
    (root / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return manifest


def backup_postgres(database_url: str, output: Path) -> dict:
    output.parent.mkdir(parents=True, exist_ok=True)
    return run_backup_command(["pg_dump", "--format=custom", "--no-owner", "--file", str(output), database_url])


def restore_postgres(database_url: str, dump_file: Path) -> dict:
    return run_backup_command(["pg_restore", "--clean", "--if-exists", "--no-owner", "--dbname", database_url, str(dump_file)])


def mirror_minio(source: str, destination: str) -> dict:
    return run_backup_command(["mc", "mirror", "--overwrite", source, destination])
```

The module CLI must dispatch these subcommands without embedding credentials:

```python
def cli() -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    backup = subparsers.add_parser("backup-postgres")
    backup.add_argument("--database-url", required=True)
    backup.add_argument("--output", type=Path, required=True)
    restore = subparsers.add_parser("restore-postgres")
    restore.add_argument("--database-url", required=True)
    restore.add_argument("--dump", type=Path, required=True)
    manifest = subparsers.add_parser("manifest")
    manifest.add_argument("--root", type=Path, required=True)
    manifest.add_argument("--created-at", required=True)
    args = parser.parse_args()
    if args.command == "backup-postgres":
        result = backup_postgres(args.database_url, args.output)
    elif args.command == "restore-postgres":
        result = restore_postgres(args.database_url, args.dump)
    else:
        result = create_backup_manifest(args.root, args.created_at)
    print(json.dumps(result, ensure_ascii=True, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(cli())
```

- [ ] **Step 4 (2-5 min): Add exact CLI commands and restore assertions to the plan implementation.**

The implementation CLI must run these commands with credentials supplied only through environment variables:

```text
python -m tools.backup_restore backup-postgres --database-url "$DATABASE_URL" --output temp_test/week11-12/backup/postgres.dump
mc mirror --overwrite local/ml-platform temp_test/week11-12/backup/minio
python -m tools.backup_restore manifest --root temp_test/week11-12/backup --created-at 2026-07-20T12:00:00Z
python -m tools.backup_restore restore-postgres --database-url "$RESTORE_DATABASE_URL" --dump temp_test/week11-12/backup/postgres.dump
mc mirror --overwrite temp_test/week11-12/backup/minio local-restored/ml-platform
```

Expected: PostgreSQL row counts and foreign-key checks match the source; every restored object SHA-256 matches the manifest; elapsed restore time is recorded and is <= 1800 seconds.

- [ ] **Step 5 (2-5 min): Run backup unit tests and a dry-run command.**

Run: `python -m unittest tests.test_week11_12_tools.BackupRestoreTests -v`

Expected: tests pass; dry-run refuses embedded credentials and writes no production database or bucket.

### Task 4: Add N-1 Upgrade and Migration Repeatability Fixture

**Files:**
- Create: `ml-platform/backend/tools/upgrade_fixture.py`
- Modify: `ml-platform/backend/tests/test_week11_12_tools.py`

- [ ] **Step 1 (2-5 min): Write failing upgrade-contract tests.**

```python
from tools.upgrade_fixture import validate_upgrade_result


class UpgradeFixtureTests(unittest.TestCase):
    def test_upgrade_result_requires_head_repeatability_and_no_data_loss(self):
        result = {
            "from_revision": "20260718_08",
            "to_revision": "20260720_10_security_notifications",
            "first_upgrade": "ok",
            "second_upgrade": "ok",
            "alembic_check": "ok",
            "row_counts_equal": True,
            "business_data_loss": False,
        }
        self.assertEqual(validate_upgrade_result(result)["status"], "passed")

    def test_wrong_target_revision_fails_closed(self):
        with self.assertRaises(ValueError):
            validate_upgrade_result({"from_revision": "20260718_08", "to_revision": "other"})
```

- [ ] **Step 2 (2-5 min): Run the tests and verify the fixture module is absent.**

Run: `python -m unittest tests.test_week11_12_tools.UpgradeFixtureTests -v`

Expected: `ImportError` for `validate_upgrade_result`.

- [ ] **Step 3 (2-5 min): Implement isolated database creation and upgrade checks.**

```python
import subprocess
from pathlib import Path

EXPECTED_N_MINUS_ONE = "20260718_08"
EXPECTED_HEAD = "20260720_10_security_notifications"


def validate_upgrade_result(result: dict) -> dict:
    if result.get("from_revision") != EXPECTED_N_MINUS_ONE or result.get("to_revision") != EXPECTED_HEAD:
        raise ValueError("unexpected migration range")
    checks = ["first_upgrade", "second_upgrade", "alembic_check"]
    passed = all(result.get(name) == "ok" for name in checks) and result.get("row_counts_equal") and not result.get("business_data_loss")
    return {"status": "passed" if passed else "failed", "checks": result}


def run_alembic(database_url: str, *arguments: str) -> subprocess.CompletedProcess:
    environment = os.environ.copy()
    environment["DATABASE_URL"] = database_url
    return subprocess.run(["alembic", *arguments], env=environment, capture_output=True, text=True, check=False)


def create_upgrade_record(output: Path, database_url: str) -> Path:
    output.parent.mkdir(parents=True, exist_ok=True)
    record = {"database_url": "[redacted]", "from_revision": EXPECTED_N_MINUS_ONE, "to_revision": EXPECTED_HEAD}
    output.write_text(__import__("json").dumps(record, indent=2) + "\n", encoding="utf-8")
    return output
```

- [ ] **Step 4 (2-5 min): Define the N-1 execution sequence.**

Run in an isolated PostgreSQL database created from the current production fixture:

```text
alembic upgrade 20260718_08
python -m tools.upgrade_fixture snapshot --output temp_test/week11-12/upgrade/pre.json
alembic upgrade 20260720_10_security_notifications
alembic upgrade 20260720_10_security_notifications
alembic current
alembic check
python -m tools.upgrade_fixture verify --before temp_test/week11-12/upgrade/pre.json --output temp_test/week11-12/upgrade/result.json
```

Expected: both upgrades are idempotent, `alembic current` reports `20260720_10_security_notifications`, `alembic check` reports no new operations, business row counts/foreign keys are unchanged, and the result has `status=passed`.

- [ ] **Step 5 (2-5 min): Run the focused tests.**

Run: `python -m unittest tests.test_week11_12_tools.UpgradeFixtureTests -v`

Expected: all upgrade validation tests pass without contacting the default development SQLite database.

### Task 5: Add Security Scan Wrapper and Secret-Leak Regression Tests

**Files:**
- Create: `ml-platform/backend/tools/security_scans.py`
- Create: `ml-platform/backend/tests/test_week12_security_gates.py`

- [ ] **Step 1 (2-5 min): Write failing scan-command and redaction tests.**

```python
import json
import unittest
from unittest.mock import patch

from tools.security_scans import run_scan, redact_scan_output


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
        value = redact_scan_output("postgresql://user:pass@db/app token=abc")
        self.assertNotIn("user:pass@", value)
        self.assertNotIn("abc", value)
```

- [ ] **Step 2 (2-5 min): Run the tests and verify the scanner module is absent.**

Run: `python -m unittest tests.test_week12_security_gates -v`

Expected: `ImportError` for `run_scan`.

- [ ] **Step 3 (2-5 min): Implement explicit scan commands and JSON results.**

```python
from pathlib import Path
import json
import re
import subprocess

SECRET_PATTERNS = (
    re.compile(r"(?i)(password|secret|token|authorization)=([^\s]+)"),
    re.compile(r"(?i)(postgresql|redis)://[^\s]+@"),
)


def redact_scan_output(value: str) -> str:
    redacted = value
    for pattern in SECRET_PATTERNS:
        redacted = pattern.sub(lambda match: f"{match.group(1)}=[redacted]" if "=" in match.group(0) else "[redacted-url]", redacted)
    return redacted


def run_scan(command: list[str]) -> dict:
    completed = subprocess.run(command, capture_output=True, text=True, check=False)
    return {
        "command": command,
        "status": "passed" if completed.returncode == 0 else "failed",
        "returncode": completed.returncode,
        "stdout": redact_scan_output(completed.stdout[-10000:]),
        "stderr": redact_scan_output(completed.stderr[-10000:]),
    }


def run_all(output: str) -> dict:
    gates = {
        "python_dependencies": run_scan(["python", "-m", "pip_audit", "-r", "requirements.txt"]),
        "source_bandit": run_scan(["bandit", "-r", "app", "-q"]),
        "frontend_dependencies": run_scan(["npm", "audit", "--audit-level=high", "--registry=https://registry.npmjs.org"]),
        "filesystem_trivy": run_scan(["trivy", "fs", "--exit-code", "1", "."]),
        "secret_gitleaks": run_scan(["gitleaks", "detect", "--no-banner", "--redact"]),
    }
    result = {"status": "passed" if all(item["status"] == "passed" for item in gates.values()) else "failed", "gates": gates}
    Path(output).write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return result
```

- [ ] **Step 4 (2-5 min): Run mocked security tests and verify no secret is emitted.**

Run: `python -m unittest tests.test_week12_security_gates -v`

Expected: all tests pass; failed scanner output contains `[redacted]` and never the test password/token.

- [ ] **Step 5 (2-5 min): Pin the scan tool versions in CI only.**

The primary integrator adds this exact setup before invoking `run_all`:

```yaml
- name: Install security scanners
  run: |
    python -m pip install "pip-audit==2.*" "bandit==1.*"
    npm install --global audit-ci@7
    curl -sfL https://raw.githubusercontent.com/aquasecurity/trivy/main/contrib/install.sh | sh -s -- -b "$RUNNER_TEMP/bin" v0.60.0
    curl -sfL https://raw.githubusercontent.com/gitleaks/gitleaks/master/install.sh | sh -s -- -b "$RUNNER_TEMP/bin" v8.24.2
```

Expected: the job fails when any required scanner is missing or returns non-zero; exceptions require a reviewed, redacted record in the evidence manifest.

### Task 6: Add the Controlled Notification Receiver Fixture

**Files:**
- Create: `ml-platform/backend/tools/notification_receiver.py`
- Modify: `ml-platform/backend/tests/test_week11_12_tools.py`

- [ ] **Step 1 (2-5 min): Write the receiver contract test.**

```python
from tools.notification_receiver import NotificationReceiver


class NotificationReceiverTests(unittest.TestCase):
    def test_receiver_records_redacted_json_and_can_assert_event_type(self):
        receiver = NotificationReceiver()
        with receiver.running() as url:
            request = __import__("urllib.request").request.Request(
                url,
                data=b'{"event_type":"rollout.completed"}',
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            response = __import__("urllib.request").request.urlopen(request, timeout=3)
            self.assertEqual(response.status, 202)
        self.assertEqual(receiver.events[0]["payload"]["event_type"], "rollout.completed")
```

- [ ] **Step 2 (2-5 min): Run the receiver test and verify the module is absent.**

Run: `python -m unittest tests.test_week11_12_tools.NotificationReceiverTests -v`

Expected: `ImportError` for `NotificationReceiver`.

- [ ] **Step 3 (2-5 min): Implement a loopback receiver with bounded, redacted event storage.**

```python
import json
import threading
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class NotificationReceiver:
    def __init__(self):
        self.events: list[dict] = []

    @staticmethod
    def _safe(value):
        if isinstance(value, dict):
            return {
                key: "[redacted]" if any(marker in key.lower() for marker in ("secret", "token", "password", "authorization", "records", "predictions", "storage_uri", "traceback")) else NotificationReceiver._safe(item)
                for key, item in value.items()
            }
        if isinstance(value, list):
            return [NotificationReceiver._safe(item) for item in value[:100]]
        return value

    @contextmanager
    def running(self):
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                length = min(int(self.headers.get("Content-Length", "0")), 65536)
                payload = self.rfile.read(length)
                try:
                    parsed = json.loads(payload.decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError):
                    parsed = {"invalid": True}
                owner.events.append({"path": self.path, "payload": owner._safe(parsed)})
                self.send_response(202)
                self.end_headers()
            def log_message(self, *_args):
                return

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            yield f"http://127.0.0.1:{server.server_port}/events"
        finally:
            server.shutdown()
            thread.join(timeout=3)
            server.server_close()
```

- [ ] **Step 4 (2-5 min): Run receiver and redaction tests.**

Run: `python -m unittest tests.test_week11_12_tools.NotificationReceiverTests -v`

Expected: receiver starts on loopback only, returns `202` for POST, and never writes credentials, inference records, predictions, or raw exception text.

The primary integrator also adds a controlled SMTP service only in the acceptance composition:

```yaml
  mailpit:
    image: axllent/mailpit:v1.21
    expose: ["1025", "8025"]
    healthcheck:
      test: ["CMD", "/mailpit", "readyz"]
      interval: 5s
      timeout: 5s
      retries: 20
```

Week 10 email delivery points at `mailpit:1025`; the browser/API acceptance queries `http://mailpit:8025/api/v1/messages` and asserts the allowlisted subject/body without exposing SMTP credentials.

### Task 7: Add Frozen Week 9/10 Contract Tests

**Files:**
- Create: `ml-platform/backend/tests/test_week11_contracts.py`

This task cannot be completed until Week 9 rollout/API-key/inference schemas and Week 10 notification/authorization schemas are frozen. The test file must use the actual frozen routes, not private service calls.

- [ ] **Step 1 (2-5 min): Add RED tests for rollout, production inference, rate limit, and notification contracts.**

```python
import unittest
from fastapi.testclient import TestClient

from app.main import app


class FrozenWeek9Week10ContractTests(unittest.TestCase):
    def test_rollout_response_exposes_revision_and_actual_model(self):
        response = TestClient(app).get("/api/inference-deployments/00000000-0000-0000-0000-000000000001/rollouts")
        self.assertIn(response.status_code, {404, 401})

    def test_production_inference_rejects_missing_or_expired_api_key(self):
        response = TestClient(app).post(
            "/api/v1/inference/00000000-0000-0000-0000-000000000001/predict",
            json={"records": [{"current": 0.0}]},
        )
        self.assertIn(response.status_code, {401, 403})

    def test_notification_endpoint_test_never_returns_secret(self):
        response = TestClient(app).post(
            "/api/projects/00000000-0000-0000-0000-000000000001/notification-endpoints/00000000-0000-0000-0000-000000000002/test"
        )
        self.assertNotIn("secret", response.text.lower())
```

- [ ] **Step 2 (2-5 min): Run the contract tests before freeze.**

Run: `python -m unittest tests.test_week11_contracts -v`

Expected before freeze: tests remain explicitly blocked by missing Week 9/10 routes and are not registered in the Week 11 manifest.

- [ ] **Step 3 (2-5 min): Replace only route parameters and auth setup after freeze.**

Use the frozen API schemas for project/deployment IDs, API-key header names, rollout response fields, and notification endpoint IDs. Keep the assertions below mandatory:

```python
self.assertIn(response.json()["status"], {"candidate", "progressing", "paused", "completed", "rolled_back"})
self.assertRegex(response.json()["actual_model_version_id"], r"^[0-9a-f-]{36}$")
self.assertNotIn("records", response.text)
self.assertNotIn("prediction", response.text.lower())
self.assertLessEqual(int(response.headers.get("Retry-After", "1")), 60)
```

- [ ] **Step 4 (2-5 min): Run the frozen contract tests and register them once.**

Run: `python -m unittest tests.test_week11_contracts -v`

Expected after freeze: all route/schema/security assertions pass; failures show a stable domain code rather than a raw exception or credential.

### Task 8: Add Browser Acceptance for Four Roles, Outsider, Rollout, and Notifications

**Files:**
- Create: `ml-platform/frontend/e2e/week12-acceptance.spec.ts`

This task waits for Week 9/10 UI routes and receiver configuration. It extends existing `core-navigation.spec.ts`, `model-inference.spec.ts`, and `weld-quality.spec.ts`; it must not replace them.

- [ ] **Step 1 (2-5 min): Write the RED browser test against the frozen role matrix.**

```typescript
import { expect, test } from "@playwright/test";

test("owner can roll out and configure all notification channels", async ({ page }) => {
  await page.goto("/login");
  await page.getByPlaceholder("用户名").fill("admin");
  await page.getByPlaceholder("密码").fill("admin123");
  await page.locator('button[type="submit"]').click();
  await expect(page).toHaveURL(/\/$/);
  await page.goto("/models");
  await expect(page.getByRole("tab", { name: /发布|Release/ })).toBeVisible();
  await expect(page.getByRole("button", { name: /回滚|Rollback/ })).toBeVisible();
  await page.goto("/projects");
  await expect(page.getByRole("tab", { name: /通知|Notifications/ })).toBeVisible();
  await expect(page.getByText(/企业微信|WeCom/)).toBeVisible();
  await expect(page.getByText(/Webhook/)).toBeVisible();
  await expect(page.getByText(/邮件|Email/)).toBeVisible();
});

test("outsider receives hidden 404 and cannot probe project members or notifications", async ({ request }) => {
  const response = await request.get("/api/projects/00000000-0000-0000-0000-000000000001/members");
  expect(response.status()).toBe(404);
});
```

- [ ] **Step 2 (2-5 min): Run the targeted browser test and capture the missing-route failure.**

Run: `npm run test:e2e -- --project=chromium e2e/week12-acceptance.spec.ts`

Expected before Week 9/10 UI freeze: the test fails on the missing Release/Notifications tab, and no Week 12 pass is claimed.

- [ ] **Step 3 (2-5 min): Add the complete frozen flow.**

The final spec must additionally perform: API-key creation with one-time plaintext assertion; rollout `0 -> 10 -> 50 -> 100`; forced threshold failure and automatic rollback; production inference rate-limit `429` plus `Retry-After`; owner/editor/operator/viewer permission checks; in-app unread/read/archive; controlled WeCom, email, and generic Webhook receiver events; and audit verification that events contain no records, predictions, credentials, object URIs, or tracebacks.

- [ ] **Step 4 (2-5 min): Run Chromium acceptance with traces enabled.**

Run: `npm run test:e2e -- --project=chromium --trace=on`

Expected: Week 12 spec passes for owner, editor, operator, viewer, and outsider; any failed request, console error, duplicate `/api/api/` URL, or leaked secret fails the test and leaves trace evidence under `temp_test/week11-12/playwright`.

### Task 9: Integrate Week 11/12 Tests into the Backend Manifest and CI

**Files:**
- Modify: `ml-platform/backend/tests/week_manifest.py`
- Modify: `ml-platform/backend/tests/test_ci_workflow.py`
- Modify: `.github/workflows/ci.yml`

Only the primary integrator edits these shared files after Tasks 1-8 produce passing modules.

- [ ] **Step 1 (2-5 min): Write the manifest RED assertion.**

```python
from tests.week_manifest import WEEK_TEST_MODULES


def test_week11_12_modules_are_owned_once():
    week11 = {"test_week11_12_tools", "test_week11_contracts"}
    week12 = {"test_week12_security_gates"}
    all_modules = [module for modules in WEEK_TEST_MODULES.values() for module in modules]
    assert week11.issubset(set(WEEK_TEST_MODULES[11]))
    assert week12.issubset(set(WEEK_TEST_MODULES[12]))
    assert len(all_modules) == len(set(all_modules))
```

- [ ] **Step 2 (2-5 min): Register each module once and run the manifest test.**

Add exact entries:

```python
    11: ["test_week11_12_tools", "test_week11_contracts"],
    12: ["test_week12_security_gates"],
```

Run: `python -m unittest tests.test_suite_manifest tests.test_ci_workflow -v`

Expected: ownership checks pass; no Week 1-10 module is duplicated.

- [ ] **Step 3 (2-5 min): Add CI jobs with fixed evidence paths.**

The primary integrator adds these job contracts to `.github/workflows/ci.yml`:

```yaml
  week11-12-verification:
    name: Week 11-12 verification (Ubuntu)
    runs-on: ubuntu-22.04
    needs: [quality, browser-acceptance, production-integration, experiment-integration]
    timeout-minutes: 90
    steps:
      - uses: actions/checkout@v5
      - uses: actions/setup-python@v6
        with:
          python-version: "3.11"
      - name: Run verification tools
        working-directory: ml-platform/backend
        env:
          ML_PLATFORM_EVIDENCE_DIR: ${{ github.workspace }}/temp_test/week11-12
        run: |
          python -m unittest tests.test_week11_12_tools tests.test_week12_security_gates -v
          python -m tools.acceptance_environment --output "$ML_PLATFORM_EVIDENCE_DIR/environment.json"
      - name: Upload verification evidence
        if: always()
        uses: actions/upload-artifact@v4
        with:
          name: week11-12-verification-evidence
          path: temp_test/week11-12
          if-no-files-found: warn
```

- [ ] **Step 4 (2-5 min): Run CI contract tests and local YAML parsing.**

Run: `python -m unittest tests.test_ci_workflow -v` and `git diff --check`.

Expected: CI has no unsupported service keys, all required upstream jobs are dependencies, evidence upload runs on failure, and no secrets are printed.

### Task 10: Execute Three-Run Week 11 Performance Baseline

**Files:**
- Create: `docs/week11-performance-baseline.md`
- Generate: `temp_test/week11-12/performance/*.json` (ignored evidence, never hand-edited)

- [ ] **Step 1 (2-5 min): Capture the fixed environment before measuring.**

Run on the acceptance host:

```text
python -m tools.acceptance_environment --output temp_test/week11-12/environment.json
docker compose ps
docker image inspect ml-platform-backend --format '{{json .RepoDigests}}'
alembic current
```

Expected: environment manifest records Linux kernel, 4 vCPU, 8 GiB RAM, Git commit, image digest, Compose service versions, and migration head without credentials.

- [ ] **Step 2 (2-5 min): Warm and measure core reads, enqueue, and inference.**

Run each command three times, changing only `--iteration` and output path:

```text
python -m tools.week11_performance run --url http://127.0.0.1:8000/api/projects --concurrency 20 --requests-per-worker 100 --warmup 30 --scenario core-read --iteration 1 --bearer-env ACCEPTANCE_JWT --output temp_test/week11-12/performance/core-read-1.json
python -m tools.week11_performance run --url "http://127.0.0.1:8000/api/v1/inference/$ACCEPTANCE_DEPLOYMENT_ID/predict" --method POST --body-file temp_test/week11-12/requests/inference.json --api-key-env ACCEPTANCE_API_KEY --concurrency 20 --requests-per-worker 100 --warmup 30 --scenario warm-inference --iteration 1 --output temp_test/week11-12/performance/warm-inference-1.json
python -m tools.week11_performance run --url http://127.0.0.1:8000/api/training/jobs --method POST --body-file temp_test/week11-12/requests/enqueue.json --bearer-env ACCEPTANCE_JWT --concurrency 20 --requests-per-worker 100 --warmup 30 --scenario enqueue --iteration 1 --output temp_test/week11-12/performance/enqueue-1.json
```

Expected: each JSON contains request count, status counts, p50/p95/p99, error rate, duration, commit SHA, and no request/response payload.

- [ ] **Step 3 (2-5 min): Run cold-load and welding workflow measurements separately.**

Run:

```text
python -m tools.week11_performance run --url "$COLD_LOAD_URL" --method POST --bearer-env ACCEPTANCE_JWT --concurrency 1 --requests-per-worker 1 --scenario cold-model-load --iteration 1 --output temp_test/week11-12/performance/cold-load-1.json
python -m tools.week11_performance run --url "$WELDING_RUN_URL" --method POST --body-file temp_test/week11-12/requests/welding.json --bearer-env ACCEPTANCE_JWT --concurrency 1 --requests-per-worker 10 --scenario welding-e2e --iteration 1 --output temp_test/week11-12/performance/welding-e2e-1.json
```

Expected: cold load is reported separately from warm inference; welding records 10/10 completed runs and duration <= 90 s for every successful iteration.

- [ ] **Step 4 (2-5 min): Evaluate candidate gates without changing load.**

Run: `python -m tools.week11_performance summarize --input-dir temp_test/week11-12/performance --output temp_test/week11-12/performance/summary.json`

Expected: summary reports all three iterations, min/median/max, p95/p99, error rate, and `candidate_status`; a failed gate remains failed and includes raw result paths.

- [ ] **Step 5 (2-5 min): Write the reviewed baseline report.**

`docs/week11-performance-baseline.md` must include the exact host manifest, command lines, raw JSON paths, threshold table, bottleneck evidence, and a signed decision of `accepted`, `accepted-with-risk`, or `rejected`. Lowering concurrency or deleting failed samples is prohibited.

### Task 11: Execute Backup/Restore and RTO/RPO Acceptance

**Files:**
- Modify: `docs/week12-acceptance.md`
- Generate: `temp_test/week11-12/backup/*`

- [ ] **Step 1 (2-5 min): Snapshot source PostgreSQL and MinIO.**

Run:

```text
python -m tools.backup_restore backup-postgres --database-url "$DATABASE_URL" --output temp_test/week11-12/backup/postgres.dump
mc alias set source "$MINIO_ENDPOINT" "$MINIO_ACCESS_KEY" "$MINIO_SECRET_KEY"
mc mirror --overwrite source/$MINIO_BUCKET temp_test/week11-12/backup/minio
python -m tools.backup_restore manifest --root temp_test/week11-12/backup --created-at 2026-07-20T12:00:00Z
```

Expected: dump, object mirror, and manifest exist; database URLs and credentials are absent from command output and manifest.

- [ ] **Step 2 (2-5 min): Restore into an isolated PostgreSQL/MinIO target.**

Run:

```text
python -m tools.backup_restore restore-postgres --database-url "$RESTORE_DATABASE_URL" --dump temp_test/week11-12/backup/postgres.dump
mc alias set restored "$RESTORE_MINIO_ENDPOINT" "$RESTORE_MINIO_ACCESS_KEY" "$RESTORE_MINIO_SECRET_KEY"
mc mirror --overwrite temp_test/week11-12/backup/minio restored/$RESTORE_MINIO_BUCKET
```

Expected: restore completes in <= 1800 seconds, all Alembic tables are at the frozen head, and no source production service is modified.

- [ ] **Step 3 (2-5 min): Verify counts, foreign keys, and object hashes.**

Run: `python -m tools.backup_restore verify --source-database "$DATABASE_URL" --restored-database "$RESTORE_DATABASE_URL" --manifest temp_test/week11-12/backup/manifest.json --restored-bucket restored/$RESTORE_MINIO_BUCKET --output temp_test/week11-12/backup/restore-result.json`

Expected: every business table count matches, all foreign-key checks pass, every object SHA-256 matches, RTO/RPO values are recorded, and `status=passed`.

### Task 12: Execute N-1 to Head Upgrade Acceptance

**Files:**
- Modify: `docs/week12-acceptance.md`
- Generate: `temp_test/week11-12/upgrade/*`

- [ ] **Step 1 (2-5 min): Build the N-1 database from the current production schema.**

Run: `python -m tools.upgrade_fixture create --revision 20260718_08 --output temp_test/week11-12/upgrade/n-minus-one.json`

Expected: isolated PostgreSQL has revision `20260718_08`, representative user/project/workflow/model rows, and no notification tables.

- [ ] **Step 2 (2-5 min): Upgrade twice to the frozen Week 10 head.**

Run: `python -m tools.upgrade_fixture upgrade --database-url "$UPGRADE_DATABASE_URL" --target 20260720_10_security_notifications --output temp_test/week11-12/upgrade/result.json`

Expected: first and second upgrade succeed, `alembic current` equals `20260720_10_security_notifications`, `alembic check` is clean, and data rows remain intact.

- [ ] **Step 3 (2-5 min): Run compatibility smoke tests on the upgraded stack.**

Run: `python -m unittest tests.test_database_production tests.test_production_stack -v`

Expected: migration, readiness, worker, and API smoke tests pass against the upgraded isolated database; no downgrade or destructive reset touches the default development database.

### Task 13: Run Security, Dependency, Container, Secret, and Web Gates

**Files:**
- Modify: `docs/week12-acceptance.md`
- Generate: `temp_test/week11-12/security/*`

- [ ] **Step 1 (2-5 min): Run source and dependency scans.**

Run from their declared directories:

```text
python -m pip_audit -r ml-platform/backend/requirements.txt --format json --output temp_test/week11-12/security/pip-audit.json
bandit -r ml-platform/backend/app -q -f json -o temp_test/week11-12/security/bandit.json
npm audit --prefix ml-platform/frontend --audit-level=high --registry=https://registry.npmjs.org --json > temp_test/week11-12/security/npm-audit.json
```

Expected: each command exits 0; JSON reports contain no credentials; npm audit uses the official advisory endpoint, not the package mirror.

- [ ] **Step 2 (2-5 min): Run container/filesystem and secret scans.**

Run:

```text
trivy fs --exit-code 1 --severity HIGH,CRITICAL --format json --output temp_test/week11-12/security/trivy-fs.json .
trivy image --exit-code 1 --severity HIGH,CRITICAL --format json --output temp_test/week11-12/security/trivy-image.json ml-platform-backend:$IMAGE_TAG
gitleaks detect --no-banner --redact --report-format json --report-path temp_test/week11-12/security/gitleaks.json
```

Expected: no unreviewed HIGH/CRITICAL vulnerability or secret; an exception is a separate redacted record with owner, expiry, CVE/rule, and mitigation.

- [ ] **Step 3 (2-5 min): Run web-security checks against the frozen stack.**

Run: `python -m tools.security_scans web --base-url http://127.0.0.1:8000 --output temp_test/week11-12/security/web.json`

Expected: hidden 404 for outsider resource probes, 403 for visible insufficient permissions, SSRF loopback/private/link-local/metadata destinations rejected, redirect escapes rejected, request-size and timeout limits enforced, and no raw provider response in API output.

- [ ] **Step 4 (2-5 min): Review scan output and append the gate result.**

Run: `python -m tools.security_scans summarize --input-dir temp_test/week11-12/security --output temp_test/week11-12/security/summary.json`

Expected: summary status is `passed` only when every required scanner and web check passed; all failures remain visible and linked to raw evidence.

### Task 14: Build Evidence Manifest and Final Acceptance Report

**Files:**
- Create: `ml-platform/backend/tools/evidence_manifest.py`
- Create: `docs/evidence/week11-12-manifest.json`
- Create: `docs/week12-acceptance.md`
- Modify: `DEVELOPMENT_PLAN.md`, `PLATFORM_STATUS.md` (primary integrator only)

- [ ] **Step 1 (2-5 min): Write the manifest test before generating the report.**

```python
import hashlib
import json
from pathlib import Path


def evidence_entry(path: Path, root: Path) -> dict:
    return {
        "path": path.relative_to(root).as_posix(),
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "size": path.stat().st_size,
    }


def test_manifest_binds_all_required_evidence(tmp_path):
    evidence = [tmp_path / "performance" / "summary.json", tmp_path / "backup" / "restore-result.json", tmp_path / "upgrade" / "result.json", tmp_path / "security" / "summary.json"]
    for path in evidence:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{}", encoding="utf-8")
    manifest = {"commit": "abc", "image_digest": "sha256:test", "migration_head": "20260720_10_security_notifications", "files": [evidence_entry(path, tmp_path) for path in evidence]}
    assert len(manifest["files"]) == 4
    assert all(len(item["sha256"]) == 64 for item in manifest["files"])
```

- [ ] **Step 2 (2-5 min): Generate the machine-readable manifest.**

Implement the deterministic generator:

```python
import argparse
import hashlib
import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path


def generate(evidence_dir: Path, output: Path) -> dict:
    required = (
        evidence_dir / "performance" / "summary.json",
        evidence_dir / "backup" / "restore-result.json",
        evidence_dir / "upgrade" / "result.json",
        evidence_dir / "security" / "summary.json",
        evidence_dir / "playwright" / "result.json",
    )
    missing = [path.as_posix() for path in required if not path.is_file()]
    if missing:
        raise FileNotFoundError(f"missing required evidence: {missing}")
    statuses = [json.loads(path.read_text(encoding="utf-8")).get("status") for path in required]
    if any(status != "passed" for status in statuses):
        raise RuntimeError(f"required evidence did not pass: {statuses}")
    files = []
    for path in sorted(item for item in evidence_dir.rglob("*") if item.is_file()):
        files.append({
            "path": path.relative_to(evidence_dir).as_posix(),
            "size": path.stat().st_size,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        })
    commit = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()
    manifest = {
        "commit": commit,
        "remote_ci_run_url": os.environ["REMOTE_CI_RUN_URL"],
        "image_digest": os.environ["ACCEPTANCE_IMAGE_DIGEST"],
        "migration_head": "20260720_10_security_notifications",
        "environment": "environment.json",
        "thresholds": "performance/summary.json",
        "files": files,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": "passed",
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    generate(args.evidence_dir, args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

Run: `python -m tools.evidence_manifest --evidence-dir temp_test/week11-12 --output docs/evidence/week11-12-manifest.json`

Expected manifest keys: `commit`, `remote_ci_run_url`, `image_digest`, `migration_head`, `environment`, `thresholds`, `files`, `generated_at`, and `status`. Every file entry has a relative path, byte size, and SHA-256.

- [ ] **Step 3 (2-5 min): Write the final report from evidence only.**

`docs/week12-acceptance.md` must include: scope and frozen revisions; three-run performance table; cold/warm split; rollout and rollback result; backup restore RTO/RPO, row/FK/object hash comparison; N-1 migration result; all scan commands and outputs; four-role/outsider browser result; remote CI URL; image digest; migration head; residual risks and explicit accepted/rejected gates. It must not contain passwords, tokens, private keys, customer data, request records, predictions, storage URIs, or raw tracebacks.

- [ ] **Step 4 (2-5 min): Synchronize project status only after all gates pass.**

Update `DEVELOPMENT_PLAN.md` and `PLATFORM_STATUS.md` with the evidence manifest path, Git commit, remote Actions run URL, migration head, and any residual risk. Keep Weeks 11 and 12 `进行中` when a required local or remote gate is missing; use `受阻` only for a verified external dependency such as unavailable Docker/CI network.

- [ ] **Step 5 (2-5 min): Run final verification and inspect the worktree.**

Run:

```text
python -m unittest tests.test_week11_12_tools tests.test_week11_contracts tests.test_week12_security_gates -v
python run_suite.py --week 11
python run_suite.py --week 12
npm test
npm run build
npm run test:e2e -- --project=chromium
git diff --check
git status --short
```

Expected: every registered module passes, frontend tests/build/E2E pass, `git diff --check` is clean, generated evidence is either intentionally ignored under `temp_test` or listed in the manifest, and no unrelated user change is reverted.

## Self-Review

1. **Spec coverage:** Performance harness and three-run gates are Tasks 1, 2, and 10; backup/restore and RTO/RPO are Tasks 3 and 11; N-1 and repeatable migration are Tasks 4 and 12; dependency/source/container/secret/web scans are Tasks 5 and 13; rollout, rollback, API-key, rate-limit, role, audit, and all four notification channels are Tasks 7, 8, and 13; evidence binding and final report are Task 14.
2. **Dependency coverage:** Tasks 1-6 are independent and may start now. Tasks 7-8 wait for the Week 9 API freeze and Week 10 migration `20260720_10_security_notifications`. Tasks 10-14 require the frozen stack and do not lower load, remove failed samples, or treat local skips as passes.
3. **File ownership:** New tools/tests are isolated. `.github/workflows/ci.yml`, `docker-compose.yml`, `week_manifest.py`, `DEVELOPMENT_PLAN.md`, and `PLATFORM_STATUS.md` are explicitly primary-integrator files; no parallel task owns them.
4. **Placeholder scan:** The plan contains no forbidden placeholder marker or undefined implementation step. Every implementation step provides code or an exact command and expected result.
5. **Type/contract consistency:** `temp_test/week11-12` is the only generated evidence root; `20260718_08` is the N-1 revision; `20260720_10_security_notifications` is the frozen target; performance outputs, scan outputs, backup results, upgrade results, browser traces, and the final manifest use those exact paths throughout.
