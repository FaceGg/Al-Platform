"""Lease, completion, and cleanup primitives shared by durable workers."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import re
import time
from typing import Iterable

from sqlalchemy import and_, or_, update

from app.models.operation import DurableOperation
from app.storage.local import LocalStorage


_SHA256 = re.compile(r"^sha256:[0-9a-f]{64}$")
_SENSITIVE = re.compile(r"password|secret|token|api[_-]?key", re.IGNORECASE)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _redact(value):
    if isinstance(value, dict):
        return {str(key): "[redacted]" if _SENSITIVE.search(str(key)) else _redact(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_redact(item) for item in value]
    return value


def claim_operation(db, operation_id, worker_id: str, lease_seconds: int) -> bool:
    """Atomically claim a queued or expired operation.

    The conditional UPDATE is the concurrency boundary.  A read followed by
    a normal ORM assignment lets two workers both observe an expired lease and
    publish duplicate work; the row-count check below makes only one claimant
    win.  A worker that already owns a live lease gets an idempotent success
    without incrementing the retry attempt.
    """
    if isinstance(lease_seconds, bool) or lease_seconds <= 0 or lease_seconds > 86400 or not worker_id:
        raise ValueError("OPERATION_LEASE_INVALID")
    operation = db.get(DurableOperation, operation_id)
    if operation is None:
        raise ValueError("OPERATION_NOT_FOUND")
    now = _utcnow()
    if operation.state == "completed":
        return False
    if operation.lease_owner and operation.lease_expires_at and operation.lease_expires_at >= now and operation.lease_owner != worker_id:
        return False
    if operation.lease_owner == worker_id and operation.lease_expires_at and operation.lease_expires_at >= now:
        return True

    expires = now + timedelta(seconds=lease_seconds)
    result = db.execute(
        update(DurableOperation)
        .where(
            DurableOperation.id == operation_id,
            DurableOperation.state != "completed",
            or_(
                DurableOperation.lease_owner.is_(None),
                DurableOperation.lease_expires_at < now,
            ),
        )
        .values(
            lease_owner=worker_id,
            lease_expires_at=expires,
            heartbeat_at=now,
            state="running",
            stage="running",
            attempt=DurableOperation.attempt + 1,
        )
    )
    if result.rowcount != 1:
        db.rollback()
        return False
    db.commit()
    return True


def claim_operation_dispatch(db, operation_id, retry_seconds: int = 30) -> bool:
    """Atomically reserve one queued operation for dispatch.

    Dispatch acknowledgement is persisted separately from worker leases so a
    worker can claim immediately after the enqueue call. A second recovery
    process only wins after the dispatch marker ages out.
    """
    if isinstance(retry_seconds, bool) or retry_seconds <= 0 or retry_seconds > 86400:
        raise ValueError("OPERATION_DISPATCH_INVALID")
    now = _utcnow()
    retry_before = now - timedelta(seconds=retry_seconds)
    result = db.execute(
        update(DurableOperation)
        .where(
            DurableOperation.id == operation_id,
            DurableOperation.state == "queued",
            or_(
                DurableOperation.stage != "dispatched",
                DurableOperation.heartbeat_at.is_(None),
                DurableOperation.heartbeat_at < retry_before,
            ),
        )
        .values(stage="dispatched", heartbeat_at=now)
    )
    if result.rowcount != 1:
        db.rollback()
        return False
    db.commit()
    db.expire_all()
    return True


def heartbeat_operation(db, operation_id, worker_id: str, lease_seconds: int = 30) -> None:
    if isinstance(lease_seconds, bool) or lease_seconds <= 0 or lease_seconds > 86400:
        raise ValueError("OPERATION_LEASE_INVALID")
    operation = db.get(DurableOperation, operation_id)
    if operation is None:
        raise ValueError("OPERATION_NOT_FOUND")
    now = _utcnow()
    result = db.execute(
        update(DurableOperation)
        .where(
            DurableOperation.id == operation_id,
            DurableOperation.lease_owner == worker_id,
            DurableOperation.state == "running",
            DurableOperation.lease_expires_at >= now,
        )
        .values(
            heartbeat_at=now,
            lease_expires_at=now + timedelta(seconds=lease_seconds),
        )
    )
    if result.rowcount != 1:
        db.rollback()
        raise ValueError("OPERATION_LEASE_NOT_OWNED")
    db.commit()
    db.expire_all()


def complete_operation(db, operation_id, *args, worker_id: str | None = None, result_artifact_id=None, checksum: str | None = None, result_summary: dict | None = None) -> None:
    """Commit a result only while the current lease is still valid.

    The public plan omits ``worker_id`` and uses the current lease owner;
    older callers pass ``worker_id`` as the first positional argument.  Both
    forms remain supported while the update itself stays lease-guarded.
    """
    if args:
        if len(args) == 3:
            worker_id, result_artifact_id, checksum = args
        elif len(args) == 2:
            result_artifact_id, checksum = args
        else:
            raise TypeError("complete_operation expects result_artifact_id, checksum[, worker_id]")
    if _SHA256.fullmatch(checksum or "") is None:
        raise ValueError("OPERATION_CHECKSUM_INVALID")
    operation = db.get(DurableOperation, operation_id)
    if operation is None:
        raise ValueError("OPERATION_NOT_FOUND")
    worker_id = worker_id or operation.lease_owner
    if not worker_id:
        raise ValueError("OPERATION_LEASE_NOT_OWNED")
    now = _utcnow()
    result = db.execute(
        update(DurableOperation)
        .where(
            DurableOperation.id == operation_id,
            DurableOperation.lease_owner == worker_id,
            DurableOperation.state == "running",
            DurableOperation.lease_expires_at >= now,
        )
        .values(
            result_artifact_id=result_artifact_id,
            checksum=checksum,
            result_summary=result_summary,
            error_code=None,
            error_details=None,
            progress=100,
            stage="completed",
            state="completed",
            lease_owner=None,
            lease_expires_at=None,
        )
    )
    if result.rowcount != 1:
        db.rollback()
        raise ValueError("OPERATION_LEASE_NOT_OWNED")
    db.commit()
    db.expire_all()


def fail_operation(db, operation_id, error_code: str, error_details: dict | None = None, *, worker_id: str | None = None) -> None:
    operation = db.get(DurableOperation, operation_id)
    if operation is None:
        raise ValueError("OPERATION_NOT_FOUND")
    if operation.state == "completed":
        raise ValueError("OPERATION_LEASE_NOT_OWNED")
    if worker_id is not None and operation.lease_owner != worker_id:
        raise ValueError("OPERATION_LEASE_NOT_OWNED")
    operation.state = "failed"
    operation.stage = "failed"
    operation.result_artifact_id = None
    operation.checksum = None
    operation.error_code = str(error_code)[:64]
    operation.error_details = _redact(error_details or {})
    operation.lease_owner = None
    operation.lease_expires_at = None
    db.commit()
    db.expire_all()


def recover_expired_operations(db, *, worker_id: str, lease_seconds: int = 30, limit: int = 100) -> tuple[str, ...]:
    """Reclaim expired operation leases in a deterministic, bounded pass.

    Recovery is intentionally expressed through the same conditional claim
    used by workers. A concurrent recovery/worker race therefore yields one
    claimant, while a live lease is left untouched.
    """
    if not worker_id or isinstance(limit, bool) or limit < 1:
        raise ValueError("OPERATION_RECOVERY_INVALID")
    now = _utcnow()
    candidates = (
        db.query(DurableOperation.id)
        .filter(
            DurableOperation.state.in_(("queued", "running")),
            DurableOperation.lease_expires_at.is_not(None),
            DurableOperation.lease_expires_at < now,
        )
        .order_by(DurableOperation.updated_at, DurableOperation.id)
        .limit(limit)
        .all()
    )
    recovered: list[str] = []
    for (operation_id,) in candidates:
        if claim_operation(db, operation_id, worker_id, lease_seconds):
            recovered.append(str(operation_id))
    # Tests and worker callers may hold ORM instances across recovery. Bulk
    # updates do not reliably refresh those objects on every SQL dialect.
    db.expire_all()
    return tuple(recovered)


@dataclass(frozen=True)
class CleanupReport:
    status: str
    scanned: int
    removed: int
    retained_committed: int
    errors: list[str]
    ttl_seconds: int
    source_commit: str | None = None


def cleanup_orphan_artifacts(storage, older_than: timedelta, *, committed_paths: Iterable[Path] = ()) -> CleanupReport:
    if not isinstance(storage, LocalStorage):
        raise ValueError("CLEANUP_STORAGE_UNSUPPORTED")
    ttl_seconds = int(older_than.total_seconds())
    if ttl_seconds < 0:
        raise ValueError("CLEANUP_TTL_INVALID")
    committed = {Path(path).resolve() for path in committed_paths}
    # ``_utcnow()`` is intentionally naive for database compatibility; calling
    # ``timestamp()`` on it would reinterpret UTC as the host local timezone.
    # Use the epoch clock for filesystem mtime comparisons instead.
    cutoff = time.time() - ttl_seconds
    scanned = removed = retained_committed = 0
    errors: list[str] = []
    for path in storage.base_dir.rglob("*"):
        if not path.is_file():
            continue
        scanned += 1
        resolved = path.resolve()
        if resolved in committed:
            retained_committed += 1
            continue
        if path.stat().st_mtime > cutoff or not path.name.startswith("."):
            continue
        try:
            path.unlink()
            removed += 1
        except OSError:
            errors.append("artifact_delete_failed")
    return CleanupReport(
        status="passed" if not errors else "failed",
        scanned=scanned,
        removed=removed,
        retained_committed=retained_committed,
        errors=errors,
        ttl_seconds=ttl_seconds,
    )


def write_cleanup_report(storage, output: Path, older_than: timedelta, source_commit: str, *, committed_paths: Iterable[Path] = ()) -> Path:
    if re.fullmatch(r"[0-9a-f]{40}", source_commit or "") is None:
        raise ValueError("CLEANUP_SOURCE_COMMIT_INVALID")
    report = cleanup_orphan_artifacts(storage, older_than, committed_paths=committed_paths)
    payload = {**asdict(report), "source_commit": source_commit}
    serialized = json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True) + "\n"
    target = Path(output)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.{hashlib.sha256(serialized.encode()).hexdigest()[:12]}.tmp")
    temporary.write_text(serialized, encoding="utf-8")
    temporary.replace(target)
    return target
