"""Generate a fail-closed, hash-bound Week 11-12 evidence manifest."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urlsplit

from tools.backup_restore import MAX_RPO_SECONDS
from tools.security_scans import REQUIRED_SCAN_GATES
from tools.upgrade_fixture import EXPECTED_N_MINUS_ONE
from tools.week11_performance import (
    SCENARIO_REQUIRED_ITERATIONS,
    validate_iteration_evidence,
)


MIGRATION_HEAD = "20260720_10_security_notifications"
REQUIRED_GATE_EVIDENCE = (
    Path("performance/summary.json"),
    Path("backup/restore-result.json"),
    Path("upgrade/result.json"),
    Path("security/summary.json"),
    Path("playwright/result.json"),
)
REQUIRED_EVIDENCE = (Path("environment.json"), *REQUIRED_GATE_EVIDENCE)
_SENSITIVE_KEY = re.compile(
    r"(?:password|secret|token|authorization|api[-_]?key|access[-_]?key)",
    re.IGNORECASE,
)
_URL_USERINFO = re.compile(r"[a-z][a-z0-9+.-]*://[^\s/@]*(?::[^\s/@]*)?@", re.IGNORECASE)
_SECRET_ASSIGNMENT = re.compile(
    r"\b(?:password|secret|token|authorization|api[-_]?key|access[-_]?key)\s*[:=]\s*(?!\[redacted\])[^\s,;]+",
    re.IGNORECASE,
)
_IMAGE_DIGEST = re.compile(r"sha256:[0-9a-f]{64}")
_NON_BUSINESS_UPGRADE_TABLES = frozenset(
    {
        "alembic_version",
        "sqlite_sequence",
        "platform_audit_events",
        "notification_endpoints",
        "notification_subscriptions",
        "notification_outbox",
        "notification_deliveries",
        "in_app_notifications",
    },
)
_PLAYWRIGHT_PROJECT = "chromium"
_MAX_RTO_SECONDS = 1800.0
_NON_SECRET_STRUCTURE_KEYS = frozenset({"secret_gitleaks"})


def _git_commit() -> str:
    completed = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        check=False,
    )
    commit = completed.stdout.strip()
    if completed.returncode != 0 or not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise RuntimeError("EVIDENCE_GIT_COMMIT_UNAVAILABLE")
    return commit


def _assert_safe_text(value: str, *, location: str) -> None:
    if _URL_USERINFO.search(value) or _SECRET_ASSIGNMENT.search(value):
        raise ValueError(f"sensitive value found in evidence: {location}")


def _assert_safe_json(value: Any, *, location: str) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            key_text = str(key)
            if (
                _SENSITIVE_KEY.search(key_text)
                and key_text not in _NON_SECRET_STRUCTURE_KEYS
                and item not in (None, "", "[redacted]", False)
            ):
                raise ValueError(f"sensitive value found in evidence: {location}")
            _assert_safe_json(item, location=location)
    elif isinstance(value, list):
        for item in value:
            _assert_safe_json(item, location=location)
    elif isinstance(value, str):
        _assert_safe_text(value, location=location)


def _load_required_json(path: Path) -> dict[str, object]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise RuntimeError(f"invalid required evidence: {path.as_posix()}") from error
    _assert_safe_json(value, location=path.as_posix())
    if not isinstance(value, dict):
        raise RuntimeError(f"invalid required evidence: {path.as_posix()}")
    return value


def _load_required_status(path: Path) -> str:
    value = _load_required_json(path)
    return str(value.get("status", ""))


def _contract_failure(path: Path, check: str) -> None:
    raise RuntimeError(
        f"required evidence contract failed: {path.as_posix()}: {check}",
    )


def _require_contract(path: Path, condition: bool, check: str) -> None:
    if not condition:
        _contract_failure(path, check)


def _is_integer(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _is_nonnegative_finite(value: object) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
        and float(value) >= 0.0
    )


def _nonempty_count_map(value: object) -> bool:
    return (
        isinstance(value, dict)
        and bool(value)
        and all(
            isinstance(name, str)
            and _is_integer(count)
            and count >= 0
            for name, count in value.items()
        )
    )


def _validate_environment(
    path: Path,
    environment: Mapping[str, object],
    *,
    commit: str,
    image_digest: str,
) -> None:
    runtime = environment.get("runtime")
    _require_contract(path, isinstance(runtime, dict), "runtime missing")
    _require_contract(
        path,
        isinstance(runtime.get("python"), str) and bool(runtime["python"].strip()),
        "runtime.python missing",
    )
    _require_contract(
        path,
        isinstance(runtime.get("platform"), str) and bool(runtime["platform"].strip()),
        "runtime.platform missing",
    )
    _require_contract(
        path,
        _is_integer(runtime.get("cpu_count")) and runtime["cpu_count"] > 0,
        "runtime.cpu_count invalid",
    )
    _require_contract(
        path,
        _is_integer(runtime.get("memory_bytes")) and runtime["memory_bytes"] > 0,
        "runtime.memory_bytes invalid",
    )

    git = environment.get("git")
    migration = environment.get("migration")
    container = environment.get("container")
    _require_contract(
        path,
        isinstance(git, dict) and git.get("commit") == commit,
        "git.commit does not match manifest commit",
    )
    _require_contract(
        path,
        isinstance(migration, dict)
        and isinstance(migration.get("current"), str)
        and MIGRATION_HEAD in migration["current"],
        "migration.current does not include frozen head",
    )
    _require_contract(
        path,
        isinstance(container, dict) and container.get("image_digest") == image_digest,
        "container.image_digest does not match manifest image",
    )


def _validate_performance(
    path: Path,
    performance: Mapping[str, object],
    *,
    evidence_dir: Path,
    commit: str,
) -> None:
    _require_contract(path, performance.get("status") == "passed", "status is not passed")
    _require_contract(
        path,
        performance.get("candidate_status") == "passed",
        "candidate_status is not passed",
    )
    _require_contract(path, performance.get("commit") == commit, "summary commit mismatch")
    provenance = performance.get("provenance")
    _require_contract(
        path,
        isinstance(provenance, dict)
        and provenance.get("status") == "passed"
        and provenance.get("commit") == commit,
        "provenance is invalid",
    )

    iterations = performance.get("iterations")
    scenarios = performance.get("scenarios")
    _require_contract(path, isinstance(iterations, list) and bool(iterations), "iterations missing")
    _require_contract(path, isinstance(scenarios, dict), "scenarios missing")
    _require_contract(
        path,
        set(scenarios) == set(SCENARIO_REQUIRED_ITERATIONS),
        "frozen scenario set incomplete",
    )

    performance_root = evidence_dir / "performance"
    seen_iterations: dict[str, set[int]] = {
        scenario: set() for scenario in SCENARIO_REQUIRED_ITERATIONS
    }
    for item in iterations:
        _require_contract(path, isinstance(item, dict), "iteration is not an object")
        raw_name = item.get("path")
        _require_contract(
            path,
            isinstance(raw_name, str)
            and raw_name.endswith(".json")
            and Path(raw_name).name == raw_name,
            "iteration raw path invalid",
        )
        raw_path = (performance_root / raw_name).resolve()
        _require_contract(
            path,
            raw_path.parent == performance_root.resolve() and raw_path.is_file(),
            "iteration raw result missing",
        )
        raw_result = _load_required_json(raw_path)
        embedded_raw_result = {
            key: value
            for key, value in item.items()
            if key not in {"path", "candidate_gates"}
        }
        _require_contract(
            path,
            raw_result == embedded_raw_result,
            "iteration does not match its raw result",
        )
        scenario = item.get("scenario")
        iteration = item.get("iteration")
        _require_contract(
            path,
            isinstance(scenario, str) and scenario in SCENARIO_REQUIRED_ITERATIONS,
            "iteration scenario invalid",
        )
        _require_contract(
            path,
            _is_integer(iteration) and iteration in SCENARIO_REQUIRED_ITERATIONS[scenario],
            "iteration number invalid",
        )
        _require_contract(path, item.get("commit") == commit, "iteration commit mismatch")
        gates = item.get("candidate_gates")
        _require_contract(
            path,
            isinstance(gates, dict)
            and bool(gates)
            and all(isinstance(gate, dict) and gate.get("passed") is True for gate in gates.values()),
            "iteration candidate gate failed",
        )
        calculated_gates = validate_iteration_evidence(raw_result)
        _require_contract(
            path,
            all(gate.get("passed") is True for gate in calculated_gates.values()),
            "iteration raw contract failed",
        )
        seen_iterations[scenario].add(iteration)

    for scenario, required_iterations in SCENARIO_REQUIRED_ITERATIONS.items():
        scenario_result = scenarios[scenario]
        _require_contract(
            path,
            isinstance(scenario_result, dict)
            and scenario_result.get("status") == "passed"
            and seen_iterations[scenario] == set(required_iterations),
            f"{scenario} scenario contract failed",
        )


def _validate_backup(path: Path, result: Mapping[str, object]) -> None:
    _require_contract(path, result.get("status") == "passed", "status is not passed")
    source_counts = result.get("source_table_counts")
    restored_counts = result.get("restored_table_counts")
    _require_contract(path, _nonempty_count_map(source_counts), "source rows missing")
    _require_contract(path, _nonempty_count_map(restored_counts), "restored rows missing")
    _require_contract(
        path,
        source_counts == restored_counts and any(count > 0 for count in source_counts.values()),
        "restored rows do not match source",
    )
    _require_contract(path, result.get("row_counts_equal") is True, "row count gate failed")
    _require_contract(
        path,
        isinstance(result.get("foreign_key_violations"), list)
        and not result["foreign_key_violations"],
        "foreign key gate failed",
    )
    object_hashes = result.get("object_hashes")
    _require_contract(
        path,
        isinstance(object_hashes, dict)
        and object_hashes.get("status") == "passed"
        and _is_integer(object_hashes.get("checked"))
        and object_hashes["checked"] > 0
        and object_hashes.get("mismatches") == [],
        "object hash gate failed",
    )
    _require_contract(
        path,
        result.get("restore_returncode") == 0
        and result.get("minio_restore_returncode") == 0,
        "restore return code failed",
    )
    _require_contract(
        path,
        _is_nonnegative_finite(result.get("rto_seconds"))
        and float(result["rto_seconds"]) <= _MAX_RTO_SECONDS
        and result.get("rto_passed") is True,
        "RTO gate failed",
    )
    _require_contract(
        path,
        _is_nonnegative_finite(result.get("rpo_seconds"))
        and float(result["rpo_seconds"]) <= MAX_RPO_SECONDS
        and result.get("rpo_passed") is True,
        "RPO gate failed",
    )


def _validate_upgrade(path: Path, result: Mapping[str, object]) -> None:
    _require_contract(path, result.get("status") == "passed", "status is not passed")
    _require_contract(
        path,
        result.get("from_revision") == EXPECTED_N_MINUS_ONE
        and result.get("to_revision") == MIGRATION_HEAD,
        "migration range invalid",
    )
    _require_contract(
        path,
        all(result.get(name) == "ok" for name in ("first_upgrade", "second_upgrade", "alembic_check")),
        "migration repeatability failed",
    )
    _require_contract(
        path,
        result.get("pre_upgrade_snapshot_valid") is True
        and result.get("post_upgrade_snapshot_valid") is True
        and result.get("row_counts_equal") is True
        and result.get("business_data_loss") is False
        and result.get("foreign_key_violations") == [],
        "retained data gate failed",
    )
    before_counts = result.get("before_table_counts")
    after_counts = result.get("after_table_counts")
    _require_contract(path, _nonempty_count_map(before_counts), "pre-upgrade rows missing")
    _require_contract(path, _nonempty_count_map(after_counts), "post-upgrade rows missing")
    _require_contract(
        path,
        all(after_counts.get(table) == count for table, count in before_counts.items())
        and any(
            table not in _NON_BUSINESS_UPGRADE_TABLES and count > 0
            for table, count in before_counts.items()
        ),
        "retained business rows missing",
    )


def _validate_security(path: Path, result: Mapping[str, object]) -> None:
    _require_contract(path, result.get("status") == "passed", "status is not passed")
    gates = result.get("gates")
    _require_contract(path, isinstance(gates, dict), "security gates missing")
    _require_contract(
        path,
        REQUIRED_SCAN_GATES.issubset(gates),
        "security gate set incomplete",
    )
    for name in REQUIRED_SCAN_GATES:
        gate = gates[name]
        _require_contract(
            path,
            isinstance(gate, dict) and gate.get("status") == "passed",
            f"{name} gate failed",
        )
        if name == "web_security":
            web_gates = gate.get("gates")
            _require_contract(
                path,
                isinstance(web_gates, dict)
                and bool(web_gates)
                and all(
                    isinstance(item, dict) and item.get("status") == "passed"
                    for item in web_gates.values()
                ),
                "web security checks missing",
            )
        else:
            _require_contract(
                path,
                gate.get("returncode") == 0
                and isinstance(gate.get("command"), list)
                and bool(gate["command"]),
                f"{name} scanner receipt missing",
            )


def _validate_playwright(path: Path, result: Mapping[str, object]) -> None:
    _require_contract(path, result.get("status") == "passed", "status is not passed")
    _require_contract(path, result.get("project") == _PLAYWRIGHT_PROJECT, "project invalid")
    tests = result.get("tests")
    _require_contract(path, isinstance(tests, dict), "test summary missing")
    total = tests.get("total")
    passed = tests.get("passed")
    failed = tests.get("failed")
    _require_contract(
        path,
        _is_integer(total)
        and total > 0
        and _is_integer(passed)
        and passed == total
        and _is_integer(failed)
        and failed == 0,
        "test summary invalid",
    )


def _evidence_entry(path: Path, root: Path) -> dict[str, object]:
    content = path.read_bytes()
    try:
        decoded = content.decode("utf-8")
    except UnicodeDecodeError:
        decoded = ""
    if decoded:
        _assert_safe_text(decoded, location=path.relative_to(root).as_posix())
        try:
            _assert_safe_json(
                json.loads(decoded),
                location=path.relative_to(root).as_posix(),
            )
        except json.JSONDecodeError:
            pass
    return {
        "path": path.relative_to(root).as_posix(),
        "size": len(content),
        "sha256": hashlib.sha256(content).hexdigest(),
    }


def _assert_safe_metadata(remote_ci_run_url: str, image_digest: str) -> None:
    _assert_safe_text(remote_ci_run_url, location="remote_ci_run_url")
    _assert_safe_text(image_digest, location="image_digest")
    parsed = urlsplit(remote_ci_run_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.username or parsed.password:
        raise ValueError("remote_ci_run_url must be a credential-free HTTP(S) URL")
    if not image_digest:
        raise ValueError("image_digest is required")
    if _IMAGE_DIGEST.fullmatch(image_digest) is None:
        raise ValueError("image_digest must be a sha256 digest")


def generate(
    evidence_dir: Path,
    output: Path,
    *,
    remote_ci_run_url: str,
    image_digest: str,
    generated_at: str | None = None,
) -> dict[str, object]:
    """Validate evidence gates then write a reproducible manifest with SHA-256s."""
    evidence_dir = evidence_dir.resolve()
    missing = [str(relative) for relative in REQUIRED_EVIDENCE if not (evidence_dir / relative).is_file()]
    if missing:
        raise FileNotFoundError(f"missing required evidence: {missing}")

    _assert_safe_metadata(remote_ci_run_url, image_digest)
    environment_path = evidence_dir / "environment.json"
    environment = _load_required_json(environment_path)
    evidence = {
        relative: _load_required_json(evidence_dir / relative)
        for relative in REQUIRED_GATE_EVIDENCE
    }
    statuses = {
        relative.as_posix(): value.get("status")
        for relative, value in evidence.items()
    }
    if any(status != "passed" for status in statuses.values()):
        raise RuntimeError(f"required evidence did not pass: {statuses}")
    commit = _git_commit()
    _validate_environment(
        environment_path,
        environment,
        commit=commit,
        image_digest=image_digest,
    )
    _validate_performance(
        Path("performance/summary.json"),
        evidence[Path("performance/summary.json")],
        evidence_dir=evidence_dir,
        commit=commit,
    )
    _validate_backup(
        Path("backup/restore-result.json"),
        evidence[Path("backup/restore-result.json")],
    )
    _validate_upgrade(
        Path("upgrade/result.json"),
        evidence[Path("upgrade/result.json")],
    )
    _validate_security(
        Path("security/summary.json"),
        evidence[Path("security/summary.json")],
    )
    _validate_playwright(
        Path("playwright/result.json"),
        evidence[Path("playwright/result.json")],
    )

    files = [
        _evidence_entry(path, evidence_dir)
        for path in sorted(item for item in evidence_dir.rglob("*") if item.is_file())
    ]
    manifest = {
        "commit": commit,
        "remote_ci_run_url": remote_ci_run_url,
        "image_digest": image_digest,
        "migration_head": MIGRATION_HEAD,
        "environment": "environment.json",
        "thresholds": "performance/summary.json",
        "files": files,
        "generated_at": generated_at or datetime.now(timezone.utc).isoformat(),
        "status": "passed",
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(manifest, ensure_ascii=True, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    generate(
        args.evidence_dir,
        args.output,
        remote_ci_run_url=os.environ["REMOTE_CI_RUN_URL"],
        image_digest=os.environ["ACCEPTANCE_IMAGE_DIGEST"],
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
