"""Generic annotation task boundary and legacy quality-run adapter."""

from __future__ import annotations

import uuid
import hashlib
import json

from sqlalchemy.exc import IntegrityError
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

    transition_schema_id = uuid.uuid5(
        uuid.NAMESPACE_URL, f"generic-transition-label-schema:{run.id}"
    )
    label_snapshot = {
        "legacy_run_id": str(run.id),
        "run_metadata": {
            "project_id": str(run.project_id),
            "created_by_id": str(run.created_by_id),
            "status": run.status,
            "field_mapping": run.field_mapping or {},
            "feature_schema": run.feature_schema or [],
            "input_fingerprint": run.input_fingerprint or {},
            "statistics": run.statistics or {},
            "automl_results": run.automl_results or [],
            "clustering_results": run.clustering_results or {},
            "output_artifacts": run.output_artifacts or {},
            "rule_set_version": run.rule_set_version,
        },
        "transition_schema": {
            "id": str(transition_schema_id),
            "kind": "legacy-quality-run-snapshot",
            "source_run_id": str(run.id),
            "source_snapshot_ids": [str(snapshot.id) for snapshot in snapshots],
        },
        "samples": [
            {
                "id": str(sample.id),
                "source_row_index": sample.source_row_index,
                "display_id": sample.display_id,
                "table_values": sample.table_values or {},
                "automatic_label": sample.automatic_label,
                "current_label": sample.current_label,
                "current_note": sample.current_note,
                "cluster_id": sample.cluster_id,
                "rule_hits": sample.rule_hits or [],
                "created_at": sample.created_at.isoformat() if sample.created_at else None,
                "updated_at": sample.updated_at.isoformat() if sample.updated_at else None,
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
                "project_id": str(revision.project_id),
                "author_id": str(revision.author_id),
                "review_comment": revision.review_comment,
                "parent_revision_id": str(revision.parent_revision_id) if revision.parent_revision_id else None,
                "created_at": revision.created_at.isoformat() if revision.created_at else None,
            }
            for revision in revisions
        ],
        "snapshots": [
            {
                "id": str(snapshot.id),
                "name": snapshot.name,
                "labels": snapshot.labels or [],
                "label_counts": snapshot.label_counts or {},
                "project_id": str(snapshot.project_id),
                "run_id": str(snapshot.run_id),
                "created_by_id": str(snapshot.created_by_id),
                "created_at": snapshot.created_at.isoformat() if snapshot.created_at else None,
            }
            for snapshot in snapshots
        ],
    }
    canonical_json = json.dumps(label_snapshot, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    label_snapshot["canonical_json"] = canonical_json
    label_snapshot["checksum"] = hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()
    if len(samples) != len(label_snapshot["samples"]):
        raise ValueError("LEGACY_MIGRATION_SAMPLE_COUNT_MISMATCH")
    if {str(sample.id) for sample in samples} != {item["id"] for item in label_snapshot["samples"]}:
        raise ValueError("LEGACY_MIGRATION_SAMPLE_ID_MISMATCH")
    task = GenericAnnotationTask(
        project_id=run.project_id,
        dataset_version_id=run.dataset_artifact_id,
        label_schema_id=transition_schema_id,
        owner_id=run.created_by_id,
        mode="automatic" if run.automl_results else "manual",
        status="completed" if run.status in {"completed", "success"} else "pending",
        sample_scope={"kind": "all", "legacy_run_id": str(run.id)},
        label_snapshot=label_snapshot,
        source_legacy_id=str(run.id),
    )
    db.add(task)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        existing = db.query(GenericAnnotationTask).filter(
            GenericAnnotationTask.source_legacy_id == str(run_uuid)
        ).first()
        if existing is not None:
            return existing
        raise
    db.refresh(task)
    return task
