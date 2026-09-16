"""Immutable, indexed task-scope storage and bounded readers."""

from __future__ import annotations

import hashlib
from collections.abc import Iterable, Iterator, Sequence
from typing import Mapping

from sqlalchemy import and_, or_

from app.models.platform_models import AnnotationTaskScopeSample, GenericAnnotationTask


_SCOPE_STORAGE = "annotation_task_scope_samples"
_SCOPE_BATCH_SIZE = 500


def _chunks(values: Sequence[str], size: int = _SCOPE_BATCH_SIZE) -> Iterator[Sequence[str]]:
    for start in range(0, len(values), size):
        yield values[start:start + size]


def scope_digest(entries: Iterable[tuple[str, int]]) -> tuple[int, str]:
    """Hash the ordered frozen scope without retaining its identifiers."""
    digest = hashlib.sha256()
    digest.update(b"annotation-task-scope-v1\x00")
    count = 0
    for sample_id, row_index in entries:
        digest.update(str(int(row_index)).encode("utf-8"))
        digest.update(b"\x00")
        digest.update(str(sample_id).encode("utf-8"))
        digest.update(b"\x00")
        count += 1
    return count, "sha256:" + digest.hexdigest()


def scope_descriptor(sample_count: int, scope_hash: str) -> dict[str, object]:
    return {
        "storage": _SCOPE_STORAGE,
        "sample_count": int(sample_count),
        "scope_hash": str(scope_hash),
    }


def _uses_persisted_scope(snapshot: Mapping[str, object] | None) -> bool:
    scope = (snapshot or {}).get("scope")
    return isinstance(scope, Mapping) and scope.get("storage") == _SCOPE_STORAGE


def has_persisted_scope(db, task_id, task_revision: int, snapshot: Mapping[str, object] | None = None) -> bool:
    if _uses_persisted_scope(snapshot):
        return True
    return db.query(AnnotationTaskScopeSample.id).filter_by(
        task_id=task_id,
        task_revision=task_revision,
    ).first() is not None


def scope_count(db, task: GenericAnnotationTask, *, task_revision: int, snapshot: Mapping[str, object]) -> int:
    if has_persisted_scope(db, task.id, task_revision, snapshot):
        return int(db.query(AnnotationTaskScopeSample).filter_by(
            task_id=task.id,
            task_revision=task_revision,
        ).count())
    return len((snapshot or {}).get("sample_ids") or ())


def iter_scope_batches(
    db,
    task: GenericAnnotationTask,
    *,
    task_revision: int,
    snapshot: Mapping[str, object],
    batch_size: int = _SCOPE_BATCH_SIZE,
) -> Iterator[list[tuple[str, int]]]:
    """Yield the frozen scope in source order with stable keyset pagination."""
    if batch_size <= 0:
        raise ValueError("SCOPE_BATCH_SIZE_INVALID")
    if has_persisted_scope(db, task.id, task_revision, snapshot):
        marker = None
        while True:
            query = db.query(AnnotationTaskScopeSample).filter_by(
                task_id=task.id,
                task_revision=task_revision,
            )
            if marker is not None:
                query = query.filter(or_(
                    AnnotationTaskScopeSample.row_index > marker.row_index,
                    and_(
                        AnnotationTaskScopeSample.row_index == marker.row_index,
                        AnnotationTaskScopeSample.id > marker.id,
                    ),
                ))
            rows = query.order_by(
                AnnotationTaskScopeSample.row_index.asc(),
                AnnotationTaskScopeSample.id.asc(),
            ).limit(batch_size).all()
            if not rows:
                return
            yield [(str(row.sample_id), int(row.row_index)) for row in rows]
            marker = rows[-1]
        return

    # Existing deployments may still have immutable snapshots containing a
    # bounded list. New tasks never take this path.
    legacy_ids = [str(sample_id) for sample_id in (snapshot or {}).get("sample_ids") or ()]
    for start in range(0, len(legacy_ids), batch_size):
        yield [
            (sample_id, start + offset)
            for offset, sample_id in enumerate(legacy_ids[start:start + batch_size])
        ]


def persist_scope_entries(
    db,
    task_id,
    task_revision: int,
    entries: Iterable[tuple[str, int]],
    *,
    batch_size: int = _SCOPE_BATCH_SIZE,
) -> int:
    """Persist one revision's immutable scope in bounded inserts."""
    if batch_size <= 0:
        raise ValueError("SCOPE_BATCH_SIZE_INVALID")
    batch: list[AnnotationTaskScopeSample] = []
    count = 0
    for sample_id, row_index in entries:
        batch.append(AnnotationTaskScopeSample(
            task_id=task_id,
            task_revision=int(task_revision),
            sample_id=str(sample_id),
            row_index=int(row_index),
        ))
        count += 1
        if len(batch) >= batch_size:
            db.add_all(batch)
            db.flush()
            batch = []
    if batch:
        db.add_all(batch)
        db.flush()
    return count


def copy_scope_revision(
    db,
    task: GenericAnnotationTask,
    *,
    from_revision: int,
    to_revision: int,
    source_snapshot: Mapping[str, object],
    target_snapshot: Mapping[str, object],
) -> int:
    """Freeze a new configuration revision against the same source scope."""
    return persist_scope_entries(
        db,
        task.id,
        to_revision,
        (
            entry
            for batch in iter_scope_batches(
                db,
                task,
                task_revision=from_revision,
                snapshot=source_snapshot,
            )
            for entry in batch
        ),
    )


def missing_scope_sample_ids(
    db,
    task: GenericAnnotationTask,
    *,
    task_revision: int,
    snapshot: Mapping[str, object],
    sample_ids: Sequence[str],
) -> set[str]:
    """Check a caller-provided scope without loading the task's full scope."""
    requested = {str(sample_id) for sample_id in sample_ids if str(sample_id)}
    if not requested:
        return set()
    if not has_persisted_scope(db, task.id, task_revision, snapshot):
        frozen = {str(sample_id) for sample_id in (snapshot or {}).get("sample_ids") or ()}
        return requested - frozen
    found: set[str] = set()
    values = sorted(requested)
    for batch in _chunks(values):
        rows = db.query(AnnotationTaskScopeSample.sample_id).filter(
            AnnotationTaskScopeSample.task_id == task.id,
            AnnotationTaskScopeSample.task_revision == task_revision,
            AnnotationTaskScopeSample.sample_id.in_(batch),
        ).all()
        found.update(str(sample_id) for (sample_id,) in rows)
    return requested - found
