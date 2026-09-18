import uuid
from datetime import datetime
from types import SimpleNamespace

import joblib
import numpy as np
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Query, sessionmaker
from sqlalchemy.pool import StaticPool

import app.models.labeling as labeling_models
from app.database import Base
from app.models.annotator import AnnotatorAccount, ProjectAnnotatorGrant
from app.models.labeling import (
    AnnotationAssignmentSample,
    AnnotationRevision,
    AnnotationSampleCurrent,
    AnnotationStrategyArtifact,
    LabelColumn,
    LabelSchema,
)
from app.models.artifact import Artifact
from app.models.access import AuditEvent
from app.models.data_version import DatasetSample, DatasetSchemaColumn, DatasetVersion
from app.models.operation import DurableOperation
from app.models.platform_models import (
    AnnotationTaskExecutionResult,
    AnnotationTaskPreview,
    AnnotationTaskPreviewSample,
    AnnotationTaskRevisionSnapshot,
    GenericAnnotationTask,
    AnnotationTaskScopeSample,
)
from app.models.project import Project
from app.models.user import User
from app.schemas.annotation_tasks import TaskAction
from app.services.annotation_task_state import (
    create_annotation_preview,
    current_annotation_task_preview,
    list_annotation_preview_samples,
    list_annotation_previews,
    list_annotation_tasks,
    transition_annotation_task,
)
from app.services.annotation_concurrency import create_assignments
from app.services.annotation_scope import iter_scope_batches, persist_scope_entries, scope_count, scope_descriptor


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


@pytest.mark.parametrize(
    ("field", "setting"),
    [
        ("sample_count", "annotation_max_samples"),
        ("input_column_count", "annotation_max_input_columns"),
        ("label_column_count", "annotation_max_label_columns"),
    ],
)
def test_annotation_capacity_preflight_blocks_before_preview(db, monkeypatch, field, setting):
    from app.config import settings
    from app.api.annotation_task_state import _error

    task, user, project = _task(db)
    db.add(DatasetVersion(
        id=task.dataset_version_id, project_id=project.id, operator_id=user.id,
        version=1, row_count=2, column_count=2, content_hash="sha256:data", schema_hash="sha256:schema",
    ))
    db.add(AnnotationTaskRevisionSnapshot(task_id=task.id, task_revision=0, snapshot={
        "scope": {"sample_count": 2},
        "label_schema": {"columns": [{"machine_key": "a"}, {"machine_key": "b"}]},
    }))
    db.add_all([
        DatasetSchemaColumn(dataset_version_id=task.dataset_version_id, name="a", position=0, dtype="float", nullable=False),
        DatasetSchemaColumn(dataset_version_id=task.dataset_version_id, name="b", position=1, dtype="float", nullable=False),
    ])
    db.commit()
    for name in ("annotation_max_samples", "annotation_max_input_columns", "annotation_max_label_columns"):
        monkeypatch.setattr(settings, name, 2)
    monkeypatch.setattr(settings, setting, 1)
    with pytest.raises(ValueError, match="ANNOTATION_CAPACITY_EXCEEDED") as exc_info:
        create_annotation_preview(db, task.id, 0, "sha256:frozen", user.id)
    assert exc_info.value.details["exceeded"] == {field: {"count": 2, "limit": 1}}
    http_error = _error(exc_info.value)
    assert http_error.status_code == 409
    assert http_error.detail["details"] == exc_info.value.details
    assert task.status == "draft"
    assert db.query(AnnotationTaskPreview).filter_by(task_id=task.id).count() == 0
    assert db.query(DurableOperation).count() == 0
    monkeypatch.setattr(settings, setting, 2)
    preview = create_annotation_preview(db, task.id, 0, "sha256:frozen", user.id)
    assert preview.summary["capacity"] == {"sample_count": 2, "input_column_count": 2, "label_column_count": 2}


def test_existing_preview_replay_survives_lowered_capacity_quota(db, monkeypatch):
    from app.config import settings

    task, user, _ = _task(db)
    preview = create_annotation_preview(db, task.id, 0, "sha256:frozen", user.id)
    monkeypatch.setattr(settings, "annotation_max_samples", 1)
    repeated = create_annotation_preview(db, task.id, 0, "sha256:frozen", user.id)
    assert repeated.id == preview.id
    assert db.query(DurableOperation).count() == 1


def test_annotation_capacity_preflight_fails_closed_without_frozen_scope(db):
    user = User(username=f"unknown-scope-{uuid.uuid4().hex}", password_hash="hash")
    db.add(user)
    db.flush()
    project = Project(name="Unknown scope", owner_id=user.id)
    db.add(project)
    db.flush()
    schema = LabelSchema(project_id=project.id, name="unknown-labels", version=1, status="active")
    db.add(schema)
    db.flush()
    task = GenericAnnotationTask(
        project_id=project.id,
        dataset_version_id=uuid.uuid4(),
        label_schema_id=schema.id,
        owner_id=user.id,
        mode="manual",
        status="draft",
        task_revision=0,
        sample_scope={"kind": "all"},
        task_snapshot={"visible_columns": [], "label_schema": {"columns": []}},
    )
    db.add(task)
    db.commit()
    with pytest.raises(ValueError, match="ANNOTATION_CAPACITY_UNKNOWN"):
        create_annotation_preview(db, task.id, 0, "sha256:unknown-scope", user.id)


def test_publish_keeps_the_configuration_revision_and_current_preview(db):
    task, user, _ = _task(db)
    preview = create_annotation_preview(db, task.id, task_revision=0, config_hash="sha256:publish-configuration", actor_id=user.id)
    preview.status = "completed"
    preview.progress = 100
    task.status = "preview_ready"
    db.commit()

    published = transition_annotation_task(
        db,
        task.id,
        expected_revision=0,
        action=TaskAction.publish,
        actor_id=user.id,
    )

    assert published.status == "awaiting_annotation"
    assert published.task_revision == 0
    assert current_annotation_task_preview(db, published).id == preview.id


def test_task_lifecycle_command_receipt_replays_before_revision_validation(db):
    task, user, _ = _task(db)
    task.status = "preview_ready"
    db.commit()

    first = transition_annotation_task(
        db,
        task.id,
        expected_revision=0,
        action=TaskAction.pause,
        actor_id=user.id,
        idempotency_key="pause-command",
        request_id=uuid.uuid4(),
    )
    operation = db.query(DurableOperation).filter_by(
        task_id=task.id,
        resource_type="annotation_task_command",
        idempotency_key="pause-command",
    ).one()
    assert first.status == "paused"
    assert operation.result_summary["response"]["status"] == "paused"

    task.status = "completed"
    db.commit()
    replay = transition_annotation_task(
        db,
        task.id,
        expected_revision=0,
        action=TaskAction.pause,
        actor_id=user.id,
        idempotency_key="pause-command",
        request_id=uuid.uuid4(),
    )
    assert replay._command_replayed is True
    assert replay._command_operation_id == operation.id
    assert replay._command_response_payload == operation.result_summary["response"]

    with pytest.raises(ValueError, match="IDEMPOTENCY_CONFLICT"):
        transition_annotation_task(
            db,
            task.id,
            expected_revision=0,
            action=TaskAction.pause,
            actor_id=user.id,
            idempotency_key="pause-command",
            reason="changed payload",
        )


def test_reopen_creates_a_new_configuration_revision_snapshot(db):
    task, user, _ = _task(db)
    task.status = "completed"
    db.commit()

    reopened = transition_annotation_task(
        db,
        task.id,
        expected_revision=0,
        action=TaskAction.reopen,
        actor_id=user.id,
    )

    assert reopened.status == "in_progress"
    assert reopened.task_revision == 1
    snapshot = db.query(AnnotationTaskRevisionSnapshot).filter_by(task_id=task.id, task_revision=1).one()
    assert snapshot.snapshot == task.task_snapshot


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


def test_execute_worker_publishes_current_labels_and_assignments_copy_them(db, monkeypatch):
    task, user, project = _task(db)
    task.mode = "automatic"
    preview = create_annotation_preview(db, task.id, task_revision=0, config_hash="sha256:execution-label-publication", actor_id=user.id)
    preview.status = "completed"
    preview.progress = 100
    db.add_all([
        AnnotationTaskPreviewSample(
            preview_id=preview.id,
            sample_id="s-1",
            row_index=0,
            values={
                "annotation_decision": {
                    "values": {"label": "auto-a"},
                    "provenance": {"label": {"source": "model"}},
                    "model_output": {"label": "auto-a"},
                    "cluster_id": 1,
                    "matched_rule_ids": ["rule-a"],
                }
            },
        ),
        AnnotationTaskPreviewSample(
            preview_id=preview.id,
            sample_id="s-2",
            row_index=1,
            values={"annotation_decision": {"values": {"label": "auto-b"}}},
        ),
    ])
    task.status = "preview_ready"
    db.commit()

    from app.services.annotation_task_execution import request_annotation_execution
    from app.tasks.annotation_execution_tasks import execute_annotation_task

    requested = request_annotation_execution(db, task.id, preview.id, user.id)
    monkeypatch.setattr("app.tasks.annotation_execution_tasks.SessionLocal", lambda: db)
    result = execute_annotation_task.run(str(task.id), str(preview.id), str(user.id), str(requested.operation_id))

    assert result["status"] == "completed"
    current = db.query(AnnotationSampleCurrent).filter_by(task_id=task.id).order_by(AnnotationSampleCurrent.sample_id).all()
    assert [(row.sample_id, row.values, row.revision_no) for row in current] == [
        ("s-1", {"label": "auto-a"}, 0),
        ("s-2", {"label": "auto-b"}, 0),
    ]
    revisions = db.query(AnnotationRevision).filter_by(task_id=task.id).order_by(AnnotationRevision.sample_id).all()
    assert [(row.sample_id, row.values, row.revision_no, row.source, row.action) for row in revisions] == [
        ("s-1", {"label": "auto-a"}, 0, "automatic", "initialize"),
        ("s-2", {"label": "auto-b"}, 0, "automatic", "initialize"),
    ]
    assert all(row.provenance_ref == f"annotation-execution:{requested.operation_id}" for row in revisions)

    subject_id = uuid.uuid4()
    db.add_all([
        AnnotatorAccount(subject_id=subject_id, username=f"automatic-{uuid.uuid4().hex}", password_hash="hash", status="active"),
        ProjectAnnotatorGrant(project_id=project.id, subject_id=subject_id, status="active", granted_by=user.id),
    ])
    db.commit()
    assignment = create_assignments(
        db,
        task_id=task.id,
        annotator_ids=[subject_id],
        sample_scope={"kind": "ids", "sample_ids": ["s-1", "s-2"]},
        actor=user.id,
        initial_revision=task.task_revision,
        idempotency_key="automatic-label-assignment",
    )[0]
    assigned = db.query(AnnotationAssignmentSample).filter_by(assignment_id=assignment.id).order_by(AnnotationAssignmentSample.sample_id).all()
    assert [(row.sample_id, row.values, row.revision_no) for row in assigned] == [
        ("s-1", {"label": "auto-a"}, 0),
        ("s-2", {"label": "auto-b"}, 0),
    ]


def test_execute_worker_rejects_nonready_results_without_publishing_labels(db, monkeypatch):
    task, user, _ = _task(db)
    task.mode = "automatic"
    preview = create_annotation_preview(db, task.id, task_revision=0, config_hash="sha256:execution-nonready-output", actor_id=user.id)
    preview.status = "completed"
    preview.progress = 100
    db.add_all([
        AnnotationTaskPreviewSample(
            preview_id=preview.id,
            sample_id="s-1",
            row_index=0,
            values={"annotation_decision": {"values": {"label": "auto-a"}, "status": "ready"}},
        ),
        AnnotationTaskPreviewSample(
            preview_id=preview.id,
            sample_id="s-2",
            row_index=1,
            values={"annotation_decision": {"values": {"label": "auto-b"}, "status": "failed"}},
        ),
    ])
    task.status = "preview_ready"
    db.commit()

    from app.services.annotation_task_execution import request_annotation_execution
    from app.tasks.annotation_execution_tasks import execute_annotation_task

    requested = request_annotation_execution(db, task.id, preview.id, user.id)
    monkeypatch.setattr("app.tasks.annotation_execution_tasks.SessionLocal", lambda: db)
    result = execute_annotation_task.run(str(task.id), str(preview.id), str(user.id), str(requested.operation_id))

    assert result["status"] == "failed"
    assert db.get(DurableOperation, requested.operation_id).state == "failed"
    assert db.query(AnnotationTaskExecutionResult).filter_by(operation_id=requested.operation_id).count() == 0
    assert db.query(AnnotationSampleCurrent).filter_by(task_id=task.id).count() == 0
    assert db.query(AnnotationRevision).filter_by(task_id=task.id).count() == 0


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


def test_execute_worker_materializes_results_in_bounded_batches(db, monkeypatch):
    task, user, _ = _task(db)
    preview = create_annotation_preview(
        db,
        task.id,
        task_revision=0,
        config_hash="sha256:bounded-execution",
        actor_id=user.id,
    )
    preview.status = "completed"
    preview.progress = 100
    task.status = "preview_ready"
    db.add_all([
        AnnotationTaskPreviewSample(
            preview_id=preview.id,
            sample_id=f"bounded-{index}",
            row_index=index,
            values={"label": f"value-{index}"},
        )
        for index in range(3)
    ])
    db.commit()

    from app.services.annotation_task_execution import request_annotation_execution
    from app.tasks.annotation_execution_tasks import execute_annotation_task

    requested = request_annotation_execution(db, task.id, preview.id, user.id)
    monkeypatch.setattr("app.tasks.annotation_execution_tasks.SessionLocal", lambda: db)
    original_all = Query.all

    def bounded_all(query):
        assert query._limit_clause is not None, f"unbounded row query: {query}"
        return original_all(query)

    monkeypatch.setattr(Query, "all", bounded_all)
    result = execute_annotation_task.run(
        str(task.id),
        str(preview.id),
        str(user.id),
        str(requested.operation_id),
    )

    assert result["status"] == "completed"
    assert db.query(AnnotationTaskExecutionResult).filter_by(operation_id=requested.operation_id).count() == 3


def test_preview_worker_materializes_source_rows_in_bounded_batches(db, monkeypatch):
    task, user, _ = _task(db)
    sample_ids = [f"preview-bounded-{index}" for index in range(3)]
    frozen_snapshot = {
        "config_hash": "sha256:preview-bounded",
        "sample_ids": sample_ids,
        "visible_columns": ["feature"],
        "label_schema": {"columns": [{"machine_key": "label"}]},
    }
    db.query(GenericAnnotationTask).filter_by(id=task.id).update(
        {GenericAnnotationTask.task_snapshot: frozen_snapshot},
        synchronize_session=False,
    )
    db.refresh(task)
    db.add_all([
        DatasetSample(
            dataset_version_id=task.dataset_version_id,
            sample_id=sample_id,
            row_index=index,
            values={"feature": index},
        )
        for index, sample_id in enumerate(sample_ids)
    ])
    db.commit()

    preview = create_annotation_preview(
        db,
        task.id,
        task_revision=0,
        config_hash="sha256:preview-bounded",
        actor_id=user.id,
    )
    from app.tasks.annotation_preview_tasks import execute_annotation_preview

    monkeypatch.setattr("app.tasks.annotation_preview_tasks.SessionLocal", lambda: db)
    original_all = Query.all

    def bounded_all(query):
        assert query._limit_clause is not None, f"unbounded preview row query: {query}"
        return original_all(query)

    monkeypatch.setattr(Query, "all", bounded_all)
    result = execute_annotation_preview.run(str(task.id), str(preview.id), str(user.id))

    assert result["status"] == "completed", db.get(AnnotationTaskPreview, preview.id).error
    persisted = db.query(AnnotationTaskPreviewSample).filter_by(preview_id=preview.id).limit(10).all()
    assert [item.sample_id for item in persisted] == sample_ids


def test_persisted_task_scope_uses_bounded_keyset_pages(db, monkeypatch):
    task, _, _ = _task(db)
    scope_entries = [(f"scope-{index}", index * 10) for index in range(5)]
    assert persist_scope_entries(db, task.id, 0, scope_entries, batch_size=2) == len(scope_entries)
    db.commit()
    snapshot = {
        "scope": scope_descriptor(len(scope_entries), "sha256:scope"),
        "sample_ids": ["legacy-id-must-not-be-read"],
    }
    original_all = Query.all

    def bounded_all(query):
        assert query._limit_clause is not None, f"unbounded scope query: {query}"
        return original_all(query)

    monkeypatch.setattr(Query, "all", bounded_all)
    assert scope_count(db, task, task_revision=0, snapshot=snapshot) == len(scope_entries)
    assert list(iter_scope_batches(db, task, task_revision=0, snapshot=snapshot, batch_size=2)) == [
        scope_entries[:2],
        scope_entries[2:4],
        scope_entries[4:],
    ]


def test_preview_worker_uses_persisted_scope_instead_of_snapshot_sample_ids(db, monkeypatch):
    task, user, _ = _task(db)
    sample_ids = [f"persisted-preview-{index}" for index in range(3)]
    snapshot = {
        "config_hash": "sha256:persisted-preview-scope",
        "scope": scope_descriptor(len(sample_ids), "sha256:persisted-preview-scope"),
        "sample_ids": ["legacy-id-must-not-be-read"],
        "visible_columns": ["feature"],
        "label_schema": {"columns": [{"machine_key": "label"}]},
    }
    db.query(GenericAnnotationTask).filter_by(id=task.id).update(
        {GenericAnnotationTask.task_snapshot: snapshot},
        synchronize_session=False,
    )
    persist_scope_entries(db, task.id, 0, [(sample_id, index) for index, sample_id in enumerate(sample_ids)])
    db.add_all([
        DatasetSample(
            dataset_version_id=task.dataset_version_id,
            sample_id=sample_id,
            row_index=index,
            values={"feature": index},
        )
        for index, sample_id in enumerate(sample_ids)
    ])
    db.commit()
    db.refresh(task)
    preview = create_annotation_preview(
        db,
        task.id,
        task_revision=0,
        config_hash=snapshot["config_hash"],
        actor_id=user.id,
    )
    from app.tasks import annotation_preview_tasks as module

    monkeypatch.setattr(module, "SessionLocal", lambda: db)
    monkeypatch.setattr(module, "_PREVIEW_BATCH_SIZE", 2)
    result = module.execute_annotation_preview.run(str(task.id), str(preview.id), str(user.id))

    assert result["status"] == "completed", db.get(AnnotationTaskPreview, preview.id).error
    assert [item.sample_id for item in db.query(AnnotationTaskPreviewSample).filter_by(preview_id=preview.id).order_by(
        AnnotationTaskPreviewSample.row_index.asc()
    ).all()] == sample_ids


def test_automatic_preview_runs_strategy_in_bounded_source_batches(db, monkeypatch):
    task, user, _ = _task(db)
    task.mode = "automatic"
    sample_ids = [f"automatic-bounded-{index}" for index in range(501)]
    frozen_snapshot = {
        "config_hash": "sha256:automatic-bounded",
        "sample_ids": sample_ids,
        "visible_columns": ["feature"],
        "label_schema": {"columns": [{"machine_key": "label", "value_type": "string"}]},
        "configuration": {"clustering": False},
    }
    db.query(GenericAnnotationTask).filter_by(id=task.id).update(
        {GenericAnnotationTask.task_snapshot: frozen_snapshot},
        synchronize_session=False,
    )
    db.refresh(task)
    db.add_all([
        DatasetSample(
            dataset_version_id=task.dataset_version_id,
            sample_id=sample_id,
            row_index=index,
            values={"feature": index},
        )
        for index, sample_id in enumerate(sample_ids)
    ])
    db.commit()

    preview = create_annotation_preview(
        db,
        task.id,
        task_revision=0,
        config_hash="sha256:automatic-bounded",
        actor_id=user.id,
    )
    from app.services.annotation_strategies import AnnotationDecision
    from app.tasks import annotation_preview_tasks as module

    strategy_batches = []
    artifact = SimpleNamespace(
        id=uuid.uuid4(),
        strategy="model",
        artifact={
            "configuration_complete": True,
            "model_version_id": None,
        },
    )

    def evaluate_batch(*_args, rows, **_kwargs):
        strategy_batches.append(tuple(rows))
        return SimpleNamespace(
            decisions={
                sample_id: AnnotationDecision(
                    values={"label": f"value-{row['feature']}"},
                    provenance={"label": {"source": "model"}},
                    model_output={"label": f"value-{row['feature']}"},
                )
                for sample_id, row in rows.items()
            },
            artifact=artifact,
        )

    monkeypatch.setattr(module, "SessionLocal", lambda: db)
    monkeypatch.setattr(module, "apply_preview_annotation_strategy", evaluate_batch)
    result = module.execute_annotation_preview.run(str(task.id), str(preview.id), str(user.id))

    assert result["status"] == "completed", db.get(AnnotationTaskPreview, preview.id).error
    assert [len(batch) for batch in strategy_batches] == [500, 1]
    assert db.query(AnnotationTaskPreviewSample).filter_by(preview_id=preview.id).count() == len(sample_ids)


def test_cluster_discovery_preview_uses_bounded_streams_and_persists_decisions(db, monkeypatch, tmp_path):
    task, user, project = _task(db)
    from sklearn.ensemble import RandomForestClassifier
    from app.tasks import annotation_preview_tasks as module

    task.mode = "automatic"
    sample_ids = [f"cluster-stream-{index}" for index in range(12)]
    features = np.array([
        [0.0, 0.0], [0.1, 0.2], [0.2, 0.1], [0.3, 0.1], [0.4, 0.2], [0.5, 0.1],
        [5.0, 5.0], [5.1, 5.2], [5.2, 5.1], [5.3, 5.1], [5.4, 5.2], [5.5, 5.1],
    ])
    labels = np.array(["a"] * 6 + ["b"] * 6)
    model = RandomForestClassifier(n_estimators=8, random_state=7).fit(features, labels)
    artifact_path = tmp_path / "streaming-cluster-model.joblib"
    joblib.dump({"model": model, "input_contract": {"feature_columns": ["x", "y"]}}, artifact_path)
    model_artifact = Artifact(
        project_id=project.id,
        name="streaming-cluster-model",
        type="model",
        storage_path=str(artifact_path),
        format="joblib",
    )
    db.add(model_artifact)
    db.flush()
    snapshot = {
        "config_hash": "sha256:cluster-streaming",
        "sample_ids": sample_ids,
        "visible_columns": ["x"],
        "label_schema": {"columns": [{"machine_key": "label", "value_type": "string"}]},
        "configuration": {
            "model_artifact_id": str(model_artifact.id),
            "clustering": True,
            "cluster_discovery": True,
            "random_seed": 7,
            "model_outputs": {
                sample_id: {"label": str(labels[index])}
                for index, sample_id in enumerate(sample_ids)
            },
        },
    }
    db.query(GenericAnnotationTask).filter_by(id=task.id).update(
        {GenericAnnotationTask.task_snapshot: snapshot},
        synchronize_session=False,
    )
    db.add_all([
        DatasetSample(
            dataset_version_id=task.dataset_version_id,
            sample_id=sample_id,
            row_index=index,
            values={"x": float(features[index, 0]), "y": float(features[index, 1])},
        )
        for index, sample_id in enumerate(sample_ids)
    ])
    db.commit()
    db.refresh(task)

    preview = create_annotation_preview(
        db,
        task.id,
        task_revision=0,
        config_hash=snapshot["config_hash"],
        actor_id=user.id,
    )
    original_batches = module._dataset_sample_batches
    requested_batch_sizes = []

    def observed_batches(session, dataset_version_id, batch_sample_ids):
        requested_batch_sizes.append(len(batch_sample_ids))
        yield from original_batches(session, dataset_version_id, batch_sample_ids)

    monkeypatch.setattr(module, "SessionLocal", lambda: db)
    monkeypatch.setattr(module, "_PREVIEW_BATCH_SIZE", 3)
    monkeypatch.setattr(module, "_dataset_sample_batches", observed_batches)
    result = module.execute_annotation_preview.run(str(task.id), str(preview.id), str(user.id))

    assert result["status"] == "completed", db.get(AnnotationTaskPreview, preview.id).error
    assert requested_batch_sizes and max(requested_batch_sizes) <= 3
    strategy = db.query(AnnotationStrategyArtifact).filter_by(task_id=task.id).one()
    assert "assignments" not in strategy.artifact["cluster_artifact"]
    assert "labels" not in strategy.artifact["cluster_artifact"]
    assert strategy.artifact["clusters"] == []
    assert strategy.artifact["cluster_counts_storage"] == "annotation_strategy_decisions"
    decision_model = labeling_models.AnnotationStrategyDecision
    assert db.query(decision_model).filter_by(strategy_artifact_id=strategy.id).count() == len(sample_ids)
    assert db.query(AnnotationTaskPreviewSample).filter_by(preview_id=preview.id).count() == len(sample_ids)
    assert sum(item["sample_count"] for item in db.get(AnnotationTaskPreview, preview.id).summary["clusters"]) == len(sample_ids)


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

    from app.models.platform_models import AnnotationTaskExecutionStatistic
    from app.services.annotation_task_state import list_annotation_execution_stats

    persisted = db.query(AnnotationTaskExecutionStatistic).filter_by(operation_id=requested.operation_id).all()
    assert {
        (item.kind, item.payload["key"], item.count)
        for item in persisted
    } == {
        ("cluster", "1", 2),
        ("rule", "r-1", 2),
        ("rule", "r-2", 1),
        ("final_label", "label=a", 2),
    }
    operation = db.get(DurableOperation, requested.operation_id)
    assert operation.result_summary == {"sample_count": 2, "needs_review_count": 0}

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


def test_annotation_operation_center_lists_return_operations_by_task_context(db):
    task, user, project = _task(db)
    preview = create_annotation_preview(
        db,
        task.id,
        task_revision=0,
        config_hash="sha256:return-operation-context",
        actor_id=user.id,
    )
    return_operation = DurableOperation(
        project_id=project.id,
        task_id=task.id,
        resource_type="annotation_return",
        resource_key=f"annotation-return:{uuid.uuid4()}",
        idempotency_key="return-operation-context",
        state="queued",
        stage="queued",
    )
    db.add(return_operation)
    db.commit()

    from app.services.annotation_task_state import list_annotation_operations

    page = list_annotation_operations(db, project.id, user.id, limit=10)

    assert page["total"] == 2
    assert {item["id"] for item in page["items"]} == {
        str(preview.operation_id),
        str(return_operation.id),
    }
    assert {item["resource_type"] for item in page["items"]} == {
        "annotation_preview",
        "annotation_return",
    }


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


def test_annotation_preview_and_execution_operations_store_task_context(db):
    task, user, project = _task(db)
    preview = create_annotation_preview(
        db,
        task.id,
        task_revision=0,
        config_hash="sha256:operation-context",
        actor_id=user.id,
    )
    preview.status = "completed"
    preview.progress = 100
    task.status = "preview_ready"
    db.commit()

    from app.services.annotation_task_execution import request_annotation_execution

    execution = request_annotation_execution(db, task.id, preview.id, user.id)
    preview_operation = db.get(DurableOperation, preview.operation_id)
    execution_operation = db.get(DurableOperation, execution.operation_id)

    for operation, resource_type in (
        (preview_operation, "annotation_preview"),
        (execution_operation, "annotation_execution"),
    ):
        assert operation.project_id == project.id
        assert operation.task_id == task.id
        assert operation.resource_type == resource_type


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


def test_task_preview_and_sample_pages_use_bounded_row_queries(db, monkeypatch):
    task, user, project = _task(db)
    first_preview = AnnotationTaskPreview(
        task_id=task.id,
        task_revision=0,
        config_hash="sha256:bounded-page-1",
        created_by=user.id,
        status="completed",
        progress=100,
    )
    second_preview = AnnotationTaskPreview(
        task_id=task.id,
        task_revision=0,
        config_hash="sha256:bounded-page-2",
        created_by=user.id,
        status="completed",
        progress=100,
    )
    db.add_all([first_preview, second_preview])
    db.flush()
    db.add_all([
        AnnotationTaskPreviewSample(preview_id=first_preview.id, sample_id="bounded-1", row_index=0, values={}),
        AnnotationTaskPreviewSample(preview_id=first_preview.id, sample_id="bounded-2", row_index=1, values={}),
    ])
    db.commit()

    original_all = Query.all

    def bounded_all(query):
        assert query._limit_clause is not None, f"unbounded row query: {query}"
        return original_all(query)

    monkeypatch.setattr(Query, "all", bounded_all)
    assert len(list_annotation_tasks(db, project.id, user.id, limit=1)["items"]) == 1
    assert len(list_annotation_previews(db, task.id, user.id, limit=1)["items"]) == 1
    assert len(list_annotation_preview_samples(db, task.id, first_preview.id, user.id, limit=1)["items"]) == 1


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


def test_preview_checksum_failure_rolls_back_samples_and_completion_state(db, monkeypatch):
    task, user, _ = _task(db)
    preview = create_annotation_preview(db, task.id, task_revision=0, config_hash="sha256:checksum-failure", actor_id=user.id)
    from app.tasks.annotation_preview_tasks import execute_annotation_preview

    monkeypatch.setattr("app.tasks.annotation_preview_tasks.SessionLocal", lambda: db)

    def fail_checksum_iteration(*args, **kwargs):
        raise ValueError("CHECKSUM_BUILD_FAILED")

    monkeypatch.setattr("app.tasks.annotation_preview_tasks._preview_sample_batches", fail_checksum_iteration)
    result = execute_annotation_preview.run(str(task.id), str(preview.id), str(user.id))

    persisted_preview = db.query(AnnotationTaskPreview).filter_by(id=preview.id).one()
    operation = db.get(DurableOperation, preview.operation_id)
    assert result["status"] == "failed"
    assert db.query(AnnotationTaskPreviewSample).filter_by(preview_id=preview.id).count() == 0
    assert persisted_preview.status == "failed"
    assert operation.state == "failed"


def test_preview_worker_persists_claim_failure_at_zero_progress(db, monkeypatch):
    task, user, _ = _task(db)
    preview = create_annotation_preview(db, task.id, task_revision=0, config_hash="sha256:claim-failure", actor_id=user.id)
    from app.tasks.annotation_preview_tasks import execute_annotation_preview
    monkeypatch.setattr("app.tasks.annotation_preview_tasks.SessionLocal", lambda: db)
    monkeypatch.setattr(
        "app.tasks.annotation_preview_tasks.claim_operation",
        lambda *args, **kwargs: (_ for _ in ()).throw(ValueError("OPERATION_NOT_FOUND")),
    )
    result = execute_annotation_preview.run(str(task.id), str(preview.id), str(user.id))
    persisted = db.query(AnnotationTaskPreview).filter_by(id=preview.id).one()
    assert result["status"] == "failed"
    assert persisted.status == "failed"
    assert persisted.progress == 0
    assert persisted.error == {"code": "PREVIEW_EXECUTION_FAILED", "message": "OPERATION_NOT_FOUND", "details": {}}


def test_cluster_discovery_without_usable_importance_fails_closed(db, monkeypatch):
    task, user, _ = _task(db)
    task.mode = "automatic"
    snapshot = {
        "config_hash": "sha256:automatic-preview",
        "sample_ids": ["s-1", "s-2"],
        "visible_columns": ["feature"],
        "label_schema": {"columns": [{"machine_key": "label", "value_type": "string", "required": False}]},
            "configuration": {
                "clustering": True,
                "cluster_discovery": True,
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
    persisted = db.query(AnnotationTaskPreview).filter_by(id=preview.id).one()
    assert result["status"] == "failed"
    assert persisted.status == "failed"
    assert persisted.error["code"] == "FEATURE_IMPORTANCE_UNAVAILABLE"
    assert db.query(AnnotationStrategyArtifact).filter_by(task_id=task.id, task_revision=0).count() == 0


def test_cluster_discovery_persists_sample_decisions_outside_weighted_cluster_artifact(db, tmp_path):
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
            "cluster_discovery": True,
            "random_seed": 7,
        },
        rows=rows,
    )
    assert len(result.decisions) == len(rows)
    assert result.artifact.artifact["importance_source"] == "model_artifact"
    assert result.artifact.artifact["configuration_complete"] is False
    cluster_artifact = result.artifact.artifact["cluster_artifact"]
    assert cluster_artifact["seed"] == 7
    assert cluster_artifact["evaluation_mode"] == "all_rows"
    assert cluster_artifact["evaluation_sample_count"] == len(rows)
    assert cluster_artifact["total_sample_count"] == len(rows)
    assert cluster_artifact["evaluation_sample_hash"]
    assert cluster_artifact["preprocessing"]["fit_scope"] == "frozen_task_sample_scope"
    assert cluster_artifact["preprocessing"]["standardizer"]["mean"]
    assert "assignments" not in cluster_artifact
    assert "labels" not in cluster_artifact
    decision_model = getattr(labeling_models, "AnnotationStrategyDecision", None)
    assert decision_model is not None
    persisted = db.query(decision_model).filter_by(strategy_artifact_id=result.artifact.id).order_by(
        decision_model.row_index.asc()
    ).all()
    assert [(item.sample_id, item.cluster_id, item.status) for item in persisted] == [
        (sample_id, result.decisions[sample_id].cluster_id, "pending_configuration")
        for sample_id in rows
    ]
    assert all(item.decision_hash.startswith("sha256:") for item in persisted)
    assert {decision.status for decision in result.decisions.values()} == {"pending_configuration"}
    from app.api.generic_tasks import _cluster_discovery_ids
    assert _cluster_discovery_ids(db, task) == {
        str(decision.cluster_id)
        for decision in result.decisions.values()
    }


def test_final_cluster_preview_reuses_the_discovery_artifact(db, tmp_path, monkeypatch):
    task, user, project = _task(db)
    from sklearn.ensemble import RandomForestClassifier
    from app.services import annotation_strategies

    features = np.array([[0.0, 0.0], [0.1, 0.2], [0.2, 0.1], [5.0, 5.0], [5.1, 5.2], [5.2, 5.1]])
    labels = np.array(["a", "a", "a", "b", "b", "b"])
    model = RandomForestClassifier(n_estimators=8, random_state=7).fit(features, labels)
    artifact_path = tmp_path / "discovery-model.joblib"
    joblib.dump({"model": model, "input_contract": {"feature_columns": ["x", "y"]}}, artifact_path)
    model_artifact = Artifact(project_id=project.id, name="discovery-model", type="model", storage_path=str(artifact_path), format="joblib")
    db.add(model_artifact)
    db.commit()
    rows = {f"s-{index}": {"x": float(row[0]), "y": float(row[1])} for index, row in enumerate(features)}
    schema_snapshot = {"columns": [{"machine_key": "label", "value_type": "string", "required": True}]}

    discovery = annotation_strategies.apply_preview_annotation_strategy(
        db,
        task_id=task.id,
        task_revision=0,
        config_hash="sha256:cluster-discovery",
        actor_id=user.id,
        project_id=project.id,
        schema_snapshot=schema_snapshot,
        configuration={
            "model_artifact_id": str(model_artifact.id),
            "clustering": True,
            "cluster_discovery": True,
            "random_seed": 7,
        },
        rows=rows,
    )
    selected_cluster = str(next(iter(discovery.decisions.values())).cluster_id)

    monkeypatch.setattr(
        annotation_strategies,
        "_cluster_artifact_from_package",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("final preview must reuse discovery artifact")),
    )
    final = annotation_strategies.apply_preview_annotation_strategy(
        db,
        task_id=task.id,
        task_revision=1,
        config_hash="sha256:cluster-final",
        actor_id=user.id,
        project_id=project.id,
        schema_snapshot=schema_snapshot,
        configuration={
            "model_artifact_id": str(model_artifact.id),
            "clustering": True,
            "strategy": "cluster",
            "selected_clusters": [selected_cluster],
            "cluster_labels": {selected_cluster: {"label": "a"}},
            "other_values": {"label": "other"},
            "random_seed": 7,
        },
        rows=rows,
    )

    assert final.artifact.artifact["configuration_complete"] is True
    assert "assignments" not in final.artifact.artifact["cluster_artifact"]
    assert {
        decision.cluster_id
        for decision in final.decisions.values()
    } == {
        decision.cluster_id
        for decision in discovery.decisions.values()
    }


def test_cluster_discovery_falls_back_to_permutation_importance(db, tmp_path):
    task, user, project = _task(db)
    from sklearn.neighbors import KNeighborsClassifier
    from app.services.annotation_strategies import apply_preview_annotation_strategy

    features = np.array([[0.0], [0.1], [0.2], [5.0], [5.1], [5.2]])
    labels = np.array(["a", "a", "a", "b", "b", "b"])
    model = KNeighborsClassifier(n_neighbors=1).fit(features, labels)
    artifact_path = tmp_path / "unranked-model.joblib"
    joblib.dump({"model": model, "input_contract": {"feature_columns": ["x"]}}, artifact_path)
    model_artifact = Artifact(project_id=project.id, name="unranked-model", type="model", storage_path=str(artifact_path), format="joblib")
    db.add(model_artifact)
    db.commit()
    rows = {f"s-{index}": {"x": float(row[0])} for index, row in enumerate(features)}

    result = apply_preview_annotation_strategy(
        db,
        task_id=task.id,
        task_revision=0,
        config_hash="sha256:permutation-importance",
        actor_id=user.id,
        project_id=project.id,
        schema_snapshot={"columns": [{"machine_key": "label", "value_type": "string", "required": False}]},
        configuration={
            "model_artifact_id": str(model_artifact.id),
            "clustering": True,
            "cluster_discovery": True,
            "random_seed": 7,
        },
        rows=rows,
    )
    cluster_artifact = result.artifact.artifact["cluster_artifact"]
    assert cluster_artifact["importance_method"] == "permutation"
    assert sum(cluster_artifact["weights"].values()) == pytest.approx(1.0)
    assert all(weight >= 0 for weight in cluster_artifact["weights"].values())


class _UnscorableModel:
    """predict works, but has neither native importance nor a score method."""

    def predict(self, values):
        import numpy as _np

        return _np.asarray(["a"] * len(values))


class _UnpredictableModel:
    """Model inference itself fails, exercising the MODEL_INFERENCE_FAILED code."""

    def predict(self, values):
        raise RuntimeError("predictor unavailable")


def test_cluster_discovery_without_any_importance_source_fails_closed(db, tmp_path):
    task, user, project = _task(db)
    from app.services.annotation_strategies import StrategyConfigError, apply_preview_annotation_strategy

    artifact_path = tmp_path / "unscorable-model.joblib"
    joblib.dump({"model": _UnscorableModel(), "input_contract": {"feature_columns": ["x"]}}, artifact_path)
    model_artifact = Artifact(project_id=project.id, name="unscorable-model", type="model", storage_path=str(artifact_path), format="joblib")
    db.add(model_artifact)
    db.commit()

    with pytest.raises(StrategyConfigError) as error:
        apply_preview_annotation_strategy(
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
                "cluster_discovery": True,
            },
            rows={"s-1": {"x": 0.0}, "s-2": {"x": 1.0}, "s-3": {"x": 2.0}},
        )
    assert error.value.code == "FEATURE_IMPORTANCE_UNAVAILABLE"


def test_model_inference_failure_fails_preview_with_stable_code(db, tmp_path):
    task, user, project = _task(db)
    from app.services.annotation_strategies import StrategyConfigError, apply_preview_annotation_strategy

    artifact_path = tmp_path / "broken-model.joblib"
    joblib.dump({"model": _UnpredictableModel(), "input_contract": {"feature_columns": ["x"]}}, artifact_path)
    model_artifact = Artifact(project_id=project.id, name="broken-model", type="model", storage_path=str(artifact_path), format="joblib")
    db.add(model_artifact)
    db.commit()

    with pytest.raises(StrategyConfigError) as error:
        apply_preview_annotation_strategy(
            db,
            task_id=task.id,
            task_revision=0,
            config_hash="sha256:broken-inference",
            actor_id=user.id,
            project_id=project.id,
            schema_snapshot={"columns": [{"machine_key": "label", "value_type": "string", "required": False}]},
            configuration={
                "model_artifact_id": str(model_artifact.id),
                "clustering": True,
                "cluster_discovery": True,
            },
            rows={"s-1": {"x": 0.0}, "s-2": {"x": 1.0}, "s-3": {"x": 2.0}},
        )
    assert error.value.code == "MODEL_INFERENCE_FAILED"


def test_cluster_discovery_uses_frozen_multioutput_feature_importance(db, tmp_path):
    task, user, project = _task(db)
    from sklearn.multioutput import MultiOutputClassifier
    from sklearn.neighbors import KNeighborsClassifier
    from app.services.annotation_strategies import apply_preview_annotation_strategy

    features = np.array([[0.0, 0.0], [0.1, 0.2], [0.2, 0.1], [5.0, 5.0], [5.1, 5.2], [5.2, 5.1]])
    targets = np.array([["a", "low"], ["a", "low"], ["a", "high"], ["b", "high"], ["b", "high"], ["b", "high"]])
    model = MultiOutputClassifier(KNeighborsClassifier(n_neighbors=1)).fit(features, targets)
    artifact_path = tmp_path / "multioutput-importance.joblib"
    joblib.dump({
        "model": model,
        "input_contract": {"feature_columns": ["x", "y"]},
        "feature_importance": {"x": 3.0, "y": 1.0},
        "feature_importance_report": {
            "source": "model_native",
            "by_feature": {"x": 0.75, "y": 0.25},
            "per_target": {
                "label_a": {"x": 0.75, "y": 0.25},
                "label_b": {"x": 0.75, "y": 0.25},
            },
        },
    }, artifact_path)
    model_artifact = Artifact(project_id=project.id, name="multioutput-importance", type="model", storage_path=str(artifact_path), format="joblib")
    db.add(model_artifact)
    db.commit()
    rows = {f"s-{index}": {"x": float(row[0]), "y": float(row[1])} for index, row in enumerate(features)}

    result = apply_preview_annotation_strategy(
        db,
        task_id=task.id,
        task_revision=0,
        config_hash="sha256:multioutput-importance",
        actor_id=user.id,
        project_id=project.id,
        schema_snapshot={"columns": [
            {"machine_key": "label_a", "value_type": "string", "required": False},
            {"machine_key": "label_b", "value_type": "string", "required": False},
        ]},
        configuration={
            "model_artifact_id": str(model_artifact.id),
            "clustering": True,
            "cluster_discovery": True,
            "random_seed": 7,
        },
        rows=rows,
    )

    cluster_artifact = result.artifact.artifact["cluster_artifact"]
    assert cluster_artifact["weights"] == pytest.approx({"x": 0.75, "y": 0.25})
    assert cluster_artifact["importance_method"] == "model_native"
    assert result.artifact.artifact["importance_source"] == "model_artifact"
