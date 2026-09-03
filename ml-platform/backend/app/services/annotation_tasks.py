"""Generic annotation task boundary and legacy quality-run adapter."""

from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from app.models.platform_models import GenericAnnotationTask
from app.models.spot_weld_quality import (
    SpotWeldLabelRevision,
    SpotWeldLabelSnapshot,
    SpotWeldQualityRun,
    SpotWeldQualitySample,
)


def migrate_legacy_quality_run(db: Session, run_id: uuid.UUID) -> GenericAnnotationTask:
    """Copy one legacy quality run into the generic task boundary.

    The legacy rows remain untouched. Repeated calls are idempotent through the
    unique ``source_legacy_id`` marker and preserve sample/label snapshots for
    downstream data-version and schema migrations.
    """
    run_uuid = run_id if isinstance(run_id, uuid.UUID) else uuid.UUID(str(run_id))
    existing = db.query(GenericAnnotationTask).filter(
        GenericAnnotationTask.source_legacy_id == str(run_uuid)
    ).first()
    if existing is not None:
        return existing

    run = db.query(SpotWeldQualityRun).filter(SpotWeldQualityRun.id == run_uuid).first()
    if run is None:
        raise ValueError("LEGACY_QUALITY_RUN_NOT_FOUND")

    samples = db.query(SpotWeldQualitySample).filter(
        SpotWeldQualitySample.run_id == run.id
    ).order_by(SpotWeldQualitySample.source_row_index).all()
    revisions = db.query(SpotWeldLabelRevision).filter(
        SpotWeldLabelRevision.run_id == run.id
    ).order_by(SpotWeldLabelRevision.created_at).all()
    snapshots = db.query(SpotWeldLabelSnapshot).filter(
        SpotWeldLabelSnapshot.run_id == run.id
    ).order_by(SpotWeldLabelSnapshot.created_at).all()

    label_snapshot = {
        "legacy_run_id": str(run.id),
        "samples": [
            {
                "source_row_index": sample.source_row_index,
                "display_id": sample.display_id,
                "table_values": sample.table_values or {},
                "automatic_label": sample.automatic_label,
                "current_label": sample.current_label,
                "current_note": sample.current_note,
                "cluster_id": sample.cluster_id,
                "rule_hits": sample.rule_hits or [],
            }
            for sample in samples
        ],
        "revisions": [
            {
                "id": str(revision.id),
                "sample_id": str(revision.sample_id),
                "label": revision.label,
                "note": revision.note,
                "action": revision.action,
                "decision": revision.decision,
            }
            for revision in revisions
        ],
        "snapshots": [
            {
                "id": str(snapshot.id),
                "name": snapshot.name,
                "labels": snapshot.labels or [],
                "label_counts": snapshot.label_counts or {},
            }
            for snapshot in snapshots
        ],
    }
    task = GenericAnnotationTask(
        project_id=run.project_id,
        dataset_version_id=run.dataset_artifact_id,
        label_schema_id=(snapshots[0].id if snapshots else uuid.uuid4()),
        owner_id=run.created_by_id,
        mode="automatic" if run.automl_results else "manual",
        status="completed" if run.status in {"completed", "success"} else "pending",
        sample_scope={"kind": "all", "legacy_run_id": str(run.id)},
        label_snapshot=label_snapshot,
        source_legacy_id=str(run.id),
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    return task
