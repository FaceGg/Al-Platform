from datetime import datetime, timedelta, timezone
from pathlib import Path
import json
import uuid
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models.operation import DurableOperation
from app.models.platform_models import AnnotationTaskPreview, AnnotationTaskPreviewSample, GenericAnnotationTask
from app.models.project import Project
from app.models.user import User
from app.models.data_version import DatasetVersion
from app.models.labeling import LabelSchema
from app.services.annotation_task_state import create_annotation_preview
from app.services.operation_lifecycle import (
    cleanup_orphan_artifacts,
    claim_operation,
    complete_operation,
    fail_operation,
    recover_expired_operations,
    heartbeat_operation,
    write_cleanup_report,
    claim_operation_dispatch,
)
from app.tasks.celery_app import celery_app
from app.tasks.annotation_preview_tasks import execute_annotation_preview
from app.tasks import recovery as recovery_tasks
from tools.cleanup_acceptance import validate_cleanup_report
from app.storage.local import LocalStorage


class _SessionContext:
    def __init__(self, session): self.session = session
    def __enter__(self): return self.session
    def __exit__(self, *_): return False


@pytest.fixture()
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, expire_on_commit=False)()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def _operation(db, resource_key: str | None = None):
    operation = DurableOperation(
        resource_key=resource_key or f"preview:{uuid.uuid4()}",
        idempotency_key=f"key-{uuid.uuid4()}",
        state="queued",
        stage="queued",
    )
    db.add(operation)
    db.commit()
    return operation


def test_expired_lease_can_be_reclaimed_once(db):
    operation = _operation(db)
    assert claim_operation(db, operation.id, "worker-a", 30) is True
    assert claim_operation(db, operation.id, "worker-b", 30) is False

    operation.lease_expires_at = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(seconds=1)
    db.commit()

    assert claim_operation(db, operation.id, "worker-b", 30) is True
    assert db.get(DurableOperation, operation.id).attempt == 2


def test_recovery_reclaims_only_expired_operations_and_returns_ids(db):
    expired = _operation(db)
    live = _operation(db)
    assert claim_operation(db, expired.id, "worker-a", 30) is True
    assert claim_operation(db, live.id, "worker-a", 30) is True
    expired.lease_expires_at = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(seconds=1)
    db.commit()

    recovered = recover_expired_operations(db, worker_id="recovery-worker", lease_seconds=30)

    assert recovered == (str(expired.id),)
    assert db.get(DurableOperation, expired.id).lease_owner == "recovery-worker"
    assert db.get(DurableOperation, live.id).lease_owner == "worker-a"


def test_celery_registers_generic_recovery_task_and_beat_schedule():
    assert "app.tasks.recovery" in celery_app.conf.include
    assert "ml_platform.recover_operations" in celery_app.tasks
    assert celery_app.conf.beat_schedule["durable-operation-recovery"]["task"] == "ml_platform.recover_operations"


def test_celery_registers_generic_execution_task():
    assert "app.tasks.annotation_execution_tasks" in celery_app.conf.include
    assert "ml_platform.execute_annotation_task" in celery_app.tasks


def test_cleanup_acceptance_validates_current_sha_and_passed_report(tmp_path: Path):
    report = tmp_path / "cleanup.json"
    report.write_text(
        json.dumps(
            {
                "status": "passed",
                "scanned": 2,
                "removed": 1,
                "retained_committed": 1,
                "errors": [],
                "ttl_seconds": 3600,
                "source_commit": "a" * 40,
            }
        ),
        encoding="utf-8",
    )

    assert validate_cleanup_report(report, "a" * 40)["source_commit"] == "a" * 40
    with pytest.raises(ValueError, match="CLEANUP_REPORT_SHA_MISMATCH"):
        validate_cleanup_report(report, "b" * 40)
    report.write_text(report.read_text(encoding="utf-8").replace('"status": "passed"', '"status": "failed"'), encoding="utf-8")
    with pytest.raises(ValueError, match="CLEANUP_REPORT_NOT_PASSED"):
        validate_cleanup_report(report, "a" * 40)


def test_heartbeat_and_failure_keep_partial_result_unpublished(db):
    operation = _operation(db)
    assert claim_operation(db, operation.id, "worker-a", 30) is True
    heartbeat_operation(db, operation.id, "worker-a", 30)
    fail_operation(db, operation.id, "MODEL_EXPORT_FAILED", {"token": "redacted"})

    persisted = db.get(DurableOperation, operation.id)
    assert persisted.state == "failed"
    assert persisted.result_artifact_id is None
    assert persisted.error_code == "MODEL_EXPORT_FAILED"
    assert persisted.error_details == {"token": "[redacted]"}


def test_complete_operation_requires_current_lease_owner(db):
    operation = _operation(db)
    assert claim_operation(db, operation.id, "worker-a", 30) is True
    with pytest.raises(ValueError, match="OPERATION_LEASE_NOT_OWNED"):
        complete_operation(db, operation.id, "worker-b", uuid.uuid4(), "sha256:" + "a" * 64)

    complete_operation(db, operation.id, "worker-a", uuid.uuid4(), "sha256:" + "a" * 64)
    persisted = db.get(DurableOperation, operation.id)
    assert persisted.state == "completed"
    assert persisted.checksum == "sha256:" + "a" * 64


def test_cleanup_removes_only_old_uncommitted_local_artifacts_and_writes_receipt(db, tmp_path: Path):
    storage = LocalStorage(tmp_path / "artifacts")
    committed = storage.base_dir / "project" / "artifact" / "committed.bin"
    abandoned = storage.base_dir / "project" / "artifact" / ".abandoned.tmp"
    committed.parent.mkdir(parents=True)
    committed.write_bytes(b"committed")
    abandoned.write_bytes(b"abandoned")
    old = datetime.now(timezone.utc).timestamp() - 7200
    import os
    os.utime(committed, (old, old))
    os.utime(abandoned, (old, old))

    report = cleanup_orphan_artifacts(storage, timedelta(seconds=3600), committed_paths=[committed])
    assert report.status == "passed"
    assert report.removed == 1
    assert report.retained_committed == 1
    assert committed.exists()
    assert not abandoned.exists()

    output = write_cleanup_report(storage, tmp_path / "cleanup.json", timedelta(seconds=3600), "a" * 40, committed_paths=[committed])
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["source_commit"] == "a" * 40
    assert set(payload) >= {"status", "scanned", "removed", "retained_committed", "errors", "ttl_seconds", "source_commit"}


def test_preview_creation_persists_matching_durable_operation(db):
    user = User(username=f"operation-owner-{uuid.uuid4().hex}", password_hash="hash")
    db.add(user)
    db.flush()
    project = Project(name="operation-project", owner_id=user.id)
    db.add(project)
    db.flush()
    version = DatasetVersion(
        project_id=project.id,
        operator_id=user.id,
        version=1,
        row_count=0,
        column_count=0,
        content_hash="sha256:operation-data",
        schema_hash="sha256:operation-schema",
    )
    schema = LabelSchema(project_id=project.id, name="operation-labels", version=1, status="active")
    db.add_all([version, schema])
    db.flush()
    task = GenericAnnotationTask(
        project_id=project.id,
        dataset_version_id=version.id,
        label_schema_id=schema.id,
        owner_id=user.id,
        mode="manual",
        status="draft",
        task_revision=0,
        task_snapshot={"sample_ids": []},
    )
    db.add(task)
    db.commit()

    preview = create_annotation_preview(db, task.id, 0, "sha256:operation-config", user.id)
    operation = db.get(DurableOperation, preview.operation_id)

    assert operation is not None
    assert operation.resource_key == f"annotation-preview:{preview.id}"
    assert operation.idempotency_key == "sha256:operation-config"
    assert operation.state == "queued"


def test_preview_worker_claims_and_completes_durable_operation(db, monkeypatch):
    user = User(username=f"preview-worker-{uuid.uuid4().hex}", password_hash="hash")
    db.add(user); db.flush()
    project = Project(name="preview-worker-project", owner_id=user.id)
    db.add(project); db.flush()
    version = DatasetVersion(project_id=project.id, operator_id=user.id, version=1, row_count=0, column_count=0, content_hash="sha256:w", schema_hash="sha256:s")
    schema = LabelSchema(project_id=project.id, name="labels", version=1, status="active")
    db.add_all([version, schema]); db.flush()
    task = GenericAnnotationTask(project_id=project.id, dataset_version_id=version.id, label_schema_id=schema.id, owner_id=user.id, mode="manual", status="draft", task_revision=0, task_snapshot={"sample_ids": []})
    db.add(task); db.commit()
    preview = create_annotation_preview(db, task.id, 0, "sha256:worker-lifecycle", user.id)
    monkeypatch.setattr("app.tasks.annotation_preview_tasks.SessionLocal", lambda: db)
    result = execute_annotation_preview.run(str(task.id), str(preview.id), str(user.id))
    operation = db.get(DurableOperation, preview.operation_id)
    assert result["status"] == "completed"
    assert operation.state == "completed"
    assert operation.progress == 100
    assert operation.checksum and operation.checksum.startswith("sha256:")
    repeat = execute_annotation_preview.run(str(task.id), str(preview.id), str(user.id))
    assert repeat["status"] == "not_claimed"
    assert db.get(DurableOperation, preview.operation_id).checksum == operation.checksum


def test_preview_worker_failure_fails_operation_without_publishing_samples(db, monkeypatch):
    user = User(username=f"preview-fail-{uuid.uuid4().hex}", password_hash="hash")
    db.add(user); db.flush()
    project = Project(name="preview-fail-project", owner_id=user.id)
    db.add(project); db.flush()
    version = DatasetVersion(project_id=project.id, operator_id=user.id, version=1, row_count=0, column_count=0, content_hash="sha256:w2", schema_hash="sha256:s2")
    schema = LabelSchema(project_id=project.id, name="labels", version=1, status="active")
    db.add_all([version, schema]); db.flush()
    task = GenericAnnotationTask(project_id=project.id, dataset_version_id=version.id, label_schema_id=schema.id, owner_id=user.id, mode="manual", status="draft", task_revision=0, task_snapshot={"sample_ids": ["x"]})
    db.add(task); db.commit()
    preview = create_annotation_preview(db, task.id, 0, "sha256:worker-failure", user.id)
    monkeypatch.setattr("app.tasks.annotation_preview_tasks.SessionLocal", lambda: db)
    monkeypatch.setattr("app.tasks.annotation_preview_tasks.DatasetSample", None)
    result = execute_annotation_preview.run(str(task.id), str(preview.id), str(user.id))
    operation = db.get(DurableOperation, preview.operation_id)
    assert result["status"] == "failed"
    assert operation.state == "failed"
    assert db.query(AnnotationTaskPreviewSample).filter_by(preview_id=preview.id).count() == 0


def test_fail_operation_cannot_downgrade_completed_operation(db):
    operation = _operation(db)
    assert claim_operation(db, operation.id, "worker-a", 30) is True
    complete_operation(db, operation.id, "worker-a", uuid.uuid4(), "sha256:" + "b" * 64)
    with pytest.raises(ValueError, match="OPERATION_LEASE_NOT_OWNED"):
        fail_operation(db, operation.id, "PREVIEW_EXECUTION_FAILED", worker_id="worker-a")
    assert db.get(DurableOperation, operation.id).state == "completed"


def test_recover_operations_requeues_queued_and_expired_preview(monkeypatch, db):
    user = User(username=f"preview-recovery-{uuid.uuid4().hex}", password_hash="hash")
    db.add(user); db.flush()
    project = Project(name="preview-recovery-project", owner_id=user.id)
    db.add(project); db.flush()
    version = DatasetVersion(project_id=project.id, operator_id=user.id, version=1, row_count=0, column_count=0, content_hash="sha256:w3", schema_hash="sha256:s3")
    schema = LabelSchema(project_id=project.id, name="labels", version=1, status="active")
    db.add_all([version, schema]); db.flush()
    task = GenericAnnotationTask(project_id=project.id, dataset_version_id=version.id, label_schema_id=schema.id, owner_id=user.id, mode="manual", status="draft", task_revision=0, task_snapshot={"sample_ids": []})
    db.add(task); db.commit()
    queued = create_annotation_preview(db, task.id, 0, "sha256:recovery-queued", user.id)
    task.task_revision = 1; db.commit()
    expired_preview = create_annotation_preview(db, task.id, 1, "sha256:recovery-expired", user.id)
    expired_op = db.get(DurableOperation, expired_preview.operation_id)
    from datetime import datetime, timedelta
    expired_op.state = "running"; expired_op.lease_owner = "old-worker"; expired_op.lease_expires_at = datetime.utcnow() - timedelta(seconds=1); db.commit()
    dispatched = []
    monkeypatch.setattr(recovery_tasks, "enqueue_annotation_preview", lambda *args: dispatched.append(args) or SimpleNamespace(id="dispatch"))
    monkeypatch.setattr(recovery_tasks, "SessionLocal", lambda: _SessionContext(db))
    result = recovery_tasks.recover_operations()
    assert result["count"] == 2
    assert {str(args[1]) for args in dispatched} == {str(queued.id), str(expired_preview.id)}
    assert {str(args[2]) for args in dispatched} == {str(user.id)}


def test_recover_operations_requeues_queued_execution(monkeypatch, db):
    user = User(username=f"execution-recovery-{uuid.uuid4().hex}", password_hash="hash")
    db.add(user); db.flush()
    project = Project(name="execution-recovery-project", owner_id=user.id)
    db.add(project); db.flush()
    version = DatasetVersion(project_id=project.id, operator_id=user.id, version=1, row_count=0, column_count=0, content_hash="sha256:w4", schema_hash="sha256:s4")
    schema = LabelSchema(project_id=project.id, name="labels", version=1, status="active")
    db.add_all([version, schema]); db.flush()
    task = GenericAnnotationTask(project_id=project.id, dataset_version_id=version.id, label_schema_id=schema.id, owner_id=user.id, mode="automatic", status="preview_ready", task_revision=0, task_snapshot={"sample_ids": []})
    db.add(task); db.commit()
    preview = create_annotation_preview(db, task.id, 0, "sha256:execution-recovery", user.id)
    preview.status = "completed"; preview.progress = 100; task.status = "preview_ready"; db.commit()
    db.get(DurableOperation, preview.operation_id).state = "completed"; db.commit()
    from app.services.annotation_task_execution import request_annotation_execution
    requested = request_annotation_execution(db, task.id, preview.id, user.id)
    dispatched = []
    monkeypatch.setattr(recovery_tasks, "enqueue_annotation_preview", lambda *args: dispatched.append(("preview", args)) or SimpleNamespace(id="preview-dispatch"))
    monkeypatch.setattr(recovery_tasks, "enqueue_annotation_execution", lambda *args: dispatched.append(("execution", args)) or SimpleNamespace(id="execution-dispatch"))
    monkeypatch.setattr(recovery_tasks, "SessionLocal", lambda: _SessionContext(db))
    result = recovery_tasks.recover_operations()
    assert result["count"] == 1
    assert dispatched == [("execution", (task.id, preview.id, requested.operation_id, task.owner_id))]


def test_recovery_does_not_redispatch_execution_marked_dispatched(monkeypatch, db):
    user = User(username=f"execution-recovery-dedupe-{uuid.uuid4().hex}", password_hash="hash")
    db.add(user); db.flush()
    project = Project(name="execution-recovery-dedupe-project", owner_id=user.id)
    version = DatasetVersion(project_id=project.id, operator_id=user.id, version=1, row_count=0, column_count=0, content_hash="sha256:w5", schema_hash="sha256:s5")
    schema = LabelSchema(project_id=project.id, name="labels", version=1, status="active")
    db.add(project); db.flush()
    version.project_id = project.id
    schema.project_id = project.id
    db.add_all([version, schema]); db.flush()
    task = GenericAnnotationTask(project_id=project.id, dataset_version_id=version.id, label_schema_id=schema.id, owner_id=user.id, mode="automatic", status="preview_ready", task_revision=0, task_snapshot={"sample_ids": []})
    db.add(task); db.commit()
    preview = create_annotation_preview(db, task.id, 0, "sha256:execution-recovery-dedupe", user.id)
    preview.status = "completed"; preview.progress = 100; task.status = "preview_ready"; db.commit()
    db.get(DurableOperation, preview.operation_id).state = "completed"; db.commit()
    from app.services.annotation_task_execution import request_annotation_execution
    requested = request_annotation_execution(db, task.id, preview.id, user.id)
    dispatched = []
    monkeypatch.setattr(recovery_tasks, "enqueue_annotation_execution", lambda *args: dispatched.append(args) or SimpleNamespace(id="execution-dispatch"))
    monkeypatch.setattr(recovery_tasks, "SessionLocal", lambda: _SessionContext(db))

    assert recovery_tasks.recover_operations()["count"] == 1
    assert recovery_tasks.recover_operations()["count"] == 0
    assert dispatched == [(task.id, preview.id, requested.operation_id, task.owner_id)]


def test_recovery_skips_failed_execution_operation(monkeypatch, db):
    operation = _operation(db, resource_key=f"annotation-execution:{uuid.uuid4()}")
    operation.state = "failed"
    operation.error_code = "ANNOTATION_EXECUTION_INVALID"
    db.commit()
    dispatched = []
    monkeypatch.setattr(recovery_tasks, "enqueue_annotation_execution", lambda *args: dispatched.append(args) or SimpleNamespace(id="execution-dispatch"))
    monkeypatch.setattr(recovery_tasks, "SessionLocal", lambda: _SessionContext(db))

    assert recovery_tasks.recover_operations()["count"] == 0
    assert dispatched == []


def test_operation_dispatch_claim_is_atomic_and_recoverable(db):
    operation = _operation(db, resource_key=f"annotation-execution:{uuid.uuid4()}")

    assert claim_operation_dispatch(db, operation.id, 30) is True


@pytest.mark.parametrize("state", ["failed", "cancelled"])
def test_terminal_operation_cannot_be_claimed(db, state):
    operation = _operation(db)
    operation.state = state
    db.commit()
    assert claim_operation(db, operation.id, "late-worker", 30) is False
    assert operation.state == state


def test_expired_worker_cannot_fail_operation(db):
    operation = _operation(db)
    claim_operation(db, operation.id, "old-worker", 30)
    operation.lease_expires_at = datetime.utcnow() - timedelta(seconds=1)
    db.commit()
    with pytest.raises(ValueError, match="OPERATION_LEASE_NOT_OWNED"):
        fail_operation(db, operation.id, "LATE_FAILURE", worker_id="old-worker")
    db.refresh(operation)
    assert operation.state == "running"
    assert claim_operation_dispatch(db, operation.id, 30) is False

    persisted = db.get(DurableOperation, operation.id)
    persisted.heartbeat_at = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(seconds=31)
    db.commit()
    assert claim_operation_dispatch(db, operation.id, 30) is True
