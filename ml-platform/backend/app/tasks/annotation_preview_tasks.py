"""Durable preview execution for generic annotation tasks."""

import uuid
import hashlib
import json
import threading
from types import SimpleNamespace

import pandas as pd
from sqlalchemy import and_, or_

from app.database import SessionLocal
from app.models.data_version import DatasetSample
from app.models.labeling import AnnotationStrategyArtifact
from app.models.platform_models import AnnotationTaskPreview, AnnotationTaskPreviewSample, GenericAnnotationTask
from app.services.annotation_strategies import (
    StrategyConfigError,
    _artifact_model_package,
    apply_preview_annotation_strategy,
    build_streaming_cluster_artifact_from_package,
)
from app.services.annotation_task_state import (
    current_annotation_task_snapshot,
    mark_preview_completed,
    record_annotation_preview_progress,
)
from app.services.annotation_scope import iter_scope_batches, scope_count
from app.services.weighted_clustering import assign_clusters_from_artifact, cluster_artifact_from_payload
from app.services.operation_lifecycle import claim_operation, heartbeat_operation, complete_operation, fail_operation
from app.tasks.celery_app import celery_app
from app.config import settings


_PREVIEW_BATCH_SIZE = 500


def _chunks(values, size=_PREVIEW_BATCH_SIZE):
    for start in range(0, len(values), size):
        yield values[start:start + size]


def _dataset_sample_batches(db, dataset_version_id, sample_ids):
    for sample_id_batch in _chunks(sample_ids):
        if not sample_id_batch:
            continue
        yield db.query(DatasetSample).filter(
            DatasetSample.dataset_version_id == dataset_version_id,
            DatasetSample.sample_id.in_(sample_id_batch),
        ).order_by(
            DatasetSample.row_index.asc(),
            DatasetSample.id.asc(),
        ).limit(len(sample_id_batch)).all()


def _source_rows_for_sample_ids(db, dataset_version_id, sample_ids):
    """Materialize one bounded source slice in frozen scope order."""
    source_rows = [
        row
        for batch in _dataset_sample_batches(db, dataset_version_id, sample_ids)
        for row in batch
    ]
    rows_by_id = {str(row.sample_id): row for row in source_rows}
    rows = {
        str(sample_id): (
            dict(rows_by_id[str(sample_id)].values or {})
            if str(sample_id) in rows_by_id else {}
        )
        for sample_id in sample_ids
    }
    return source_rows, rows_by_id, rows


def _existing_cluster_discovery_artifact(db, task_id, task_revision, config_hash):
    """Reuse frozen centers on a retry instead of fitting or searching again."""
    strategy_artifact = db.query(AnnotationStrategyArtifact).filter_by(
        task_id=task_id,
        task_revision=task_revision,
        config_hash=config_hash,
    ).one_or_none()
    if strategy_artifact is None:
        return None
    payload = dict(strategy_artifact.artifact or {})
    if payload.get("configuration_complete") is not False:
        return None
    cluster_payload = payload.get("cluster_artifact")
    if not isinstance(cluster_payload, dict):
        raise StrategyConfigError("cluster discovery artifact is invalid", "CLUSTER_ARTIFACT_INVALID")
    try:
        return cluster_artifact_from_payload(cluster_payload), cluster_payload
    except ValueError as error:
        raise StrategyConfigError("cluster discovery artifact is invalid", "CLUSTER_ARTIFACT_INVALID") from error


def _preview_sample_batches(db, preview_id):
    marker = None
    while True:
        query = db.query(AnnotationTaskPreviewSample).filter_by(preview_id=preview_id)
        if marker is not None:
            query = query.filter(or_(
                AnnotationTaskPreviewSample.sample_id > marker.sample_id,
                and_(
                    AnnotationTaskPreviewSample.sample_id == marker.sample_id,
                    AnnotationTaskPreviewSample.id > marker.id,
                ),
            ))
        rows = query.order_by(
            AnnotationTaskPreviewSample.sample_id.asc(),
            AnnotationTaskPreviewSample.id.asc(),
        ).limit(_PREVIEW_BATCH_SIZE).all()
        if not rows:
            return
        yield rows
        marker = rows[-1]


def enqueue_annotation_preview(task_id, preview_id, owner_id):
    """Dispatch through the same durable worker in local and Celery runtimes."""
    args = (str(task_id), str(preview_id), str(owner_id))
    if settings.task_backend == "celery":
        return execute_annotation_preview.delay(*args)
    threading.Thread(target=execute_annotation_preview.run, args=args, daemon=True).start()
    return SimpleNamespace(id=str(preview_id))


@celery_app.task(bind=True, name="ml_platform.execute_annotation_preview")
def execute_annotation_preview(self, task_id: str, preview_id: str, owner_id: str):
    task_uuid = uuid.UUID(task_id)
    preview_uuid = uuid.UUID(preview_id)
    owner_uuid = uuid.UUID(owner_id)
    session_factory = SessionLocal
    session_resource = session_factory()
    context_exit = None
    if not hasattr(session_resource, "query") and hasattr(session_resource, "__enter__"):
        db = session_resource.__enter__()
        context_exit = session_resource.__exit__
    else:
        db = session_resource
    # Tests inject a shared Session through a lambda; do not close that caller-owned
    # session. The production sessionmaker is always closed in the finally block.
    close_db = hasattr(session_factory, "kw")
    try:
        task = db.query(GenericAnnotationTask).filter_by(id=task_uuid, owner_id=owner_uuid).one_or_none()
        preview = db.query(AnnotationTaskPreview).filter_by(id=preview_uuid, task_id=task_uuid).one_or_none()
        if task is None or preview is None:
            return {"status": "not_found", "preview_id": preview_id}
        if preview.task_revision != task.task_revision:
            return {"status": "invalid_request", "preview_id": preview_id, "error": "PREVIEW_STALE"}
        operation_id = preview.operation_id
        worker_id = f"annotation-preview:{getattr(getattr(self, 'request', None), 'id', None) or preview_id}"
        try:
            if operation_id is None:
                raise ValueError("OPERATION_NOT_FOUND")
            if not claim_operation(db, operation_id, worker_id, 300):
                return {"status": "not_claimed", "preview_id": preview_id, "operation_id": str(operation_id) if operation_id else None}
            snapshot = current_annotation_task_snapshot(db, task)
            record_annotation_preview_progress(
                db,
                task_uuid,
                preview_uuid,
                owner_uuid,
                status="running",
                progress=10,
                summary={
                    "sample_scope_count": scope_count(
                        db,
                        task,
                        task_revision=preview.task_revision,
                        snapshot=snapshot,
                    ),
                    "visible_columns": snapshot.get("visible_columns", []),
                },
            )
            sample_scope_count = scope_count(
                db,
                task,
                task_revision=preview.task_revision,
                snapshot=snapshot,
            )

            def frozen_scope_batches():
                yield from iter_scope_batches(
                    db,
                    task,
                    task_revision=preview.task_revision,
                    snapshot=snapshot,
                    batch_size=_PREVIEW_BATCH_SIZE,
                )

            visible_columns = list(snapshot.get("visible_columns", []))
            summary = {
                "sample_count": sample_scope_count,
                "visible_columns": snapshot.get("visible_columns", []),
                "label_columns": [column.get("machine_key") for column in snapshot.get("label_schema", {}).get("columns", [])],
                "source_rows_found": 0,
            }
            strategy_artifact = None
            configuration = snapshot.get("configuration", {})
            if task.mode == "automatic":
                # Every automatic strategy advances source retrieval, model
                # inference, frozen decisions, and preview rows in the same
                # bounded source slices. Cluster discovery adds repeatable
                # read-only passes before this final assignment pass.
                heartbeat_operation(db, operation_id, worker_id, 300)
                model_package = None
                if configuration.get("model_artifact_id") is not None:
                    model_package = _artifact_model_package(
                        db,
                        task.project_id,
                        configuration.get("model_artifact_id"),
                    )

                cluster_discovery = bool(configuration.get("clustering")) and bool(
                    configuration.get("cluster_discovery")
                )
                frozen_cluster_artifact = None
                frozen_cluster_payload = None
                if cluster_discovery and model_package is not None:
                    existing = _existing_cluster_discovery_artifact(
                        db,
                        task.id,
                        preview.task_revision,
                        preview.config_hash,
                    )
                    if existing is not None:
                        frozen_cluster_artifact, frozen_cluster_payload = existing
                    else:
                        def cluster_source_batches():
                            for scope_batch in frozen_scope_batches():
                                sample_id_batch = [sample_id for sample_id, _ in scope_batch]
                                _, _, source_values = _source_rows_for_sample_ids(
                                    db,
                                    task.dataset_version_id,
                                    sample_id_batch,
                                )
                                yield tuple(sample_id_batch), pd.DataFrame.from_dict(source_values, orient="index")

                        try:
                            frozen_cluster_artifact, frozen_cluster_payload = (
                                build_streaming_cluster_artifact_from_package(
                                    model_package,
                                    cluster_source_batches,
                                    seed=int(configuration.get("random_seed", 42)),
                                    task_revision=preview.task_revision,
                                    total_sample_count=sample_scope_count,
                                    on_batch=lambda: heartbeat_operation(db, operation_id, worker_id, 300),
                                )
                            )
                        except StrategyConfigError:
                            raise
                        except (ValueError, TypeError, KeyError) as error:
                            code = str(error).split(":", 1)[0]
                            raise StrategyConfigError(
                                "weighted clustering cannot complete for this task range",
                                code if code.startswith(("CLUSTER_", "FEATURE_IMPORTANCE_")) else "CLUSTERING_FAILED",
                            ) from error

                needs_review_count = 0
                cluster_counts: dict[str, int] = {}
                for scope_batch in frozen_scope_batches():
                    sample_id_batch = [sample_id for sample_id, _ in scope_batch]
                    row_indexes = {sample_id: row_index for sample_id, row_index in scope_batch}
                    source_rows, rows_by_id, rows = _source_rows_for_sample_ids(
                        db,
                        task.dataset_version_id,
                        sample_id_batch,
                    )
                    summary["source_rows_found"] += len(source_rows)
                    strategy_kwargs = {"model_package": model_package}
                    if frozen_cluster_artifact is not None:
                        try:
                            cluster_ids = assign_clusters_from_artifact(
                                pd.DataFrame.from_dict(rows, orient="index"),
                                frozen_cluster_artifact,
                            )
                        except (ValueError, TypeError, KeyError) as error:
                            code = str(error).split(":", 1)[0]
                            raise StrategyConfigError(
                                "frozen cluster artifact cannot assign this preview batch",
                                code if code.startswith("CLUSTER_") else "CLUSTERING_FAILED",
                            ) from error
                        strategy_kwargs.update({
                            "precomputed_cluster_artifact": frozen_cluster_payload,
                            "precomputed_cluster_ids": {
                                sample_id: int(cluster_id)
                                for sample_id, cluster_id in zip(sample_id_batch, cluster_ids)
                            },
                        })
                    strategy_result = apply_preview_annotation_strategy(
                        db,
                        task_id=task.id,
                        task_revision=preview.task_revision,
                        config_hash=preview.config_hash,
                        actor_id=owner_uuid,
                        project_id=task.project_id,
                        schema_snapshot=snapshot.get("label_schema", {}),
                        configuration=configuration,
                        rows=rows,
                        row_indexes=row_indexes,
                        scope_sample_count=sample_scope_count,
                        **strategy_kwargs,
                    )
                    strategy_artifact = strategy_result.artifact
                    summary["strategy"] = strategy_artifact.strategy
                    summary["strategy_artifact_id"] = str(strategy_artifact.id)
                    strategy_payload = dict(strategy_artifact.artifact or {})
                    summary["configuration_complete"] = strategy_payload.get("configuration_complete", True)
                    summary["model_version_id"] = strategy_payload.get("model_version_id")
                    needs_review_count += sum(
                        decision.status == "needs_review"
                        for decision in strategy_result.decisions.values()
                    )
                    for decision in strategy_result.decisions.values():
                        if decision.cluster_id is not None:
                            key = str(decision.cluster_id)
                            cluster_counts[key] = cluster_counts.get(key, 0) + 1
                    existing_ids = {
                        item.sample_id
                        for item in db.query(AnnotationTaskPreviewSample).filter(
                            AnnotationTaskPreviewSample.preview_id == preview_uuid,
                            AnnotationTaskPreviewSample.sample_id.in_(sample_id_batch),
                        ).limit(len(sample_id_batch)).all()
                    }
                    for sample_id in sample_id_batch:
                        if sample_id in existing_ids:
                            continue
                        source_row = rows_by_id.get(sample_id)
                        source_values = dict(source_row.values or {}) if source_row is not None else {}
                        values = {column: source_values.get(column) for column in visible_columns} if visible_columns else source_values
                        decision = strategy_result.decisions.get(sample_id)
                        if decision is not None:
                            values["annotation_decision"] = {
                                "status": decision.status,
                                "values": decision.values,
                                "provenance": decision.provenance,
                                "model_output": decision.model_output,
                                "cluster_id": decision.cluster_id,
                                "matched_rule_ids": list(decision.matched_rule_ids),
                            }
                        db.add(AnnotationTaskPreviewSample(
                            preview_id=preview_uuid,
                            sample_id=sample_id,
                            row_index=row_indexes[sample_id],
                            values=values,
                        ))
                    db.flush()
                    heartbeat_operation(db, operation_id, worker_id, 300)
                summary["needs_review_count"] = needs_review_count
                summary["clusters"] = [
                    {
                        "cluster_id": int(cluster_id) if cluster_id.lstrip("-").isdigit() else cluster_id,
                        "sample_count": cluster_counts[cluster_id],
                    }
                    for cluster_id in sorted(cluster_counts, key=lambda value: (not value.lstrip("-").isdigit(), value))
                ]
            else:
                # Manual previews do not need a task-wide in-memory row map.
                # Read one source batch, materialize it, and release it before
                # loading the next batch.
                heartbeat_operation(db, operation_id, worker_id, 300)
                for scope_batch in frozen_scope_batches():
                    sample_id_batch = [sample_id for sample_id, _ in scope_batch]
                    row_indexes = {sample_id: row_index for sample_id, row_index in scope_batch}
                    source_rows, rows_by_id, _ = _source_rows_for_sample_ids(
                        db,
                        task.dataset_version_id,
                        sample_id_batch,
                    )
                    summary["source_rows_found"] += len(source_rows)
                    existing_ids = {
                        item.sample_id
                        for item in db.query(AnnotationTaskPreviewSample).filter(
                            AnnotationTaskPreviewSample.preview_id == preview_uuid,
                            AnnotationTaskPreviewSample.sample_id.in_(sample_id_batch),
                        ).limit(len(sample_id_batch)).all()
                    }
                    for sample_id in sample_id_batch:
                        if sample_id in existing_ids:
                            continue
                        source_row = rows_by_id.get(sample_id)
                        source_values = dict(source_row.values or {}) if source_row is not None else {}
                        values = {column: source_values.get(column) for column in visible_columns} if visible_columns else source_values
                        db.add(AnnotationTaskPreviewSample(
                            preview_id=preview_uuid,
                            sample_id=sample_id,
                            row_index=row_indexes[sample_id],
                            values=values,
                        ))
                    db.flush()
            digest = hashlib.sha256(json.dumps(
                {"preview_id": preview_id, "summary": summary},
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=True,
            ).encode())
            for batch in _preview_sample_batches(db, preview_uuid):
                for item in batch:
                    digest.update(b"\n")
                    digest.update(json.dumps(
                        (str(item.sample_id), item.values or {}),
                        sort_keys=True,
                        separators=(",", ":"),
                        ensure_ascii=True,
                    ).encode())
            checksum = "sha256:" + digest.hexdigest()
            record_annotation_preview_progress(
                db,
                task_uuid,
                preview_uuid,
                owner_uuid,
                status="completed",
                progress=100,
                summary=summary,
                commit=False,
            )
            mark_preview_completed(db, task_uuid, preview_uuid, owner_uuid, commit=False)
            complete_operation(db, operation_id, worker_id, preview_uuid, checksum)
            return {"status": "completed", "preview_id": preview_id, "operation_id": str(preview.operation_id)}
        except Exception as error:
            db.rollback()
            current = db.query(AnnotationTaskPreview).filter_by(id=preview_uuid, task_id=task_uuid).one_or_none()
            failed_task = db.query(GenericAnnotationTask).filter_by(id=task_uuid, owner_id=owner_uuid).one_or_none()
            lease_owned = True
            if current is not None and failed_task is not None and current.task_revision == failed_task.task_revision:
                try:
                    error_code = error.code if isinstance(error, StrategyConfigError) else "PREVIEW_EXECUTION_FAILED"
                    if operation_id is not None:
                        fail_operation(
                            db,
                            operation_id,
                            error_code,
                            {"message": str(error)[:300]},
                            worker_id=worker_id,
                        )
                except ValueError:
                    lease_owned = False
                if lease_owned or str(error) == "OPERATION_NOT_FOUND":
                    current.status = "failed"
                    current.progress = (
                        int(current.progress or 0)
                        if str(error) == "OPERATION_NOT_FOUND"
                        else max(int(current.progress or 0), 10)
                    )
                    current.error = {"code": error_code, "message": str(error)[:500]}
                    if failed_task.status == "previewing":
                        failed_task.status = "failed"
                    db.commit()
            return {"status": "failed", "preview_id": preview_id, "error": current.error if current is not None else None}
    finally:
        if context_exit is not None:
            context_exit(None, None, None)
        elif close_db:
            db.close()
