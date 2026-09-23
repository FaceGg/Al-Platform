"""Immutable return-batch snapshots and task-return coverage helpers."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from typing import Any

from sqlalchemy import and_, or_

from app.models.labeling import (
    AnnotationAssignment,
    AnnotationReturnBatch,
    AnnotationReturnBatchSample,
)
from app.models.operation import DurableOperation
from app.models.platform_models import (
    AnnotationTaskRevisionSnapshot,
    AnnotationTaskScopeSample,
    GenericAnnotationTask,
)
from app.services.annotation_scope import has_persisted_scope, iter_scope_batches
from app.services.annotation_strategies import label_schema_contract_from_snapshot


_BATCH_SIZE = 500


class AnnotationReturnSnapshotError(ValueError):
    def __init__(self, code: str, message: str | None = None):
        self.code = code
        super().__init__(message or code)


@dataclass(frozen=True)
class ReturnCoverage:
    all_returned: bool
    all_accepted: bool


def task_snapshot_for_revision(
    db,
    task: GenericAnnotationTask,
    task_revision: int,
) -> dict[str, Any]:
    """Resolve the immutable snapshot that produced a return batch."""
    revision = db.query(AnnotationTaskRevisionSnapshot).filter_by(
        task_id=task.id,
        task_revision=int(task_revision),
    ).one_or_none()
    if revision is not None:
        return dict(revision.snapshot or {})
    if int(task.task_revision) == int(task_revision) or int(task_revision) == 0:
        snapshot = dict(task.task_snapshot or {})
        if snapshot:
            return snapshot
    raise AnnotationReturnSnapshotError("RETURN_BATCH_REVISION_CONFLICT")


def label_contract_for_return_snapshot(snapshot: Mapping[str, Any]):
    schema = snapshot.get("label_schema") if isinstance(snapshot, Mapping) else None
    if not isinstance(schema, Mapping) or not isinstance(schema.get("columns"), list) or not schema["columns"]:
        raise AnnotationReturnSnapshotError("RETURN_LABEL_SCHEMA_INVALID")
    try:
        return label_schema_contract_from_snapshot(dict(schema))
    except (KeyError, TypeError, ValueError) as error:
        raise AnnotationReturnSnapshotError("RETURN_LABEL_SCHEMA_INVALID") from error


def iter_return_batch_sample_batches(
    db,
    return_batch_id,
    *,
    batch_size: int = _BATCH_SIZE,
) -> Iterator[list[AnnotationReturnBatchSample]]:
    """Read frozen batch rows with keyset pagination."""
    if batch_size <= 0:
        raise ValueError("RETURN_BATCH_PAGE_SIZE_INVALID")
    marker = None
    while True:
        query = db.query(AnnotationReturnBatchSample).filter(
            AnnotationReturnBatchSample.return_batch_id == return_batch_id,
        )
        if marker is not None:
            query = query.filter(or_(
                AnnotationReturnBatchSample.sample_id > marker.sample_id,
                and_(
                    AnnotationReturnBatchSample.sample_id == marker.sample_id,
                    AnnotationReturnBatchSample.id > marker.id,
                ),
            ))
        rows = query.order_by(
            AnnotationReturnBatchSample.sample_id.asc(),
            AnnotationReturnBatchSample.id.asc(),
        ).limit(batch_size).all()
        if not rows:
            return
        yield rows
        marker = rows[-1]


def return_batch_sample_count(db, return_batch_id) -> int:
    return int(db.query(AnnotationReturnBatchSample).filter_by(
        return_batch_id=return_batch_id,
    ).count())


def return_batch_checksum(
    db,
    batch: AnnotationReturnBatch,
    snapshot: Mapping[str, Any],
) -> str:
    """Hash the exact immutable return payload in deterministic row order."""
    digest = hashlib.sha256()
    digest.update(json.dumps(
        {
            "format": "annotation-return-batch-v1",
            "return_batch_id": str(batch.id),
            "task_revision": int(batch.task_revision),
            "scope_hash": str(batch.scope_hash),
            "label_schema": dict(snapshot.get("label_schema") or {}),
        },
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8"))
    for rows in iter_return_batch_sample_batches(db, batch.id):
        for row in rows:
            digest.update(b"\n")
            digest.update(json.dumps(
                {
                    "sample_id": str(row.sample_id),
                    "row_index": int(row.row_index),
                    "revision_no": int(row.revision_no),
                    "values": dict(row.values or {}),
                    "provenance": dict(row.provenance or {}),
                },
                ensure_ascii=True,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8"))
    return "sha256:" + digest.hexdigest()


def scope_row_indexes(
    db,
    task: GenericAnnotationTask,
    *,
    task_revision: int,
    snapshot: Mapping[str, Any],
    sample_ids: list[str],
) -> dict[str, int]:
    """Resolve only one return page against the server-owned frozen scope."""
    wanted = {str(sample_id) for sample_id in sample_ids}
    if not wanted:
        return {}
    if has_persisted_scope(db, task.id, task_revision, snapshot):
        rows = db.query(
            AnnotationTaskScopeSample.sample_id,
            AnnotationTaskScopeSample.row_index,
        ).filter(
            AnnotationTaskScopeSample.task_id == task.id,
            AnnotationTaskScopeSample.task_revision == task_revision,
            AnnotationTaskScopeSample.sample_id.in_(wanted),
        ).all()
        return {str(sample_id): int(row_index) for sample_id, row_index in rows}
    return {
        str(sample_id): int(row_index)
        for scope_batch in iter_scope_batches(
            db,
            task,
            task_revision=task_revision,
            snapshot=snapshot,
        )
        for sample_id, row_index in scope_batch
        if str(sample_id) in wanted
    }


def _coverage_query(db, task: GenericAnnotationTask, task_revision: int, *, accepted_only: bool, include_pending_batch_id=None):
    query = db.query(AnnotationReturnBatchSample.sample_id.label("sample_id")).join(
        AnnotationReturnBatch,
        AnnotationReturnBatch.id == AnnotationReturnBatchSample.return_batch_id,
    ).join(
        AnnotationAssignment,
        AnnotationAssignment.id == AnnotationReturnBatch.assignment_id,
    ).outerjoin(
        DurableOperation,
        DurableOperation.id == AnnotationReturnBatch.operation_id,
    ).filter(
        AnnotationAssignment.task_id == task.id,
        AnnotationReturnBatch.task_revision == task_revision,
    )
    if accepted_only:
        query = query.filter(AnnotationReturnBatch.state == "accepted")
    else:
        query = query.filter(or_(
            AnnotationReturnBatch.state == "accepted",
            and_(
                AnnotationReturnBatch.state == "pending",
                or_(
                    DurableOperation.state == "completed",
                    AnnotationReturnBatch.id == include_pending_batch_id,
                ),
            ),
        ))
    return query.distinct()


def _scope_has_uncovered_sample(
    db,
    task: GenericAnnotationTask,
    *,
    task_revision: int,
    snapshot: Mapping[str, Any],
    accepted_only: bool,
    include_pending_batch_id=None,
) -> bool:
    coverage = _coverage_query(
        db,
        task,
        task_revision,
        accepted_only=accepted_only,
        include_pending_batch_id=include_pending_batch_id,
    )
    if has_persisted_scope(db, task.id, task_revision, snapshot):
        covered = coverage.subquery()
        missing = db.query(AnnotationTaskScopeSample.id).outerjoin(
            covered,
            covered.c.sample_id == AnnotationTaskScopeSample.sample_id,
        ).filter(
            AnnotationTaskScopeSample.task_id == task.id,
            AnnotationTaskScopeSample.task_revision == task_revision,
            covered.c.sample_id.is_(None),
        ).first()
        return missing is not None

    seen = False
    for scope_batch in iter_scope_batches(
        db,
        task,
        task_revision=task_revision,
        snapshot=snapshot,
    ):
        seen = True
        sample_ids = [sample_id for sample_id, _ in scope_batch]
        covered_ids = {
            str(sample_id)
            for (sample_id,) in coverage.filter(
                AnnotationReturnBatchSample.sample_id.in_(sample_ids),
            ).all()
        }
        if set(sample_ids) != covered_ids:
            return True
    return not seen


def return_coverage(
    db,
    task: GenericAnnotationTask,
    *,
    task_revision: int,
    snapshot: Mapping[str, Any],
    include_pending_batch_id=None,
) -> ReturnCoverage:
    return ReturnCoverage(
        all_returned=not _scope_has_uncovered_sample(
            db,
            task,
            task_revision=task_revision,
            snapshot=snapshot,
            accepted_only=False,
            include_pending_batch_id=include_pending_batch_id,
        ),
        all_accepted=not _scope_has_uncovered_sample(
            db,
            task,
            task_revision=task_revision,
            snapshot=snapshot,
            accepted_only=True,
        ),
    )


def refresh_task_return_state(
    db,
    task: GenericAnnotationTask,
    *,
    task_revision: int,
    snapshot: Mapping[str, Any],
    include_pending_batch_id=None,
) -> ReturnCoverage:
    """Derive return lifecycle state without using mutable assignment values."""
    coverage = return_coverage(
        db,
        task,
        task_revision=task_revision,
        snapshot=snapshot,
        include_pending_batch_id=include_pending_batch_id,
    )
    if task.status in {"paused", "cancelled", "archived", "completed"}:
        return coverage
    if coverage.all_accepted:
        task.status = "accepted"
    elif coverage.all_returned:
        task.status = "returned_pending_acceptance"
    elif task.status != "in_progress":
        task.status = "awaiting_return"
    return coverage
