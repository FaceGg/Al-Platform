"""Safe backup/restore command wrappers and integrity verification."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import hmac
import json
import math
import os
from pathlib import Path, PurePosixPath
import stat
import subprocess
import tempfile
import time
from typing import Mapping, Sequence
from urllib.parse import urlsplit
import uuid

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError, SQLAlchemyError
from tools.redaction import redact_text


MAX_RPO_SECONDS = 24 * 60 * 60
BACKUP_ACCEPTANCE_ISOLATED_ENV = "BACKUP_ACCEPTANCE_ISOLATED"
BACKUP_ACCEPTANCE_MINIO_DESTINATION_ENV = "BACKUP_ACCEPTANCE_MINIO_DESTINATION"
RESTORE_ACCEPTANCE_DATABASE_URL_ENV = "RESTORE_ACCEPTANCE_DATABASE_URL"
RESTORE_ACCEPTANCE_ISOLATED_ENV = "RESTORE_ACCEPTANCE_ISOLATED"
RESTORE_ACCEPTANCE_MINIO_DESTINATION_ENV = "RESTORE_ACCEPTANCE_MINIO_DESTINATION"
RESTORE_SOURCE_DATABASE_URL_ENV = "RESTORE_SOURCE_DATABASE_URL"
RESTORE_SOURCE_MINIO_ENV = "RESTORE_SOURCE_MINIO"
BACKUP_RESTORE_EVIDENCE_KEY_ENV = "BACKUP_RESTORE_EVIDENCE_KEY"
_EVIDENCE_VERSION = 1
_EVIDENCE_FILENAMES = frozenset(
    {
        "manifest.json",
        "backup-operation.json",
        "postgres-backup-pending.json",
        "minio-backup-pending.json",
        "postgres-backup-operation.json",
        "minio-backup-operation.json",
        "restore-operation.json",
        "minio-restore-operation.json",
    },
)
_CREDENTIAL_OPTION_MARKERS = (
    "password",
    "secret",
    "token",
    "authorization",
    "api-key",
    "apikey",
    "access-key",
    "accesskey",
    "client-secret",
    "clientsecret",
    "credential",
)


def _redact(value: str) -> str:
    return redact_text(value)


def _safe_command(command: Sequence[str]) -> list[str]:
    safe = []
    for index, item in enumerate(command):
        value = str(item)
        if index == 0:
            safe.append(Path(value).name)
        elif "://" in value:
            safe.append("[redacted-url]")
        else:
            safe.append(_redact(value))
    return safe


def _contains_credential_url(value: str) -> bool:
    candidates = (value, value.partition("=")[2]) if "=" in value else (value,)
    for candidate in candidates:
        parsed = urlsplit(candidate)
        if parsed.scheme and (parsed.username is not None or parsed.password is not None):
            return True
    return False


def _contains_credential_option(value: str) -> bool:
    option = value.lstrip("-").partition("=")[0].casefold().replace("_", "-")
    return any(marker in option for marker in _CREDENTIAL_OPTION_MARKERS)


def run_backup_command(
    command: list[str],
    environment: Mapping[str, str] | None = None,
) -> dict[str, object]:
    """Run an external command while preserving only redacted evidence."""
    if any(_contains_credential_option(str(item)) for item in command[1:]):
        raise ValueError("credentials must be passed through the environment")
    if any(_contains_credential_url(str(item)) for item in command):
        raise ValueError("credential-bearing URLs must not be passed to subprocesses")
    try:
        completed = subprocess.run(
            [str(item) for item in command],
            capture_output=True,
            text=True,
            check=False,
            env=dict(environment) if environment is not None else None,
        )
    except OSError as error:
        return {
            "command": _safe_command(command),
            "returncode": 127,
            "stdout": "",
            "stderr": _redact(str(error))[-2000:],
        }
    stdout = _redact(getattr(completed, "stdout", "") or "")
    stderr = _redact(getattr(completed, "stderr", "") or "")
    return {
        "command": _safe_command(command),
        "returncode": int(completed.returncode),
        "stdout": stdout[-2000:],
        "stderr": stderr[-2000:],
    }


def _postgres_environment(database_url: str) -> tuple[dict[str, str], str]:
    url = make_url(database_url)
    if url.get_backend_name() != "postgresql":
        raise ValueError("backup and restore require a PostgreSQL database URL")
    if not url.database:
        raise ValueError("database URL must include a database name")
    environment = os.environ.copy()
    if url.username:
        environment["PGUSER"] = url.username
    if url.password is not None:
        environment["PGPASSWORD"] = url.password
    if url.host:
        environment["PGHOST"] = url.host
    if url.port is not None:
        environment["PGPORT"] = str(url.port)
    environment["PGDATABASE"] = url.database
    return environment, url.database


def _database_target_identity(database_url: str) -> tuple[str, str | None, int | None, str | None]:
    try:
        url = make_url(database_url)
        backend = url.get_backend_name()
        return (
            backend,
            url.host.casefold() if url.host else None,
            5432 if backend == "postgresql" and url.port is None else url.port,
            url.database,
        )
    except (ArgumentError, ValueError):
        raise ValueError("database target must be a valid URL") from None


def _same_database_target(first: str, second: str) -> bool:
    return _database_target_identity(first) == _database_target_identity(second)


def require_confirmed_isolated_postgres_target(
    database_url: str,
    acceptance_url_environment: str,
    confirmation_environment: str,
    source_database_url: str | None = None,
) -> str:
    """Return the confirmed PostgreSQL target or reject unsafe acceptance input."""
    acceptance_url = os.getenv(acceptance_url_environment)
    default_database_url = os.getenv("DATABASE_URL")
    if (
        not acceptance_url
        or os.getenv(confirmation_environment) != "1"
        or not _same_database_target(database_url, acceptance_url)
        or (
            default_database_url is not None
            and _same_database_target(acceptance_url, default_database_url)
        )
        or (
            source_database_url is not None
            and _same_database_target(acceptance_url, source_database_url)
        )
    ):
        raise ValueError("an explicitly confirmed isolated PostgreSQL database is required")
    _postgres_environment(acceptance_url)
    return acceptance_url


def _isolated_restore_database_url(
    database_url: str,
    source_database_url: str | None,
) -> str:
    """Require a separately named, manually confirmed restore target."""
    if not source_database_url:
        raise ValueError("an explicitly confirmed isolated restore database is required")
    return require_confirmed_isolated_postgres_target(
        database_url,
        RESTORE_ACCEPTANCE_DATABASE_URL_ENV,
        RESTORE_ACCEPTANCE_ISOLATED_ENV,
        source_database_url,
    )


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _evidence_key() -> bytes:
    value = os.getenv(BACKUP_RESTORE_EVIDENCE_KEY_ENV)
    if not value:
        raise ValueError("an acceptance evidence signing key is required")
    return value.encode("utf-8")


def _signed_evidence(payload: Mapping[str, object]) -> str:
    serialized = json.dumps(
        payload,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hmac.new(_evidence_key(), serialized, hashlib.sha256).hexdigest()


def _is_regular_evidence_file(path: Path) -> bool:
    try:
        metadata = path.lstat()
    except OSError:
        return False
    reparse_point = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    return (
        not path.is_symlink()
        and stat.S_ISREG(metadata.st_mode)
        and not (getattr(metadata, "st_file_attributes", 0) & reparse_point)
        and metadata.st_nlink == 1
    )


def _write_evidence_json(path: Path, value: Mapping[str, object]) -> Path:
    serialized = json.dumps(value, ensure_ascii=True, indent=2, sort_keys=True) + "\n"
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(serialized)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
    finally:
        if temporary_path.exists():
            temporary_path.unlink()
    return path


def _write_operation_receipt(
    manifest_path: Path,
    receipt_name: str,
    operation: str,
    returncode: int,
    duration_seconds: float,
    completed_at: datetime | None = None,
) -> Path:
    if duration_seconds < 0:
        raise ValueError("operation duration must not be negative")
    completed = completed_at or datetime.now(timezone.utc)
    if completed.tzinfo is None:
        raise ValueError("operation completion time must be timezone-aware")
    payload = {
        "evidence_version": _EVIDENCE_VERSION,
        "operation": operation,
        "manifest_sha256": _sha256_file(manifest_path),
        "returncode": int(returncode),
        "duration_seconds": float(duration_seconds),
        "completed_at": completed.astimezone(timezone.utc).isoformat(),
    }
    receipt = {**payload, "signature": _signed_evidence(payload)}
    receipt_path = manifest_path.parent / receipt_name
    if not _is_regular_evidence_file(manifest_path):
        raise ValueError("backup manifest must be a regular evidence file")
    return _write_evidence_json(receipt_path, receipt)


def _backup_evidence_entry(root: Path, path: Path) -> dict[str, object]:
    return {
        "path": path.relative_to(root).as_posix(),
        "size": path.stat().st_size,
        "sha256": _sha256_file(path),
    }


def _normalize_pending_files(files: object) -> list[dict[str, object]] | None:
    if not isinstance(files, list):
        return None
    normalized = []
    for item in files:
        if not isinstance(item, Mapping) or set(item) != {"path", "size", "sha256"}:
            return None
        raw_path = item.get("path")
        size = item.get("size")
        sha256 = item.get("sha256")
        if (
            not isinstance(raw_path, str)
            or not isinstance(size, int)
            or isinstance(size, bool)
            or size < 0
            or not isinstance(sha256, str)
            or len(sha256) != 64
            or any(character not in "0123456789abcdef" for character in sha256.casefold())
        ):
            return None
        path = PurePosixPath(raw_path)
        if (
            path.is_absolute()
            or not path.parts
            or any(part in {"", ".", ".."} for part in path.parts)
            or (len(path.parts) == 1 and path.name in _EVIDENCE_FILENAMES)
        ):
            return None
        normalized.append({"path": path.as_posix(), "size": size, "sha256": sha256})
    if len({item["path"] for item in normalized}) != len(normalized):
        return None
    return sorted(normalized, key=lambda item: str(item["path"]))


def _normalize_backup_run_id(value: object) -> str | None:
    if (
        not isinstance(value, str)
        or len(value) != 32
        or any(character not in "0123456789abcdef" for character in value)
    ):
        return None
    return value


def _write_pending_operation_receipt(
    receipt_path: Path,
    operation: str,
    returncode: int,
    duration_seconds: float,
    files: Sequence[Mapping[str, object]],
    completed_at: datetime | None = None,
    *,
    backup_run_id: str,
) -> Path:
    if duration_seconds < 0:
        raise ValueError("operation duration must not be negative")
    normalized_files = _normalize_pending_files(list(files))
    if normalized_files is None:
        raise ValueError("pending backup evidence files are invalid")
    normalized_run_id = _normalize_backup_run_id(backup_run_id)
    if normalized_run_id is None:
        raise ValueError("pending backup run identifier is invalid")
    completed = completed_at or datetime.now(timezone.utc)
    if completed.tzinfo is None:
        raise ValueError("operation completion time must be timezone-aware")
    payload = {
        "evidence_version": _EVIDENCE_VERSION,
        "operation": operation,
        "returncode": int(returncode),
        "duration_seconds": float(duration_seconds),
        "completed_at": completed.astimezone(timezone.utc).isoformat(),
        "files": normalized_files,
        "backup_run_id": normalized_run_id,
    }
    receipt = {**payload, "signature": _signed_evidence(payload)}
    return _write_evidence_json(receipt_path, receipt)


def _read_pending_operation_receipt(
    receipt_path: Path,
    operation: str,
) -> dict[str, object] | None:
    if not _is_regular_evidence_file(receipt_path):
        return None
    try:
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        if not isinstance(receipt, dict) or set(receipt) != {
            "evidence_version",
            "operation",
            "returncode",
            "duration_seconds",
            "completed_at",
            "files",
            "backup_run_id",
            "signature",
        }:
            return None
        payload = {name: value for name, value in receipt.items() if name != "signature"}
        returncode = payload["returncode"]
        duration = payload["duration_seconds"]
        completed_at = payload["completed_at"]
        files = _normalize_pending_files(payload["files"])
        backup_run_id = _normalize_backup_run_id(payload["backup_run_id"])
        if (
            payload["evidence_version"] != _EVIDENCE_VERSION
            or payload["operation"] != operation
            or not isinstance(returncode, int)
            or isinstance(returncode, bool)
            or not isinstance(duration, (int, float))
            or isinstance(duration, bool)
            or not math.isfinite(float(duration))
            or float(duration) < 0
            or not isinstance(completed_at, str)
            or files is None
            or backup_run_id is None
            or not isinstance(receipt["signature"], str)
            or not hmac.compare_digest(receipt["signature"], _signed_evidence(payload))
        ):
            return None
        completed = datetime.fromisoformat(completed_at.replace("Z", "+00:00"))
        if completed.tzinfo is None:
            return None
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
        return None
    return {
        "returncode": int(returncode),
        "duration_seconds": float(duration),
        "completed_at": completed.astimezone(timezone.utc),
        "files": files,
        "backup_run_id": backup_run_id,
    }


def _backup_manifest_entries(root: Path) -> list[dict[str, object]]:
    entries = []
    for path in sorted(root.rglob("*")):
        try:
            metadata = path.lstat()
        except OSError as error:
            raise ValueError("backup evidence contains an unreadable path") from error
        reparse_point = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
        if (
            path.is_symlink()
            or stat.S_ISLNK(metadata.st_mode)
            or getattr(metadata, "st_file_attributes", 0) & reparse_point
        ):
            raise ValueError("backup evidence must not contain linked paths")
        if not stat.S_ISREG(metadata.st_mode):
            continue
        if metadata.st_nlink != 1:
            raise ValueError("backup evidence must not contain linked files")
        if path.name in _EVIDENCE_FILENAMES and path.parent == root:
            continue
        entries.append(_backup_evidence_entry(root, path))
    return entries


def _validated_backup_manifest(
    root: Path,
) -> tuple[
    dict[str, object],
    list[dict[str, object]],
    list[dict[str, object]],
    list[dict[str, object]],
    str,
]:
    manifest_path = root / "manifest.json"
    if not _is_regular_evidence_file(manifest_path):
        raise ValueError("existing backup finalization is invalid")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        raise ValueError("existing backup finalization is invalid") from None
    if (
        not isinstance(manifest, dict)
        or set(manifest) != {"backup_run_id", "created_at", "files"}
        or not isinstance(manifest["created_at"], str)
    ):
        raise ValueError("existing backup finalization is invalid")
    manifest_files = _normalize_pending_files(manifest["files"])
    backup_run_id = _normalize_backup_run_id(manifest.get("backup_run_id"))
    if manifest_files is None or backup_run_id is None:
        raise ValueError("existing backup finalization is invalid")
    postgres_files = [
        item for item in manifest_files if not str(item["path"]).startswith("minio/")
    ]
    minio_files = [
        item for item in manifest_files if str(item["path"]).startswith("minio/")
    ]
    if len(postgres_files) != 1 or not minio_files:
        raise ValueError("existing backup finalization is invalid")
    return manifest, manifest_files, postgres_files, minio_files, backup_run_id


def _read_finalized_backup_state(
    root: Path,
    backup_receipts: Sequence[tuple[Path, str, str]],
) -> tuple[dict[str, object], list[dict[str, object]], list[dict[str, object]]] | None:
    manifest_path = root / "manifest.json"
    final_receipts = [root / receipt_name for _, _, receipt_name in backup_receipts]
    if not any(path.is_file() for path in final_receipts):
        return None
    if not manifest_path.is_file() or not all(path.is_file() for path in final_receipts):
        raise ValueError("existing backup finalization is incomplete")
    manifest, manifest_files, _postgres_files, _minio_files, _backup_run_id = (
        _validated_backup_manifest(root)
    )
    completed_receipts = [
        _read_operation_receipt(manifest_path, receipt_name, operation)
        for _, operation, receipt_name in backup_receipts
    ]
    if (
        any(receipt is None for receipt in completed_receipts)
        or any(
            not isinstance(receipt, dict) or receipt.get("returncode") != 0
            for receipt in completed_receipts
        )
    ):
        raise ValueError("existing backup finalization is invalid")
    return (
        manifest,
        manifest_files,
        [receipt for receipt in completed_receipts if isinstance(receipt, dict)],
    )


def _recover_interrupted_backup_finalization(
    root: Path,
    backup_receipts: Sequence[tuple[Path, str, str]],
) -> dict[str, object] | None:
    manifest_path = root / "manifest.json"
    final_paths = [root / receipt_name for _, _, receipt_name in backup_receipts]
    if not any(
        path.exists() or path.is_symlink() for path in final_paths
    ) or all(path.is_file() for path in final_paths):
        return None
    if not manifest_path.is_file():
        raise ValueError("existing backup finalization is incomplete")
    (
        manifest,
        manifest_files,
        postgres_files,
        minio_files,
        backup_run_id,
    ) = _validated_backup_manifest(root)
    if _backup_manifest_entries(root) != manifest_files:
        raise ValueError("backup evidence does not match finalized manifest")

    pending: list[dict[str, object]] = []
    expected_files = (postgres_files, minio_files)
    for (pending_path, operation, _), expected in zip(backup_receipts, expected_files):
        receipt = _read_pending_operation_receipt(pending_path, operation)
        if (
            receipt is None
            or receipt.get("returncode") != 0
            or receipt.get("files") != expected
            or receipt.get("backup_run_id") != backup_run_id
        ):
            raise ValueError("backup pending records do not match finalized evidence")
        pending.append(receipt)

    finalized_receipts: list[dict[str, object]] = []
    for index, ((_, operation, receipt_name), expected) in enumerate(
        zip(backup_receipts, expected_files)
    ):
        final_path = root / receipt_name
        finalized = _read_operation_receipt(manifest_path, receipt_name, operation)
        if finalized is None:
            if final_path.exists() or final_path.is_symlink():
                raise ValueError("existing backup finalization is invalid")
            pending_receipt = pending[index]
            duration_seconds = pending_receipt.get("duration_seconds")
            completed_at = pending_receipt.get("completed_at")
            if not isinstance(duration_seconds, float) or not isinstance(completed_at, datetime):
                raise ValueError("backup pending records must be valid and signed")
            _write_operation_receipt(
                manifest_path,
                receipt_name,
                operation,
                0,
                duration_seconds,
                completed_at,
            )
            finalized = _read_operation_receipt(manifest_path, receipt_name, operation)
        if (
            finalized is None
            or finalized.get("returncode") != 0
            or not _pending_matches_finalized_backup(
                pending[index],
                finalized,
                expected,
                backup_run_id,
            )
        ):
            raise ValueError("backup pending records do not match finalized evidence")
        finalized_receipts.append(finalized)
    return _recover_finalized_backup_state(
        root,
        backup_receipts,
        manifest,
        manifest_files,
        finalized_receipts,
    )


def _pending_matches_finalized_backup(
    pending: Mapping[str, object],
    finalized: Mapping[str, object],
    expected_files: list[dict[str, object]],
    backup_run_id: str,
) -> bool:
    pending_completed = pending.get("completed_at")
    finalized_completed = finalized.get("completed_at")
    if not isinstance(pending_completed, datetime) or not isinstance(finalized_completed, str):
        return False
    try:
        finalized_time = datetime.fromisoformat(finalized_completed.replace("Z", "+00:00"))
    except ValueError:
        return False
    return (
        finalized_time.tzinfo is not None
        and pending.get("returncode") == finalized.get("returncode") == 0
        and pending.get("duration_seconds") == finalized.get("duration_seconds")
        and pending_completed == finalized_time.astimezone(timezone.utc)
        and pending.get("files") == expected_files
        and pending.get("backup_run_id") == backup_run_id
    )


def _recover_finalized_backup_state(
    root: Path,
    backup_receipts: Sequence[tuple[Path, str, str]],
    manifest: dict[str, object],
    manifest_files: list[dict[str, object]],
    finalized_receipts: Sequence[dict[str, object]],
) -> dict[str, object]:
    if _backup_manifest_entries(root) != manifest_files:
        raise ValueError("backup evidence does not match finalized manifest")
    backup_run_id = _normalize_backup_run_id(manifest.get("backup_run_id"))
    if backup_run_id is None:
        raise ValueError("existing backup finalization is invalid")
    postgres_files = [
        item for item in manifest_files if not str(item["path"]).startswith("minio/")
    ]
    minio_files = [
        item for item in manifest_files if str(item["path"]).startswith("minio/")
    ]
    if len(postgres_files) != 1 or not minio_files:
        raise ValueError("existing backup finalization is invalid")
    expected_files = (postgres_files, minio_files)
    for (pending_path, operation, _), finalized, expected in zip(
        backup_receipts,
        finalized_receipts,
        expected_files,
    ):
        if not pending_path.exists():
            continue
        pending = _read_pending_operation_receipt(pending_path, operation)
        if pending is None or not _pending_matches_finalized_backup(
            pending,
            finalized,
            expected,
            backup_run_id,
        ):
            raise ValueError("backup pending records do not match finalized evidence")
    for pending_path, _, _ in backup_receipts:
        if pending_path.exists():
            pending_path.unlink()
    return manifest


def create_backup_manifest(
    root: Path,
    created_at: datetime | None = None,
) -> dict[str, object]:
    """Create a deterministic SHA-256 manifest for backup files under ``root``."""
    if created_at is not None:
        raise ValueError("manifest creation time is generated by this tool")
    created = datetime.now(timezone.utc)
    root = root.resolve()
    root.mkdir(parents=True, exist_ok=True)
    pending_receipts = (
        (
            root / "postgres-backup-pending.json",
            "backup-postgres",
            "postgres-backup-operation.json",
        ),
        (
            root / "minio-backup-pending.json",
            "backup-minio",
            "minio-backup-operation.json",
        ),
    )
    pending_paths = [receipt_path for receipt_path, _, _ in pending_receipts]
    recovered = _recover_interrupted_backup_finalization(root, pending_receipts)
    if recovered is not None:
        return recovered
    finalized = _read_finalized_backup_state(root, pending_receipts)
    if finalized is not None:
        return _recover_finalized_backup_state(root, pending_receipts, *finalized)
    if any(path.is_file() for path in pending_paths) and not all(
        path.is_file() for path in pending_paths
    ):
        raise ValueError("both signed backup pending records are required before manifest finalization")
    pending = (
        [
            _read_pending_operation_receipt(receipt_path, operation)
            for receipt_path, operation, _ in pending_receipts
        ]
        if all(path.is_file() for path in pending_paths)
        else None
    )
    if pending is not None and any(receipt is None for receipt in pending):
        raise ValueError("backup pending records must be valid and signed")
    files = _backup_manifest_entries(root)
    manifest = {
        "created_at": created.astimezone(timezone.utc).isoformat(),
        "files": files,
    }
    if pending is not None:
        postgres_files = pending[0]["files"] if pending[0] is not None else None
        minio_files = pending[1]["files"] if pending[1] is not None else None
        postgres_run_id = pending[0]["backup_run_id"] if pending[0] is not None else None
        minio_run_id = pending[1]["backup_run_id"] if pending[1] is not None else None
        if not isinstance(postgres_run_id, str) or postgres_run_id != minio_run_id:
            raise ValueError("pending backup records must belong to the same backup run")
        if (
            not isinstance(postgres_files, list)
            or len(postgres_files) != 1
            or not isinstance(minio_files, list)
            or not minio_files
            or any(
                not isinstance(item.get("path"), str)
                or not item["path"].startswith("minio/")
                for item in minio_files
            )
        ):
            raise ValueError("backup pending records do not describe a complete MinIO backup")
        expected_files = [*postgres_files, *minio_files]
        if (
            any(
                not isinstance(item.get("path"), str)
                or item["path"].startswith("minio/")
                for item in postgres_files
            )
            or len({str(item["path"]) for item in expected_files}) != len(expected_files)
            or sorted(expected_files, key=lambda item: str(item["path"])) != files
        ):
            raise ValueError("backup pending records do not match staged evidence")
        manifest["backup_run_id"] = postgres_run_id
    manifest_path = root / "manifest.json"
    _write_evidence_json(manifest_path, manifest)
    if pending is not None:
        for receipt, (_, operation, receipt_name) in zip(pending, pending_receipts):
            if receipt is None:
                raise ValueError("backup pending records must be valid and signed")
            returncode = receipt["returncode"]
            duration_seconds = receipt["duration_seconds"]
            completed_at = receipt["completed_at"]
            if (
                not isinstance(returncode, int)
                or not isinstance(duration_seconds, float)
                or not isinstance(completed_at, datetime)
            ):
                raise ValueError("backup pending records must be valid and signed")
            _write_operation_receipt(
                manifest_path,
                receipt_name,
                operation,
                returncode,
                duration_seconds,
                completed_at,
            )
        for path in pending_paths:
            path.unlink()
    return manifest


def backup_postgres(database_url: str, output: Path) -> dict[str, object]:
    output.parent.mkdir(parents=True, exist_ok=True)
    environment, database_name = _postgres_environment(database_url)
    started = time.perf_counter()
    result = run_backup_command(
        [
            "pg_dump",
            "--format=custom",
            "--no-owner",
            "--file",
            str(output),
            "--dbname",
            database_name,
        ],
        environment,
    )
    result["duration_seconds"] = time.perf_counter() - started
    if result["returncode"] == 0:
        completed_at = datetime.now(timezone.utc)
        if not output.is_file():
            raise ValueError("pg_dump did not produce a backup artifact")
        _write_pending_operation_receipt(
            output.parent / "postgres-backup-pending.json",
            "backup-postgres",
            0,
            float(result["duration_seconds"]),
            [_backup_evidence_entry(output.parent, output)],
            completed_at,
            backup_run_id=uuid.uuid4().hex,
        )
    return result


def restore_postgres(
    database_url: str,
    dump_file: Path,
    source_database_url: str | None = None,
) -> dict[str, object]:
    database_url = _isolated_restore_database_url(database_url, source_database_url)
    manifest_path = dump_file.parent / "manifest.json"
    if not _is_regular_evidence_file(manifest_path):
        raise ValueError("a signed backup manifest is required before PostgreSQL restore")
    _evidence_key()
    environment, database_name = _postgres_environment(database_url)
    started = time.perf_counter()
    result = run_backup_command(
        [
            "pg_restore",
            "--clean",
            "--if-exists",
            "--no-owner",
            "--dbname",
            database_name,
            str(dump_file),
        ],
        environment,
    )
    result["duration_seconds"] = time.perf_counter() - started
    _write_operation_receipt(
        manifest_path,
        "restore-operation.json",
        "restore-postgres",
        int(result["returncode"]),
        float(result["duration_seconds"]),
    )
    return result


def _run_minio_mirror(
    source: str,
    destination: str,
) -> dict[str, object]:
    started = time.perf_counter()
    result = run_backup_command(
        ["mc", "mirror", "--overwrite", source, destination],
    )
    result["duration_seconds"] = time.perf_counter() - started
    return result


def _normalized_minio_endpoint(value: str) -> str:
    parsed = urlsplit(value)
    if (
        not parsed.scheme
        or not parsed.netloc
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("MinIO alias resolution is invalid")
    try:
        host = parsed.hostname
        port = parsed.port
    except ValueError:
        raise ValueError("MinIO alias resolution is invalid") from None
    if not host:
        raise ValueError("MinIO alias resolution is invalid")
    scheme = parsed.scheme.casefold()
    normalized_host = host.casefold()
    if ":" in normalized_host and not normalized_host.startswith("["):
        normalized_host = f"[{normalized_host}]"
    if port is not None and not (
        (scheme == "http" and port == 80) or (scheme == "https" and port == 443)
    ):
        normalized_host = f"{normalized_host}:{port}"
    return f"{scheme}://{normalized_host}{parsed.path.rstrip('/')}"


def _minio_aliases() -> dict[str, str]:
    """Load the documented JSON-lines output from ``mc alias list --json``."""
    try:
        completed = subprocess.run(
            ["mc", "alias", "list", "--json"],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        raise ValueError("MinIO alias resolution is unavailable") from None
    if completed.returncode != 0 or not isinstance(completed.stdout, str):
        raise ValueError("MinIO alias resolution is unavailable")
    output = completed.stdout.strip()
    if not output:
        return {}
    try:
        decoded = json.loads(output)
        records = decoded if isinstance(decoded, list) else [decoded]
    except json.JSONDecodeError:
        try:
            records = [json.loads(line) for line in output.splitlines() if line.strip()]
        except json.JSONDecodeError:
            raise ValueError("MinIO alias resolution is invalid") from None
    aliases: dict[str, str] = {}
    for record in records:
        if not isinstance(record, dict):
            raise ValueError("MinIO alias resolution is invalid")
        alias = record.get("alias", record.get("Alias"))
        endpoint = record.get("URL", record.get("url"))
        if not isinstance(alias, str) or not alias or not isinstance(endpoint, str):
            raise ValueError("MinIO alias resolution is invalid")
        aliases[alias.casefold()] = _normalized_minio_endpoint(endpoint)
    return aliases


def _is_minio_alias_reference(value: str) -> bool:
    if value.startswith((".", "/", "\\")) or Path(value).is_absolute():
        return False
    return not urlsplit(value).scheme


def _minio_target_identity(
    value: str,
    aliases: Mapping[str, str] | None = None,
) -> tuple[str, str, str]:
    if value.startswith((".", "/", "\\")) or Path(value).is_absolute():
        return ("path", str(Path(value).resolve()), "")
    parsed = urlsplit(value)
    if parsed.scheme:
        if _contains_credential_url(value):
            raise ValueError("MinIO target must not contain credentials")
        parts = [part for part in parsed.path.split("/") if part]
        if not parts:
            raise ValueError("MinIO target must include a bucket")
        endpoint = _normalized_minio_endpoint(
            f"{parsed.scheme}://{parsed.netloc}",
        )
        return ("minio", endpoint, parts[0].casefold())
    alias, separator, remainder = value.partition("/")
    if not alias or not separator or not remainder:
        raise ValueError("MinIO target must include an alias and bucket")
    bucket = remainder.split("/", 1)[0]
    if not bucket:
        raise ValueError("MinIO target must include an alias and bucket")
    if aliases is None:
        raise ValueError("MinIO alias resolution is unavailable")
    endpoint = aliases.get(alias.casefold())
    if endpoint is None:
        raise ValueError("MinIO alias resolution is invalid")
    return ("minio", endpoint, bucket.casefold())


def _confirmed_isolated_minio_destination(
    source: str | None,
    destination: str,
    acceptance_destination_environment: str,
    confirmation_environment: str,
) -> str:
    acceptance_destination = os.getenv(acceptance_destination_environment)
    if (
        not acceptance_destination
        or os.getenv(confirmation_environment) != "1"
        or _contains_credential_url(acceptance_destination)
        or _contains_credential_url(destination)
        or (source is not None and _contains_credential_url(source))
    ):
        raise ValueError("an explicitly confirmed isolated restore destination is required")
    values = [destination]
    values.append(acceptance_destination)
    if source is not None:
        values.append(source)
    try:
        aliases = (
            _minio_aliases()
            if any(_is_minio_alias_reference(value) for value in values)
            else {}
        )
        destination_identity = _minio_target_identity(destination, aliases)
        acceptance_identity = (
            _minio_target_identity(acceptance_destination, aliases)
            if acceptance_destination
            else None
        )
        source_identity = (
            _minio_target_identity(source, aliases) if source is not None else None
        )
    except ValueError:
        raise ValueError(
            "an explicitly confirmed isolated restore destination is required",
        ) from None
    if (
        destination_identity != acceptance_identity
        or (source_identity is not None and source_identity == acceptance_identity)
    ):
        raise ValueError("an explicitly confirmed isolated restore destination is required")
    return acceptance_destination


def _local_backup_minio_directory(destination: str, receipt_path: Path) -> Path:
    root = receipt_path.parent.resolve()
    minio_root = root / "minio"
    if Path(destination).resolve() != minio_root:
        raise ValueError("MinIO backup destination must be the local receipt minio directory")
    return minio_root


def mirror_minio(
    source: str,
    destination: str,
    receipt_path: Path | None = None,
) -> dict[str, object]:
    """Mirror only to an explicitly confirmed isolated backup destination."""
    target = _confirmed_isolated_minio_destination(
        source,
        destination,
        BACKUP_ACCEPTANCE_MINIO_DESTINATION_ENV,
        BACKUP_ACCEPTANCE_ISOLATED_ENV,
    )
    if receipt_path is None:
        raise ValueError("a MinIO backup receipt path is required")
    minio_root = _local_backup_minio_directory(destination, receipt_path)
    if Path(target).resolve() != minio_root:
        raise ValueError("MinIO backup destination must be the local receipt minio directory")
    _evidence_key()
    postgres_pending = _read_pending_operation_receipt(
        receipt_path.parent / "postgres-backup-pending.json",
        "backup-postgres",
    )
    if postgres_pending is None:
        raise ValueError("a signed PostgreSQL backup pending record is required")
    backup_run_id = postgres_pending.get("backup_run_id")
    if not isinstance(backup_run_id, str):
        raise ValueError("a signed PostgreSQL backup pending record is required")
    result = _run_minio_mirror(source, str(minio_root))
    if result["returncode"] == 0:
        minio_entries = [
            _backup_evidence_entry(receipt_path.parent.resolve(), path)
            for path in sorted(item for item in minio_root.rglob("*") if item.is_file())
        ]
        _write_pending_operation_receipt(
            receipt_path.parent / "minio-backup-pending.json",
            "backup-minio",
            0,
            float(result["duration_seconds"]),
            minio_entries,
            backup_run_id=backup_run_id,
        )
    return result


def _isolated_restore_minio_destination(source: str, destination: str) -> str:
    return _confirmed_isolated_minio_destination(
        source,
        destination,
        RESTORE_ACCEPTANCE_MINIO_DESTINATION_ENV,
        RESTORE_ACCEPTANCE_ISOLATED_ENV,
    )


def restore_minio(
    source: str,
    destination: str,
    receipt_path: Path | None = None,
) -> dict[str, object]:
    """Restore only to the explicitly confirmed isolated MinIO destination."""
    destination = _isolated_restore_minio_destination(source, destination)
    if receipt_path is None:
        raise ValueError("a signed backup manifest is required before MinIO restore")
    manifest_path = receipt_path.parent / "manifest.json"
    if not _is_regular_evidence_file(manifest_path):
        raise ValueError("a signed backup manifest is required before MinIO restore")
    _evidence_key()
    result = _run_minio_mirror(
        source,
        destination,
    )
    _write_operation_receipt(
        manifest_path,
        receipt_path.name,
        "restore-minio",
        int(result["returncode"]),
        float(result["duration_seconds"]),
    )
    return result


def _quote_table(dialect: object, name: str, schema: str | None = None) -> str:
    preparer = dialect.identifier_preparer
    quoted_name = preparer.quote(name)
    return f"{preparer.quote_schema(schema)}.{quoted_name}" if schema else quoted_name


def _postgres_foreign_key_violations(connection: object, inspector: object) -> list[dict[str, object]]:
    violations = []
    preparer = connection.dialect.identifier_preparer
    for table in sorted(inspector.get_table_names()):
        for foreign_key in inspector.get_foreign_keys(table):
            columns = foreign_key.get("constrained_columns") or []
            referred_columns = foreign_key.get("referred_columns") or []
            referred_table = foreign_key.get("referred_table")
            if not columns or len(columns) != len(referred_columns) or not referred_table:
                continue
            child_name = _quote_table(connection.dialect, table)
            parent_name = _quote_table(
                connection.dialect,
                referred_table,
                foreign_key.get("referred_schema"),
            )
            joins = " AND ".join(
                f"child.{preparer.quote(column)} = parent.{preparer.quote(referred)}"
                for column, referred in zip(columns, referred_columns)
            )
            non_null = " OR ".join(
                f"child.{preparer.quote(column)} IS NOT NULL" for column in columns
            )
            missing = f"parent.{preparer.quote(referred_columns[0])} IS NULL"
            statement = text(
                f"SELECT COUNT(*) FROM {child_name} AS child "
                f"LEFT JOIN {parent_name} AS parent ON {joins} "
                f"WHERE ({non_null}) AND {missing}",
            )
            count = int(connection.execute(statement).scalar_one())
            if count:
                violations.append(
                    {
                        "table": table,
                        "constraint": foreign_key.get("name") or "unnamed",
                        "count": count,
                    },
                )
    return violations


def collect_database_snapshot(database_url: str) -> dict[str, object]:
    """Collect row counts and FK violations without persisting connection details."""
    engine = create_engine(database_url)
    try:
        inspector = inspect(engine)
        table_names = sorted(
            name for name in inspector.get_table_names() if name != "sqlite_sequence"
        )
        table_counts = {}
        with engine.connect() as connection:
            for table in table_names:
                table_counts[table] = int(
                    connection.execute(
                        text(f"SELECT COUNT(*) FROM {_quote_table(connection.dialect, table)}"),
                    ).scalar_one(),
                )
            if connection.dialect.name == "sqlite":
                violations = [
                    {
                        "table": str(row[0]),
                        "row_id": int(row[1]) if row[1] is not None else None,
                        "parent": str(row[2]),
                        "foreign_key": int(row[3]),
                    }
                    for row in connection.exec_driver_sql("PRAGMA foreign_key_check")
                ]
            else:
                violations = _postgres_foreign_key_violations(connection, inspector)
        return {"table_counts": table_counts, "foreign_key_violations": violations}
    finally:
        engine.dispose()


def _object_entries(manifest: Mapping[str, object]) -> list[dict[str, object]]:
    entries = []
    for item in manifest.get("files", []):
        if not isinstance(item, dict) or not isinstance(item.get("path"), str):
            continue
        path = PurePosixPath(item["path"])
        if path.parts[:1] != ("minio",) or ".." in path.parts:
            continue
        entries.append(item)
    return entries


def _remote_object_hash(bucket: str, relative_path: PurePosixPath) -> str | None:
    if _contains_credential_url(bucket):
        return None
    target = f"{bucket.rstrip('/')}/{relative_path.as_posix()}"
    try:
        completed = subprocess.run(
            ["mc", "cat", target],
            capture_output=True,
            check=False,
        )
    except OSError:
        return None
    if completed.returncode != 0:
        return None
    return hashlib.sha256(completed.stdout).hexdigest()


def _verify_object_hashes(manifest: Mapping[str, object], restored_bucket: str | Path) -> dict[str, object]:
    entries = _object_entries(manifest)
    mismatches = []
    local_root = Path(restored_bucket)
    for item in entries:
        relative = PurePosixPath(item["path"]).relative_to("minio")
        if local_root.is_dir():
            path = local_root.joinpath(*relative.parts)
            actual = _sha256_file(path) if path.is_file() else None
        else:
            actual = _remote_object_hash(str(restored_bucket), relative)
        if actual != item.get("sha256"):
            mismatches.append(relative.as_posix())
    return {
        "status": "passed" if entries and not mismatches else "failed",
        "checked": len(entries),
        "mismatches": mismatches,
    }


def _rpo_seconds(completed_at: object) -> float | None:
    if not isinstance(completed_at, str):
        return None
    try:
        completed = datetime.fromisoformat(completed_at.replace("Z", "+00:00"))
    except ValueError:
        return None
    if completed.tzinfo is None:
        return None
    elapsed = (datetime.now(timezone.utc) - completed).total_seconds()
    return elapsed if elapsed >= 0 else None


def _read_operation_receipt(
    manifest_path: Path,
    receipt_name: str,
    operation: str,
) -> dict[str, object] | None:
    receipt_path = manifest_path.parent / receipt_name
    if not _is_regular_evidence_file(receipt_path):
        return None
    try:
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        if not isinstance(receipt, dict) or set(receipt) != {
            "evidence_version",
            "operation",
            "manifest_sha256",
            "returncode",
            "duration_seconds",
            "completed_at",
            "signature",
        }:
            return None
        payload = {name: value for name, value in receipt.items() if name != "signature"}
        returncode = payload["returncode"]
        duration = payload["duration_seconds"]
        completed_at = payload["completed_at"]
        if (
            payload["evidence_version"] != _EVIDENCE_VERSION
            or payload["operation"] != operation
            or payload["manifest_sha256"] != _sha256_file(manifest_path)
            or not isinstance(returncode, int)
            or isinstance(returncode, bool)
            or not isinstance(duration, (int, float))
            or isinstance(duration, bool)
            or not math.isfinite(float(duration))
            or float(duration) < 0
            or not isinstance(completed_at, str)
            or not isinstance(receipt["signature"], str)
            or not hmac.compare_digest(receipt["signature"], _signed_evidence(payload))
        ):
            return None
        completed = datetime.fromisoformat(completed_at.replace("Z", "+00:00"))
        if completed.tzinfo is None:
            return None
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
        return None
    return {
        "returncode": returncode,
        "duration_seconds": float(duration),
        "completed_at": completed_at,
    }


def verify_restore(
    source_database: str,
    restored_database: str,
    manifest_path: Path,
    restored_bucket: str | Path,
    output: Path,
    source_minio: str | None = None,
) -> dict[str, object]:
    """Verify database counts/FKs and mirrored object hashes after restoration."""
    started = time.perf_counter()
    output.parent.mkdir(parents=True, exist_ok=True)
    try:
        restored_database = _isolated_restore_database_url(
            restored_database,
            source_database,
        )
        source_minio = source_minio or os.getenv(RESTORE_SOURCE_MINIO_ENV)
        if not source_minio:
            raise ValueError("an explicitly named MinIO restore source is required")
        restored_bucket = _confirmed_isolated_minio_destination(
            source_minio,
            str(restored_bucket),
            RESTORE_ACCEPTANCE_MINIO_DESTINATION_ENV,
            RESTORE_ACCEPTANCE_ISOLATED_ENV,
        )
        _evidence_key()
        if not _is_regular_evidence_file(manifest_path):
            raise ValueError("backup manifest must be a regular evidence file")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if not isinstance(manifest, dict):
            raise ValueError("backup manifest must be an object")
        source = collect_database_snapshot(source_database)
        restored = collect_database_snapshot(restored_database)
        objects = _verify_object_hashes(manifest, restored_bucket)
        counts_equal = source["table_counts"] == restored["table_counts"]
        fk_violations = restored["foreign_key_violations"]
        postgres_backup_operation = _read_operation_receipt(
            manifest_path,
            "postgres-backup-operation.json",
            "backup-postgres",
        )
        minio_backup_operation = _read_operation_receipt(
            manifest_path,
            "minio-backup-operation.json",
            "backup-minio",
        )
        restore_operation = _read_operation_receipt(
            manifest_path,
            "restore-operation.json",
            "restore-postgres",
        )
        minio_restore_operation = _read_operation_receipt(
            manifest_path,
            "minio-restore-operation.json",
            "restore-minio",
        )
        restore_returncode = restore_operation["returncode"] if restore_operation else None
        minio_restore_returncode = (
            minio_restore_operation["returncode"] if minio_restore_operation else None
        )
        restore_duration = (
            restore_operation["duration_seconds"] if restore_operation else None
        )
        minio_restore_duration = (
            minio_restore_operation["duration_seconds"]
            if minio_restore_operation
            else None
        )
        rto_seconds = (
            restore_duration + minio_restore_duration
            if restore_duration is not None and minio_restore_duration is not None
            else None
        )
        rto_passed = (
            restore_returncode == 0
            and minio_restore_returncode == 0
            and rto_seconds is not None
            and rto_seconds <= 1800.0
        )
        postgres_backup_returncode = (
            postgres_backup_operation["returncode"] if postgres_backup_operation else None
        )
        minio_backup_returncode = (
            minio_backup_operation["returncode"] if minio_backup_operation else None
        )
        backup_completion_times = (
            postgres_backup_operation["completed_at"]
            if postgres_backup_operation
            else None,
            minio_backup_operation["completed_at"] if minio_backup_operation else None,
        )
        try:
            oldest_backup_completion = min(
                datetime.fromisoformat(value.replace("Z", "+00:00"))
                for value in backup_completion_times
                if isinstance(value, str)
            )
        except ValueError:
            oldest_backup_completion = None
        if len([value for value in backup_completion_times if isinstance(value, str)]) != 2:
            oldest_backup_completion = None
        rpo_seconds = _rpo_seconds(
            oldest_backup_completion.isoformat() if oldest_backup_completion else None,
        )
        rpo_passed = (
            postgres_backup_returncode == 0
            and minio_backup_returncode == 0
            and rpo_seconds is not None
            and rpo_seconds <= MAX_RPO_SECONDS
        )
        passed = (
            counts_equal
            and not fk_violations
            and objects["status"] == "passed"
            and rto_passed
            and rpo_passed
        )
        result = {
            "status": "passed" if passed else "failed",
            "row_counts_equal": counts_equal,
            "source_table_counts": source["table_counts"],
            "restored_table_counts": restored["table_counts"],
            "foreign_key_violations": fk_violations,
            "object_hashes": objects,
            "postgres_backup_returncode": postgres_backup_returncode,
            "minio_backup_returncode": minio_backup_returncode,
            "restore_returncode": restore_returncode,
            "minio_restore_returncode": minio_restore_returncode,
            "rto_seconds": rto_seconds,
            "rto_passed": rto_passed,
            "rpo_seconds": rpo_seconds,
            "rpo_passed": rpo_passed,
            "verification_seconds": time.perf_counter() - started,
        }
    except (OSError, ValueError, SQLAlchemyError, json.JSONDecodeError):
        result = {
            "status": "failed",
            "error_code": "BACKUP_RESTORE_VERIFY_FAILED",
            "postgres_backup_returncode": None,
            "minio_backup_returncode": None,
            "restore_returncode": None,
            "rto_seconds": None,
            "rto_passed": False,
            "rpo_seconds": None,
            "rpo_passed": False,
            "verification_seconds": time.perf_counter() - started,
        }
    output.write_text(
        json.dumps(result, ensure_ascii=True, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    backup = subparsers.add_parser("backup-postgres")
    backup.add_argument("--database-url-env", required=True)
    backup.add_argument("--output", type=Path, required=True)
    backup_minio_parser = subparsers.add_parser("backup-minio")
    backup_minio_parser.add_argument("--source", required=True)
    backup_minio_parser.add_argument("--destination", required=True)
    backup_minio_parser.add_argument("--receipt-dir", type=Path, required=True)
    restore = subparsers.add_parser("restore-postgres")
    restore.add_argument(
        "--database-url-env",
        default=RESTORE_ACCEPTANCE_DATABASE_URL_ENV,
    )
    restore.add_argument(
        "--source-database-url-env",
        default=RESTORE_SOURCE_DATABASE_URL_ENV,
    )
    restore.add_argument("--dump", type=Path, required=True)
    restore_minio_parser = subparsers.add_parser("restore-minio")
    restore_minio_parser.add_argument("--source", required=True)
    restore_minio_parser.add_argument("--destination", required=True)
    restore_minio_parser.add_argument("--receipt-dir", type=Path, required=True)
    manifest = subparsers.add_parser("manifest")
    manifest.add_argument("--root", type=Path, required=True)
    manifest.add_argument("--created-at", help=argparse.SUPPRESS)
    verify = subparsers.add_parser("verify")
    verify.add_argument("--source-database-env", required=True)
    verify.add_argument("--restored-database-env", required=True)
    verify.add_argument("--source-minio-env", default=RESTORE_SOURCE_MINIO_ENV)
    verify.add_argument("--manifest", type=Path, required=True)
    verify.add_argument("--restored-bucket", required=True)
    verify.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)

    if args.command == "backup-postgres":
        result = backup_postgres(os.environ[args.database_url_env], args.output)
        exit_code = int(result["returncode"])
    elif args.command == "backup-minio":
        result = mirror_minio(
            args.source,
            args.destination,
            args.receipt_dir / "minio-backup-operation.json",
        )
        exit_code = int(result["returncode"])
    elif args.command == "restore-postgres":
        database_url = os.getenv(args.database_url_env)
        source_database_url = os.getenv(args.source_database_url_env)
        if database_url is None or source_database_url is None:
            raise ValueError("an explicitly confirmed isolated restore database is required")
        result = restore_postgres(database_url, args.dump, source_database_url)
        exit_code = int(result["returncode"])
    elif args.command == "restore-minio":
        result = restore_minio(
            args.source,
            args.destination,
            args.receipt_dir / "minio-restore-operation.json",
        )
        exit_code = int(result["returncode"])
    elif args.command == "verify":
        source_database_url = os.getenv(args.source_database_env)
        restored_database_url = os.getenv(args.restored_database_env)
        source_minio = os.getenv(args.source_minio_env)
        if (
            source_database_url is None
            or restored_database_url is None
            or source_minio is None
        ):
            raise ValueError("isolated restore source environment values are required")
        result = verify_restore(
            source_database_url,
            restored_database_url,
            args.manifest,
            args.restored_bucket,
            args.output,
            source_minio,
        )
        exit_code = 0 if result["status"] == "passed" else 1
    else:
        if args.created_at is not None:
            raise ValueError("manifest creation time is generated by this tool")
        result = create_backup_manifest(args.root)
        exit_code = 0
    print(json.dumps(result, ensure_ascii=True, sort_keys=True))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
