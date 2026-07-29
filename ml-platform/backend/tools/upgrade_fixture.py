"""Isolated N-1 upgrade fixtures and repeatability verification."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
from typing import Mapping

from tools.backup_restore import (
    collect_database_snapshot,
    require_confirmed_isolated_postgres_target,
)


EXPECTED_N_MINUS_ONE = "20260718_08"
EXPECTED_HEAD = "20260720_10_security_notifications"
UPGRADE_ACCEPTANCE_DATABASE_URL_ENV = "UPGRADE_ACCEPTANCE_DATABASE_URL"
UPGRADE_ACCEPTANCE_ISOLATED_ENV = "UPGRADE_ACCEPTANCE_ISOLATED"
_REQUIRED_REPRESENTATIVE_TABLES = (
    "users",
    "projects",
    "workflows",
    "model_library",
)


def _isolated_upgrade_database_url(database_url: str) -> str:
    return require_confirmed_isolated_postgres_target(
        database_url,
        UPGRADE_ACCEPTANCE_DATABASE_URL_ENV,
        UPGRADE_ACCEPTANCE_ISOLATED_ENV,
    )


def _write_result(output: Path, result: Mapping[str, object]) -> Path:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(result, ensure_ascii=True, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return output


def validate_upgrade_result(result: Mapping[str, object]) -> dict[str, object]:
    """Require the approved migration range, repeatability, and retained data."""
    if (
        result.get("from_revision") != EXPECTED_N_MINUS_ONE
        or result.get("to_revision") != EXPECTED_HEAD
    ):
        raise ValueError("unexpected migration range")
    checks = ("first_upgrade", "second_upgrade", "alembic_check")
    passed = (
        all(result.get(name) == "ok" for name in checks)
        and result.get("pre_upgrade_snapshot_valid") is True
        and result.get("post_upgrade_snapshot_valid") is True
        and result.get("row_counts_equal") is True
        and result.get("business_data_loss") is False
        and not result.get("foreign_key_violations")
    )
    return {"status": "passed" if passed else "failed", "checks": dict(result)}


def run_alembic(database_url: str, *arguments: str) -> subprocess.CompletedProcess[str]:
    """Run Alembic only against the explicitly supplied isolated database URL."""
    database_url = _isolated_upgrade_database_url(database_url)
    environment = os.environ.copy()
    environment["DATABASE_URL"] = database_url
    return subprocess.run(
        ["alembic", *arguments],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )


def snapshot_database(database_url: str) -> dict[str, object]:
    """Capture row counts and FK health without including the database URL."""
    database_url = _isolated_upgrade_database_url(database_url)
    return {"status": "passed", **collect_database_snapshot(database_url)}


def create_upgrade_record(output: Path, database_url: str) -> Path:
    """Record the approved range while omitting the supplied database URL."""
    _isolated_upgrade_database_url(database_url)
    return _write_result(
        output,
        {
            "database_url": "[redacted]",
            "from_revision": EXPECTED_N_MINUS_ONE,
            "to_revision": EXPECTED_HEAD,
        },
    )


def create_upgrade_fixture(database_url: str, revision: str, output: Path) -> dict[str, object]:
    """Move an isolated database to the approved N-1 revision and snapshot it."""
    if revision != EXPECTED_N_MINUS_ONE:
        raise ValueError("unexpected N-1 revision")
    database_url = _isolated_upgrade_database_url(database_url)
    completed = run_alembic(database_url, "upgrade", revision)
    current = run_alembic(database_url, "current") if completed.returncode == 0 else None
    snapshot = (
        snapshot_database(database_url)
        if current is not None and _has_exact_current_revision(current, revision)
        else {}
    )
    result = {
        "status": (
            "passed"
            if completed.returncode == 0 and _valid_snapshot(snapshot)
            else "failed"
        ),
        "revision": revision,
        "snapshot": snapshot,
    }
    _write_result(output, result)
    return result


def _valid_snapshot(snapshot: Mapping[str, object]) -> bool:
    counts = snapshot.get("table_counts")
    violations = snapshot.get("foreign_key_violations")
    return (
        snapshot.get("status") == "passed"
        and isinstance(counts, dict)
        and bool(counts)
        and _has_representative_business_data(counts)
        and isinstance(violations, list)
        and not violations
    )


def _has_representative_business_data(counts: Mapping[str, object]) -> bool:
    """Reject schema-only snapshots that cannot prove N-1 data retention."""
    return all(
        isinstance(counts.get(table), int)
        and not isinstance(counts.get(table), bool)
        and counts[table] > 0
        for table in _REQUIRED_REPRESENTATIVE_TABLES
    )


def _upgrade_result(
    before: Mapping[str, object],
    after: Mapping[str, object],
    first_upgrade: str,
    second_upgrade: str,
    alembic_check: str,
) -> dict[str, object]:
    pre_upgrade_snapshot_valid = _valid_snapshot(before)
    post_upgrade_snapshot_valid = _valid_snapshot(after)
    before_counts = before.get("table_counts", {}) if pre_upgrade_snapshot_valid else {}
    after_counts = after.get("table_counts", {}) if post_upgrade_snapshot_valid else {}
    row_counts_equal = all(
        after_counts.get(table) == count
        for table, count in before_counts.items()
    )
    result = {
        "from_revision": EXPECTED_N_MINUS_ONE,
        "to_revision": EXPECTED_HEAD,
        "first_upgrade": first_upgrade,
        "second_upgrade": second_upgrade,
        "alembic_check": alembic_check,
        "pre_upgrade_snapshot_valid": pre_upgrade_snapshot_valid,
        "post_upgrade_snapshot_valid": post_upgrade_snapshot_valid,
        "row_counts_equal": row_counts_equal,
        "business_data_loss": any(
            after_counts.get(table, 0) < count
            for table, count in before_counts.items()
        ),
        "foreign_key_violations": after.get("foreign_key_violations", []),
        "before_table_counts": before_counts,
        "after_table_counts": after_counts,
    }
    result["status"] = validate_upgrade_result(result)["status"]
    return result


def _failed_start_revision_result(output: Path) -> dict[str, object]:
    result = {
        "status": "failed",
        "error_code": "UPGRADE_START_REVISION_INVALID",
        "from_revision": EXPECTED_N_MINUS_ONE,
        "to_revision": EXPECTED_HEAD,
    }
    _write_result(output, result)
    return result


def _failed_snapshot_result(output: Path) -> dict[str, object]:
    result = {
        "status": "failed",
        "error_code": "UPGRADE_SNAPSHOT_INVALID",
        "from_revision": EXPECTED_N_MINUS_ONE,
        "to_revision": EXPECTED_HEAD,
    }
    _write_result(output, result)
    return result


def _has_exact_current_revision(
    completed: subprocess.CompletedProcess[str],
    expected_revision: str,
) -> bool:
    """Accept one Alembic revision line only, never a substring or extra head."""
    if completed.returncode != 0:
        return False
    output = getattr(completed, "stdout", "")
    if not isinstance(output, str):
        return False
    lines = [line.strip() for line in output.splitlines() if line.strip()]
    return len(lines) == 1 and lines[0] in {
        expected_revision,
        f"{expected_revision} (head)",
    }


def _at_n_minus_one(database_url: str) -> bool:
    return _has_exact_current_revision(
        run_alembic(database_url, "current"),
        EXPECTED_N_MINUS_ONE,
    )


def execute_upgrade(database_url: str, target: str, output: Path) -> dict[str, object]:
    """Run head twice, check Alembic, and prove retained business data."""
    if target != EXPECTED_HEAD:
        raise ValueError("unexpected migration target")
    database_url = _isolated_upgrade_database_url(database_url)
    if not _at_n_minus_one(database_url):
        return _failed_start_revision_result(output)
    before = snapshot_database(database_url)
    if not _valid_snapshot(before):
        return _failed_snapshot_result(output)
    first = run_alembic(database_url, "upgrade", target)
    second = run_alembic(database_url, "upgrade", target)
    current = run_alembic(database_url, "current")
    check = run_alembic(database_url, "check")
    after = snapshot_database(database_url)
    result = _upgrade_result(
        before,
        after,
        "ok" if first.returncode == 0 else "failed",
        "ok" if second.returncode == 0 else "failed",
        "ok"
        if current.returncode == 0
        and _has_exact_current_revision(current, target)
        and check.returncode == 0
        else "failed",
    )
    _write_result(output, result)
    return result


def verify_upgrade(before_path: Path, database_url: str, output: Path) -> dict[str, object]:
    """Compare a pre-upgrade snapshot with an explicit isolated database URL."""
    database_url = _isolated_upgrade_database_url(database_url)
    before = json.loads(before_path.read_text(encoding="utf-8"))
    if not isinstance(before, dict):
        raise ValueError("upgrade snapshot must be an object")
    if not _valid_snapshot(before):
        return _failed_snapshot_result(output)
    if not _at_n_minus_one(database_url):
        return _failed_start_revision_result(output)
    first = run_alembic(database_url, "upgrade", EXPECTED_HEAD)
    second = run_alembic(database_url, "upgrade", EXPECTED_HEAD)
    current = run_alembic(database_url, "current")
    check = run_alembic(database_url, "check")
    after = snapshot_database(database_url)
    result = _upgrade_result(
        before,
        after,
        "ok" if first.returncode == 0 else "failed",
        "ok" if second.returncode == 0 else "failed",
        "ok"
        if current.returncode == 0
        and _has_exact_current_revision(current, EXPECTED_HEAD)
        and check.returncode == 0
        else "failed",
    )
    _write_result(output, result)
    return result


def _database_url(explicit: str | None) -> str:
    database_url = explicit or os.getenv(UPGRADE_ACCEPTANCE_DATABASE_URL_ENV)
    if not database_url:
        raise ValueError("an explicitly confirmed isolated database URL is required")
    return _isolated_upgrade_database_url(database_url)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    create = subparsers.add_parser("create")
    create.add_argument("--revision", required=True)
    create.add_argument("--database-url")
    create.add_argument("--output", type=Path, required=True)
    snapshot = subparsers.add_parser("snapshot")
    snapshot.add_argument("--database-url")
    snapshot.add_argument("--output", type=Path, required=True)
    upgrade = subparsers.add_parser("upgrade")
    upgrade.add_argument("--database-url")
    upgrade.add_argument("--target", required=True)
    upgrade.add_argument("--output", type=Path, required=True)
    verify = subparsers.add_parser("verify")
    verify.add_argument("--before", type=Path, required=True)
    verify.add_argument("--database-url")
    verify.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    database_url = _database_url(getattr(args, "database_url", None))

    try:
        if args.command == "create":
            result = create_upgrade_fixture(database_url, args.revision, args.output)
        elif args.command == "snapshot":
            result = snapshot_database(database_url)
            _write_result(args.output, result)
        elif args.command == "upgrade":
            result = execute_upgrade(database_url, args.target, args.output)
        else:
            result = verify_upgrade(args.before, database_url, args.output)
    except (OSError, ValueError, subprocess.SubprocessError):
        result = {"status": "failed", "error_code": "UPGRADE_FIXTURE_FAILED"}
        _write_result(args.output, result)
    return 0 if result.get("status") == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
