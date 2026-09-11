import uuid
from datetime import datetime

import joblib
import numpy as np
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models.labeling import AnnotationStrategyArtifact, LabelColumn, LabelSchema
from app.models.artifact import Artifact
from app.models.access import AuditEvent
from app.models.operation import DurableOperation
from app.models.platform_models import AnnotationTaskExecutionResult, AnnotationTaskPreview, AnnotationTaskPreviewSample, GenericAnnotationTask
from app.models.project import Project
from app.models.user import User
from app.schemas.annotation_tasks import TaskAction
from app.services.annotation_task_state import (
    create_annotation_preview,
    list_annotation_tasks,
    transition_annotation_task,
)


class _SessionContext:
    def __init__(self, session):
        self.session = session

    def __enter__(self):
        return self.session

    def __exit__(self, *_):
        return False


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


def test_all_project_task_api_paginates_without_losing_owner_scope(db):
    from fastapi.testclient import TestClient
    from app.api.auth import get_current_user
    from app.database import get_db
    from app.main import app

    first, user, project = _task(db)
    second, _, _ = _task(db)
    second.owner_id = user.id
    foreign, _, _ = _task(db)
    db.commit()
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: user
    try:
        client = TestClient(app)
        page = client.get("/api/annotation-tasks", params={"limit": 1})
        assert page.status_code == 200
        assert page.json()["total"] == 2
        assert page.json()["next_cursor"]
        next_page = client.get("/api/annotation-tasks", params={"limit": 1, "cursor": page.json()["next_cursor"]})
        assert next_page.status_code == 200
        assert next_page.json()["total"] == 2
        assert len(next_page.json()["items"]) == 1
        assert {item["id"] for item in page.json()["items"] + next_page.json()["items"]} == {str(first.id), str(second.id)}
        for cursor in ("not-a-uuid", str(foreign.id)):
            response = client.get("/api/annotation-tasks", params={"cursor": cursor})
            assert response.status_code == 422
            assert response.json()["detail"]["code"] == "INVALID_CURSOR"
        wrong_project = client.get("/api/annotation-tasks", params={"project_id": str(project.id), "cursor": str(second.id)})
        assert wrong_project.status_code == 422
    finally:
        app.dependency_overrides.clear()


def test_preview_reuses_same_operation_for_same_config_hash(db):
    task, user, _ = _task(db)
    first = create_annotation_preview(db, task.id, task_revision=0, config_hash="sha256:abc", actor_id=user.id)
    second = create_annotation_preview(db, task.id, task_revision=0, config_hash="sha256:abc", actor_id=user.id)
    assert first.operation_id == second.operation_id
    assert db.query(AnnotationTaskPreview).count() == 1


def test_preview_is_previewing_until_worker_finishes(db, monkeypatch):
    task, user, _ = _task(db)
    preview = create_annotation_preview(db, task.id, task_revision=0, config_hash="sha256:lifecycle", actor_id=user.id)
    assert task.status == "previewing"
    from app.tasks.annotation_preview_tasks import execute_annotation_preview
    monkeypatch.setattr("app.tasks.annotation_preview_tasks.SessionLocal", lambda: _SessionContext(db))
    execute_annotation_preview.run(str(task.id), str(preview.id), str(user.id))
    assert task.status == "preview_ready"


def test_automatic_task_execution_requires_valid_preview(db):
    task, user, _ = _task(db)
    with pytest.raises(ValueError, match="PREVIEW_STALE"):
        transition_annotation_task(db, task.id, expected_revision=0, action=TaskAction.execute, actor_id=user.id, preview_id=uuid.uuid4())


def test_execute_request_creates_idempotent_durable_operation(db):
    task, user, _ = _task(db)
    preview = create_annotation_preview(db, task.id, task_revision=0, config_hash="sha256:execute-contract", actor_id=user.id)
    preview.status = "completed"
    preview.progress = 100
    task.status = "preview_ready"
    db.commit()

    from app.services.annotation_task_execution import request_annotation_execution

    first = request_annotation_execution(db, task.id, preview.id, user.id)
    second = request_annotation_execution(db, task.id, preview.id, user.id)

    assert first.operation_id == second.operation_id
    operation = db.get(DurableOperation, first.operation_id)
    assert operation is not None
    assert operation.resource_key == f"annotation-execution:{task.id}"
    assert operation.idempotency_key == f"0:{preview.id}"
    assert operation.state == "queued"
    assert task.status == "executing"


def test_execute_worker_persists_results_and_is_repeatable(db, monkeypatch):
    task, user, _ = _task(db)
    preview = create_annotation_preview(db, task.id, task_revision=0, config_hash="sha256:execute-worker", actor_id=user.id)
    preview.status = "completed"
    preview.progress = 100
    preview.summary = {"sample_count": 2}
    db.add_all([
        AnnotationTaskPreviewSample(preview_id=preview.id, sample_id="s-1", row_index=0, values={"label": "a"}),
        AnnotationTaskPreviewSample(preview_id=preview.id, sample_id="s-2", row_index=1, values={"label": "b"}),
    ])
    task.status = "preview_ready"
    db.commit()

    from app.services.annotation_task_execution import request_annotation_execution
    from app.tasks.annotation_execution_tasks import execute_annotation_task

    requested = request_annotation_execution(db, task.id, preview.id, user.id)
    monkeypatch.setattr("app.tasks.annotation_execution_tasks.SessionLocal", lambda: db)
    result = execute_annotation_task.run(str(task.id), str(requested.preview_id), str(user.id), str(requested.operation_id))

    assert result["status"] == "completed"
    assert db.query(AnnotationTaskExecutionResult).filter_by(operation_id=requested.operation_id).count() == 2
    operation = db.get(DurableOperation, requested.operation_id)
    assert operation.state == "completed"
    assert operation.checksum and operation.checksum.startswith("sha256:")
    assert db.get(GenericAnnotationTask, task.id).status == "awaiting_annotation"

    repeat = execute_annotation_task.run(str(task.id), str(requested.preview_id), str(user.id), str(requested.operation_id))
    assert repeat["status"] == "not_claimed"
    assert db.query(AnnotationTaskExecutionResult).filter_by(operation_id=requested.operation_id).count() == 2


def test_execution_results_are_cursor_paginated_and_owner_scoped(db, monkeypatch):
    task, user, _ = _task(db)
    preview = create_annotation_preview(db, task.id, task_revision=0, config_hash="sha256:execute-page", actor_id=user.id)
    preview.status = "completed"
    preview.progress = 100
    db.add_all([
        AnnotationTaskPreviewSample(preview_id=preview.id, sample_id="s-1", row_index=0, values={"annotation_decision": {"values": {"label": "a"}, "cluster_id": 1}}),
        AnnotationTaskPreviewSample(preview_id=preview.id, sample_id="s-2", row_index=1, values={"annotation_decision": {"values": {"label": "b"}, "matched_rule_ids": ["r-1"]}}),
    ])
    task.status = "preview_ready"
    db.commit()

    from app.services.annotation_task_execution import request_annotation_execution
    from app.tasks.annotation_execution_tasks import execute_annotation_task
    requested = request_annotation_execution(db, task.id, preview.id, user.id)
    monkeypatch.setattr("app.tasks.annotation_execution_tasks.SessionLocal", lambda: db)
    execute_annotation_task.run(str(task.id), str(preview.id), str(user.id), str(requested.operation_id))

    from app.services.annotation_task_state import list_annotation_execution_results
    first = list_annotation_execution_results(db, task.id, requested.operation_id, user.id, limit=1)
    assert first["total"] == 2
    assert first["next_cursor"]
    assert first["items"][0]["sample_id"] == "s-1"
    second = list_annotation_execution_results(db, task.id, requested.operation_id, user.id, cursor=first["next_cursor"], limit=1)
    assert second["items"][0]["sample_id"] == "s-2"
    other = User(username=f"execution-page-other-{uuid.uuid4().hex}", password_hash="hash")
    db.add(other)
    db.commit()
    with pytest.raises(ValueError, match="TASK_NOT_FOUND"):
        list_annotation_execution_results(db, task.id, requested.operation_id, other.id, limit=1)


def test_execution_stats_are_persisted_and_cursor_paginated(db, monkeypatch):
    task, user, _ = _task(db)
    preview = create_annotation_preview(db, task.id, task_revision=0, config_hash="sha256:execute-stats", actor_id=user.id)
    preview.status = "completed"
    preview.progress = 100
    db.add_all([
        AnnotationTaskPreviewSample(preview_id=preview.id, sample_id="s-1", row_index=0, values={"annotation_decision": {"values": {"label": "a"}, "cluster_id": 1, "matched_rule_ids": ["r-1"]}}),
        AnnotationTaskPreviewSample(preview_id=preview.id, sample_id="s-2", row_index=1, values={"annotation_decision": {"values": {"label": "a"}, "cluster_id": 1, "matched_rule_ids": ["r-1", "r-2"]}}),
    ])
    task.status = "preview_ready"
    db.commit()

    from app.services.annotation_task_execution import request_annotation_execution
    from app.tasks.annotation_execution_tasks import execute_annotation_task
    requested = request_annotation_execution(db, task.id, preview.id, user.id)
    monkeypatch.setattr("app.tasks.annotation_execution_tasks.SessionLocal", lambda: db)
    execute_annotation_task.run(str(task.id), str(preview.id), str(user.id), str(requested.operation_id))

    from app.services.annotation_task_state import list_annotation_execution_stats
    clusters = list_annotation_execution_stats(db, task.id, requested.operation_id, user.id, kind="cluster", limit=10)
    assert clusters["items"] == [{"key": "1", "cluster_id": 1, "count": 2}]
    rules = list_annotation_execution_stats(db, task.id, requested.operation_id, user.id, kind="rule", limit=1)
    assert rules["total"] == 2
    assert rules["items"][0]["key"] == "r-1"
    assert rules["next_cursor"]
    labels = list_annotation_execution_stats(db, task.id, requested.operation_id, user.id, kind="final_label", limit=10)
    assert labels["items"] == [{"key": "label=a", "label": "label", "value": "a", "count": 2}]


def test_annotation_operation_center_lists_project_owned_operations(db):
    task, user, project = _task(db)
    preview = create_annotation_preview(db, task.id, task_revision=0, config_hash="sha256:operation-center", actor_id=user.id)
    second_preview = create_annotation_preview(db, task.id, task_revision=0, config_hash="sha256:operation-center-2", actor_id=user.id)

    from app.services.annotation_task_state import list_annotation_operations
    page = list_annotation_operations(db, project.id, user.id, limit=1)
    assert page["total"] == 2
    assert page["next_cursor"]
    next_page = list_annotation_operations(db, project.id, user.id, cursor=page["next_cursor"], limit=1)
    assert next_page["total"] == 2
    assert len(next_page["items"]) == 1
    assert {item["id"] for item in page["items"] + next_page["items"]} == {
        str(preview.operation_id),
        str(second_preview.operation_id),
    }
    assert all(item["resource_type"] == "annotation_preview" for item in page["items"] + next_page["items"])


def test_execute_worker_rejects_operation_not_bound_to_task(db, monkeypatch):
    task, user, _ = _task(db)
    preview = create_annotation_preview(db, task.id, task_revision=0, config_hash="sha256:execute-boundary", actor_id=user.id)
    preview.status = "completed"
    preview.progress = 100
    task.status = "executing"
    foreign_operation = DurableOperation(resource_key=f"annotation-execution:{uuid.uuid4()}", idempotency_key=f"0:{preview.id}", state="queued", stage="queued")
    db.add(foreign_operation)
    db.commit()

    from app.tasks.annotation_execution_tasks import execute_annotation_task

    monkeypatch.setattr("app.tasks.annotation_execution_tasks.SessionLocal", lambda: db)
    result = execute_annotation_task.run(str(task.id), str(preview.id), str(user.id), str(foreign_operation.id))

    assert result["status"] == "invalid_request"
    assert db.get(DurableOperation, foreign_operation.id).state == "failed"
    assert db.get(DurableOperation, foreign_operation.id).error_code == "ANNOTATION_EXECUTION_INVALID"
    assert db.query(AnnotationTaskExecutionResult).filter_by(operation_id=foreign_operation.id).count() == 0


def test_execute_worker_fails_closed_when_task_revision_is_stale(db, monkeypatch):
    task, user, _ = _task(db)
    preview = create_annotation_preview(db, task.id, task_revision=0, config_hash="sha256:stale-execution", actor_id=user.id)
    preview.status = "completed"
    preview.progress = 100
    task.status = "executing"
    db.commit()

    from app.services.annotation_task_execution import request_annotation_execution
    requested = request_annotation_execution(db, task.id, preview.id, user.id)
    task.task_revision = 1
    db.commit()

    from app.tasks.annotation_execution_tasks import execute_annotation_task
    monkeypatch.setattr("app.tasks.annotation_execution_tasks.SessionLocal", lambda: db)
    result = execute_annotation_task.run(str(task.id), str(preview.id), str(user.id), str(requested.operation_id))

    assert result["status"] == "invalid_request"
    operation = db.get(DurableOperation, requested.operation_id)
    assert operation.state == "failed"
    assert operation.error_code == "ANNOTATION_EXECUTION_STALE"
    assert db.query(AnnotationTaskExecutionResult).filter_by(operation_id=requested.operation_id).count() == 0


def test_execute_worker_fails_closed_when_preview_is_not_completed(db, monkeypatch):
    task, user, _ = _task(db)
    preview = create_annotation_preview(db, task.id, task_revision=0, config_hash="sha256:execution-preview-invalid", actor_id=user.id)
    preview.status = "completed"
    preview.progress = 100
    task.status = "preview_ready"
    db.commit()

    from app.services.annotation_task_execution import request_annotation_execution
    requested = request_annotation_execution(db, task.id, preview.id, user.id)
    preview.status = "failed"
    db.commit()

    from app.tasks.annotation_execution_tasks import execute_annotation_task
    monkeypatch.setattr("app.tasks.annotation_execution_tasks.SessionLocal", lambda: db)
    result = execute_annotation_task.run(str(task.id), str(preview.id), str(user.id), str(requested.operation_id))

    assert result["status"] == "invalid_request"
    operation = db.get(DurableOperation, requested.operation_id)
    assert operation.state == "failed"
    assert operation.error_code == "ANNOTATION_EXECUTION_INVALID"
    assert db.get(GenericAnnotationTask, task.id).status == "failed"
    assert db.query(AnnotationTaskExecutionResult).filter_by(operation_id=requested.operation_id).count() == 0


def test_execute_retry_same_revision_reuses_operation(db):
    task, user, _ = _task(db)
    preview = create_annotation_preview(db, task.id, task_revision=0, config_hash="sha256:retry-execution", actor_id=user.id)
    preview.status = "completed"
    preview.progress = 100
    task.status = "preview_ready"
    db.commit()

    from app.services.annotation_task_execution import request_annotation_execution
    first = request_annotation_execution(db, task.id, preview.id, user.id)
    second = request_annotation_execution(db, task.id, preview.id, user.id)

    assert first.operation_id == second.operation_id
    assert db.get(GenericAnnotationTask, task.id).task_revision == preview.task_revision


def test_execution_result_queries_reject_operation_with_wrong_preview_binding(db):
    task, user, _ = _task(db)
    preview = create_annotation_preview(db, task.id, task_revision=0, config_hash="sha256:binding-preview", actor_id=user.id)
    preview.status = "completed"
    preview.progress = 100
    task.status = "executing"
    db.commit()
    from app.services.annotation_task_execution import request_annotation_execution
    requested = request_annotation_execution(db, task.id, preview.id, user.id)
    operation = db.get(DurableOperation, requested.operation_id)
    operation.idempotency_key = f"0:{uuid.uuid4()}"
    db.commit()

    from app.services.annotation_task_state import list_annotation_execution_results, list_annotation_execution_stats
    with pytest.raises(ValueError, match="OPERATION_NOT_FOUND"):
        list_annotation_execution_results(db, task.id, requested.operation_id, user.id)
    with pytest.raises(ValueError, match="OPERATION_NOT_FOUND"):
        list_annotation_execution_stats(db, task.id, requested.operation_id, user.id)


@pytest.mark.parametrize(
    ("initial_status", "action", "expected_status"),
    [
        ("draft", TaskAction.cancel, "cancelled"),
        ("needs_review", TaskAction.cancel, "cancelled"),
        ("awaiting_return", TaskAction.return_, "returned_pending_acceptance"),
        ("returned_pending_acceptance", TaskAction.accept, "accepted"),
        ("accepted", TaskAction.complete, "completed"),
        ("completed", TaskAction.archive, "archived"),
        ("archived", TaskAction.restore, "completed"),
    ],
)
def test_task_state_machine_covers_declared_lifecycle(db, initial_status, action, expected_status):
    task, user, _ = _task(db)
    task.status = initial_status
    db.commit()

    transitioned = transition_annotation_task(
        db,
        task.id,
        expected_revision=0,
        action=action,
        actor_id=user.id,
    )

    assert transitioned.status == expected_status


def test_failed_task_can_request_a_new_preview(db):
    task, user, _ = _task(db)
    task.status = "failed"
    db.commit()

    preview = create_annotation_preview(
        db,
        task.id,
        task_revision=0,
        config_hash="sha256:retry-preview",
        actor_id=user.id,
    )

    assert preview.status == "queued"
    assert task.status == "previewing"


def test_pause_and_resume_restore_the_previous_active_state(db):
    task, user, _ = _task(db)
    task.status = "executing"
    db.commit()

    paused = transition_annotation_task(
        db,
        task.id,
        expected_revision=0,
        action=TaskAction.pause,
        actor_id=user.id,
    )
    assert paused.status == "paused"
    assert paused.paused_from_status == "executing"

    resumed = transition_annotation_task(
        db,
        task.id,
        expected_revision=paused.task_revision,
        action=TaskAction.resume,
        actor_id=user.id,
    )

    assert resumed.status == "executing"
    assert resumed.paused_from_status is None


def test_pause_resume_keeps_completed_preview_executable(db, monkeypatch):
    task, user, _ = _task(db)
    preview = create_annotation_preview(db, task.id, 0, "sha256:frozen", user.id)
    from app.tasks.annotation_preview_tasks import execute_annotation_preview
    monkeypatch.setattr("app.tasks.annotation_preview_tasks.SessionLocal", lambda: db)
    execute_annotation_preview.run(str(task.id), str(preview.id), str(user.id))
    transition_annotation_task(db, task.id, 0, TaskAction.pause, user.id)
    transition_annotation_task(db, task.id, task.task_revision, TaskAction.resume, user.id)
    assert task.task_revision == preview.task_revision
    result = transition_annotation_task(db, task.id, task.task_revision, TaskAction.execute, user.id, preview.id)
    assert result.status == "executing"


def test_paused_execution_delivery_can_resume_same_operation(db, monkeypatch):
    task, user, _ = _task(db)
    preview = create_annotation_preview(db, task.id, 0, "sha256:frozen", user.id)
    preview.status = "completed"
    task.status = "preview_ready"
    db.commit()
    from app.services.annotation_task_execution import request_annotation_execution
    from app.tasks.annotation_execution_tasks import execute_annotation_task
    request = request_annotation_execution(db, task.id, preview.id, user.id)
    monkeypatch.setattr("app.tasks.annotation_execution_tasks.SessionLocal", lambda: db)
    transition_annotation_task(db, task.id, 0, TaskAction.pause, user.id)
    args = (str(task.id), str(preview.id), str(user.id), str(request.operation_id))
    assert execute_annotation_task.run(*args)["status"] == "paused"
    assert db.get(DurableOperation, request.operation_id).state == "queued"
    transition_annotation_task(db, task.id, task.task_revision, TaskAction.resume, user.id)
    assert execute_annotation_task.run(*args)["status"] == "completed"
    assert execute_annotation_task.run(*args)["status"] == "not_claimed"


def test_stale_preview_delivery_does_not_publish_or_fail_new_revision(db, monkeypatch):
    task, user, _ = _task(db)
    preview = create_annotation_preview(db, task.id, 0, "sha256:frozen", user.id)
    task.task_revision = 1
    db.commit()
    from app.tasks.annotation_preview_tasks import execute_annotation_preview
    monkeypatch.setattr("app.tasks.annotation_preview_tasks.SessionLocal", lambda: db)
    result = execute_annotation_preview.run(str(task.id), str(preview.id), str(user.id))
    assert result["status"] == "invalid_request"
    assert task.status == "previewing"
    assert db.query(AnnotationTaskPreviewSample).filter_by(preview_id=preview.id).count() == 0


@pytest.mark.parametrize("worker_kind", ["preview", "execution"])
def test_worker_lease_loss_rolls_back_all_results(db, monkeypatch, worker_kind):
    task, user, _ = _task(db)
    preview = create_annotation_preview(db, task.id, 0, "sha256:frozen", user.id)
    if worker_kind == "execution":
        preview.status = "completed"
        task.status = "preview_ready"
        db.add(AnnotationTaskPreviewSample(preview_id=preview.id, sample_id="s-1", row_index=0, values={"label": "ok"}))
        db.commit()
        from app.services.annotation_task_execution import request_annotation_execution
        request = request_annotation_execution(db, task.id, preview.id, user.id)
        from app.tasks import annotation_execution_tasks as module
        args = (str(task.id), str(preview.id), str(user.id), str(request.operation_id))
        worker = module.execute_annotation_task
        model = AnnotationTaskExecutionResult
        operation_id = request.operation_id
    else:
        from app.tasks import annotation_preview_tasks as module
        args = (str(task.id), str(preview.id), str(user.id))
        worker = module.execute_annotation_preview
        model = AnnotationTaskPreviewSample
        operation_id = preview.operation_id
    monkeypatch.setattr(module, "SessionLocal", lambda: db)

    def lose_lease(*args, **kwargs):
        db.rollback()
        operation = db.get(DurableOperation, operation_id)
        operation.lease_owner = "replacement-worker"
        db.commit()
        raise ValueError("OPERATION_LEASE_NOT_OWNED")

    monkeypatch.setattr(module, "heartbeat_operation", lose_lease)
    worker.run(*args)
    assert db.query(model).count() == 0
    assert db.get(DurableOperation, operation_id).lease_owner == "replacement-worker"
    assert task.status == ("executing" if worker_kind == "execution" else "previewing")


def test_list_annotation_tasks_uses_cursor_and_limit(db):
    task, user, project = _task(db)
    page = list_annotation_tasks(db, project.id, owner_id=user.id, cursor=None, limit=1)
    assert page["total"] == 1
    assert page["items"][0]["id"] == str(task.id)
    assert page["next_cursor"] is None


def test_task_list_exposes_only_current_revision_preview_for_execute_after_refresh(db):
    task, user, project = _task(db)
    stale = create_annotation_preview(
        db,
        task.id,
        task_revision=0,
        config_hash="sha256:stale-preview",
        actor_id=user.id,
    )
    task.task_revision = 1
    db.commit()
    current = create_annotation_preview(
        db,
        task.id,
        task_revision=1,
        config_hash="sha256:current-preview",
        actor_id=user.id,
    )
    current.status = "completed"
    current.progress = 100
    current.summary = {"sample_count": 2}
    task.status = "preview_ready"
    db.commit()

    page = list_annotation_tasks(db, project.id, owner_id=user.id, cursor=None, limit=1)

    preview = page["items"][0]["preview"]
    assert preview["id"] == str(current.id)
    assert preview["operation_id"] == str(current.operation_id)
    assert preview["task_revision"] == 1
    assert preview["status"] == "completed"
    assert preview["progress"] == 100
    assert preview["summary"] == {"sample_count": 2}
    assert preview["id"] != str(stale.id)


def test_transition_records_audit_event(db, monkeypatch):
    task, user, project = _task(db)
    create_annotation_preview(db, task.id, task_revision=0, config_hash="sha256:audit", actor_id=user.id)
    from app.tasks.annotation_preview_tasks import execute_annotation_preview
    monkeypatch.setattr("app.tasks.annotation_preview_tasks.SessionLocal", lambda: _SessionContext(db))
    preview = db.query(AnnotationTaskPreview).filter_by(task_id=task.id).one()
    execute_annotation_preview.run(str(task.id), str(preview.id), str(user.id))
    db.refresh(task)
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


def test_preview_worker_reads_the_persisted_revision_snapshot(db, monkeypatch):
    task, user, _ = _task(db)
    from app.models.platform_models import AnnotationTaskRevisionSnapshot

    task.task_revision = 1
    revision_snapshot = {
        "config_hash": "sha256:revision-one",
        "sample_ids": ["s-1"],
        "visible_columns": ["new_feature"],
        "label_schema": {"columns": [{"machine_key": "new_label"}]},
        "configuration": {"strategy": "second"},
    }
    db.add(AnnotationTaskRevisionSnapshot(
        task_id=task.id,
        task_revision=1,
        snapshot=revision_snapshot,
    ))
    db.commit()

    preview = create_annotation_preview(
        db,
        task.id,
        task_revision=1,
        config_hash=revision_snapshot["config_hash"],
        actor_id=user.id,
    )
    from app.tasks.annotation_preview_tasks import execute_annotation_preview

    monkeypatch.setattr("app.tasks.annotation_preview_tasks.SessionLocal", lambda: db)
    result = execute_annotation_preview.run(str(task.id), str(preview.id), str(user.id))

    assert result["status"] == "completed"
    assert preview.summary["visible_columns"] == ["new_feature"]


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
    monkeypatch.setattr("app.tasks.annotation_preview_tasks.SessionLocal", lambda: _SessionContext(db))
    result = execute_annotation_preview.run(str(task.id), str(preview.id), str(user.id))
    assert result["status"] == "completed"
    assert preview.progress == 100
    assert preview.summary["sample_count"] == 2
    assert preview.summary["label_columns"] == ["label"]


def test_preview_samples_are_cursor_paginated_and_owner_scoped(db, monkeypatch):
    task, user, _ = _task(db)
    preview = create_annotation_preview(db, task.id, task_revision=0, config_hash="sha256:sample-page", actor_id=user.id)
    from app.tasks.annotation_preview_tasks import execute_annotation_preview
    monkeypatch.setattr("app.tasks.annotation_preview_tasks.SessionLocal", lambda: db)
    execute_annotation_preview.run(str(task.id), str(preview.id), str(user.id))
    from app.services.annotation_task_state import list_annotation_preview_samples
    first = list_annotation_preview_samples(db, task.id, preview.id, user.id, limit=1)
    assert first["total"] == 2
    assert first["next_cursor"]
    second = list_annotation_preview_samples(db, task.id, preview.id, user.id, cursor=first["next_cursor"], limit=1)
    assert second["items"][0]["sample_id"] != first["items"][0]["sample_id"]


def test_task_list_total_is_stable_across_cursor_pages(db):
    task, user, project = _task(db)
    second = GenericAnnotationTask(
        project_id=project.id, dataset_version_id=uuid.uuid4(), label_schema_id=task.label_schema_id,
        owner_id=user.id, mode="manual", status="draft", task_revision=0, sample_scope={"kind": "all"},
        created_at=datetime(2020, 1, 1),
    )
    db.add(second)
    db.commit()
    first_page = list_annotation_tasks(db, project.id, owner_id=user.id, limit=1)
    assert first_page["total"] == 2
    next_page = list_annotation_tasks(db, project.id, owner_id=user.id, cursor=first_page["next_cursor"], limit=1)
    assert next_page["total"] == 2


def test_preview_worker_marks_failed_and_persists_error(db, monkeypatch):
    task, user, _ = _task(db)
    preview = create_annotation_preview(db, task.id, task_revision=0, config_hash="sha256:failure", actor_id=user.id)
    from app.tasks.annotation_preview_tasks import execute_annotation_preview
    monkeypatch.setattr("app.tasks.annotation_preview_tasks.SessionLocal", lambda: db)
    monkeypatch.setattr("app.tasks.annotation_preview_tasks.DatasetSample", None)
    result = execute_annotation_preview.run(str(task.id), str(preview.id), str(user.id))
    persisted = db.query(AnnotationTaskPreview).filter_by(id=preview.id).one()
    assert result["status"] == "failed"
    assert persisted.status == "failed"
    assert persisted.progress >= 10
    assert persisted.error["code"] == "PREVIEW_EXECUTION_FAILED"


def test_automatic_preview_without_usable_importance_marks_rows_for_review_and_persists_artifact(db, monkeypatch):
    task, user, _ = _task(db)
    task.mode = "automatic"
    snapshot = {
        "config_hash": "sha256:automatic-preview",
        "sample_ids": ["s-1", "s-2"],
        "visible_columns": ["feature"],
        "label_schema": {"columns": [{"machine_key": "label", "value_type": "string", "required": False}]},
        "configuration": {
            "clustering": True,
            "strategy": "cluster",
            "cluster_labels": {},
            "other_values": {"label": "other"},
            "model_outputs": {"s-1": {"label": "a"}, "s-2": {"label": "b"}},
        },
    }
    db.query(GenericAnnotationTask).filter_by(id=task.id).update({GenericAnnotationTask.task_snapshot: snapshot})
    db.commit()
    db.refresh(task)
    preview = create_annotation_preview(db, task.id, task_revision=0, config_hash="sha256:automatic-preview", actor_id=user.id)
    from app.tasks.annotation_preview_tasks import execute_annotation_preview
    monkeypatch.setattr("app.tasks.annotation_preview_tasks.SessionLocal", lambda: db)
    result = execute_annotation_preview.run(str(task.id), str(preview.id), str(user.id))
    samples = db.query(AnnotationTaskPreviewSample).filter_by(preview_id=preview.id).order_by(AnnotationTaskPreviewSample.row_index).all()
    artifact = db.query(AnnotationStrategyArtifact).filter_by(task_id=task.id, task_revision=0).one()
    assert result["status"] == "completed"
    assert artifact.artifact["importance_source"] == "unavailable"
    assert all(sample.values["annotation_decision"]["status"] == "needs_review" for sample in samples)


def test_preview_strategy_loads_model_artifact_and_persists_weighted_cluster_artifact(db, tmp_path):
    task, user, project = _task(db)
    from sklearn.ensemble import RandomForestClassifier
    from app.services.annotation_strategies import apply_preview_annotation_strategy

    features = np.array([[0.0, 0.0], [0.1, 0.2], [0.2, 0.1], [5.0, 5.0], [5.1, 5.2], [5.2, 5.1]])
    labels = np.array(["a", "a", "a", "b", "b", "b"])
    model = RandomForestClassifier(n_estimators=8, random_state=7).fit(features, labels)
    artifact_path = tmp_path / "annotation-model.joblib"
    joblib.dump({"model": model, "input_contract": {"feature_columns": ["x", "y"]}}, artifact_path)
    model_artifact = Artifact(project_id=project.id, name="annotation-model", type="model", storage_path=str(artifact_path), format="joblib")
    db.add(model_artifact)
    db.commit()
    rows = {f"s-{index}": {"x": float(row[0]), "y": float(row[1])} for index, row in enumerate(features)}
    result = apply_preview_annotation_strategy(
        db,
        task_id=task.id,
        task_revision=0,
        config_hash="sha256:artifact-cluster",
        actor_id=user.id,
        project_id=project.id,
        schema_snapshot={"columns": [{"machine_key": "label", "value_type": "string", "required": False}]},
        configuration={
            "model_artifact_id": str(model_artifact.id),
            "clustering": True,
            "strategy": "cluster",
            "cluster_labels": {str(index): {"label": "a" if index == 0 else "b"} for index in range(8)},
            "other_values": {"label": "other"},
            "random_seed": 7,
        },
        rows=rows,
    )
    assert len(result.decisions) == len(rows)
    assert result.artifact.artifact["importance_source"] == "model_artifact"
    assert result.artifact.artifact["cluster_artifact"]["seed"] == 7
    assert len(result.artifact.artifact["cluster_artifact"]["assignments"]) == len(rows)


def test_preview_strategy_with_model_artifact_missing_importance_closes_as_needs_review(db, tmp_path):
    task, user, project = _task(db)
    from sklearn.neighbors import KNeighborsClassifier
    from app.services.annotation_strategies import apply_preview_annotation_strategy

    model = KNeighborsClassifier(n_neighbors=1).fit([[0.0], [1.0]], ["a", "b"])
    artifact_path = tmp_path / "unranked-model.joblib"
    joblib.dump({"model": model, "input_contract": {"feature_columns": ["x"]}}, artifact_path)
    model_artifact = Artifact(project_id=project.id, name="unranked-model", type="model", storage_path=str(artifact_path), format="joblib")
    db.add(model_artifact)
    db.commit()
    result = apply_preview_annotation_strategy(
        db,
        task_id=task.id,
        task_revision=0,
        config_hash="sha256:missing-importance",
        actor_id=user.id,
        project_id=project.id,
        schema_snapshot={"columns": [{"machine_key": "label", "value_type": "string", "required": False}]},
        configuration={
            "model_artifact_id": str(model_artifact.id),
            "clustering": True,
            "strategy": "cluster",
            "cluster_labels": {},
            "other_values": {"label": "other"},
        },
        rows={"s-1": {"x": 0.0}, "s-2": {"x": 1.0}},
    )
    assert result.artifact.artifact["importance_source"] == "unavailable"
    assert {decision.status for decision in result.decisions.values()} == {"needs_review"}
