import uuid
from datetime import datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models.labeling import LabelColumn, LabelSchema
from app.models.access import AuditEvent
from app.models.platform_models import AnnotationTaskPreview, GenericAnnotationTask
from app.models.project import Project
from app.models.user import User
from app.schemas.annotation_tasks import TaskAction
from app.services.annotation_task_state import (
    create_annotation_preview,
    list_annotation_tasks,
    transition_annotation_task,
)


@pytest.fixture()
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, expire_on_commit=False)()
    yield session
    session.close()
    engine.dispose()


def _task(db):
    user = User(username=f"task-{uuid.uuid4().hex}", password_hash="hash")
    db.add(user)
    db.flush()
    project = Project(name="Task project", owner_id=user.id)
    db.add(project)
    db.flush()
    schema = LabelSchema(project_id=project.id, name="labels", version=1, status="active")
    db.add(schema)
    db.flush()
    db.add(LabelColumn(schema_id=schema.id, machine_key="label", display_name="Label", ordinal=0, value_type="string"))
    task = GenericAnnotationTask(
        project_id=project.id,
        dataset_version_id=uuid.uuid4(),
        label_schema_id=schema.id,
        owner_id=user.id,
        mode="manual",
        status="draft",
        task_revision=0,
        sample_scope={"kind": "all"},
        label_snapshot={"columns": ["label"]},
        task_snapshot={"config_hash": "sha256:frozen", "sample_ids": ["s-1", "s-2"], "visible_columns": ["feature"], "label_schema": {"columns": [{"machine_key": "label"}]}},
    )
    db.add(task)
    db.commit()
    return task, user, project


def test_manual_task_publish_requires_preview_ready(db):
    task, user, _ = _task(db)
    with pytest.raises(ValueError, match="TASK_STATE_INVALID"):
        transition_annotation_task(db, task.id, expected_revision=0, action=TaskAction.publish, actor_id=user.id)


def test_preview_reuses_same_operation_for_same_config_hash(db):
    task, user, _ = _task(db)
    first = create_annotation_preview(db, task.id, task_revision=0, config_hash="sha256:abc", actor_id=user.id)
    second = create_annotation_preview(db, task.id, task_revision=0, config_hash="sha256:abc", actor_id=user.id)
    assert first.operation_id == second.operation_id
    assert db.query(AnnotationTaskPreview).count() == 1


def test_automatic_task_execution_requires_valid_preview(db):
    task, user, _ = _task(db)
    with pytest.raises(ValueError, match="PREVIEW_STALE"):
        transition_annotation_task(db, task.id, expected_revision=0, action=TaskAction.execute, actor_id=user.id, preview_id=uuid.uuid4())


def test_list_annotation_tasks_uses_cursor_and_limit(db):
    task, user, project = _task(db)
    page = list_annotation_tasks(db, project.id, owner_id=user.id, cursor=None, limit=1)
    assert page["total"] == 1
    assert page["items"][0]["id"] == str(task.id)
    assert page["next_cursor"] is None


def test_transition_records_audit_event(db):
    task, user, project = _task(db)
    create_annotation_preview(db, task.id, task_revision=0, config_hash="sha256:audit", actor_id=user.id)
    transition_annotation_task(db, task.id, expected_revision=0, action=TaskAction.publish, actor_id=user.id)
    event = db.query(AuditEvent).filter(AuditEvent.resource_id == str(task.id), AuditEvent.action == "annotation_task.transition").one()
    assert event.project_id == project.id
    assert event.actor_id == user.id
    assert event.result == "success"
    assert event.changes["from_status"] == "preview_ready"
    assert event.changes["to_status"] == "awaiting_annotation"


def test_preview_list_uses_cursor(db):
    task, user, _ = _task(db)
    first = create_annotation_preview(db, task.id, task_revision=0, config_hash="sha256:first", actor_id=user.id)
    task.task_revision = 1
    db.commit()
    second = create_annotation_preview(db, task.id, task_revision=1, config_hash="sha256:second", actor_id=user.id)
    from app.services.annotation_task_state import list_annotation_previews
    page = list_annotation_previews(db, task.id, owner_id=user.id, cursor=None, limit=1)
    assert page["next_cursor"] is not None
    assert len(page["items"]) == 1
    next_page = list_annotation_previews(db, task.id, owner_id=user.id, cursor=page["next_cursor"], limit=1)
    assert len(next_page["items"]) == 1
    assert next_page["items"][0]["id"] != page["items"][0]["id"]


def test_preview_list_rejects_non_owner(db):
    task, user, _ = _task(db)
    other = User(username=f"other-{uuid.uuid4().hex}", password_hash="hash")
    db.add(other)
    db.commit()
    from app.services.annotation_task_state import list_annotation_previews
    with pytest.raises(ValueError, match="TASK_NOT_FOUND"):
        list_annotation_previews(db, task.id, owner_id=other.id, cursor=None, limit=10)


def test_task_snapshot_is_immutable(db):
    task, user, _ = _task(db)
    task.task_snapshot = {"config_hash": "sha256:changed"}
    with pytest.raises(ValueError, match="snapshot is immutable"):
        db.commit()
    db.rollback()


def test_preview_progress_is_monotonic_and_records_completion(db):
    task, user, _ = _task(db)
    preview = create_annotation_preview(db, task.id, task_revision=0, config_hash="sha256:progress", actor_id=user.id)
    from app.services.annotation_task_state import record_annotation_preview_progress
    updated = record_annotation_preview_progress(db, task.id, preview.id, user.id, status="running", progress=40, summary={"sample_count": 2})
    assert updated.progress == 40
    assert updated.status == "running"
    completed = record_annotation_preview_progress(db, task.id, preview.id, user.id, status="completed", progress=100, summary={"sample_count": 2})
    assert completed.completed_at is not None
    assert completed.status == "completed"
    with pytest.raises(ValueError, match="PREVIEW_PROGRESS_REGRESSION"):
        record_annotation_preview_progress(db, task.id, preview.id, user.id, status="running", progress=50, summary={})


def test_preview_worker_materializes_snapshot_summary(db, monkeypatch):
    task, user, _ = _task(db)
    preview = create_annotation_preview(db, task.id, task_revision=0, config_hash="sha256:worker", actor_id=user.id)
    from app.tasks.annotation_preview_tasks import execute_annotation_preview
    monkeypatch.setattr("app.tasks.annotation_preview_tasks.SessionLocal", lambda: db)
    result = execute_annotation_preview.run(str(task.id), str(preview.id), str(user.id))
    assert result["status"] == "completed"
    assert preview.progress == 100
    assert preview.summary["sample_count"] == 2
    assert preview.summary["label_columns"] == ["label"]
