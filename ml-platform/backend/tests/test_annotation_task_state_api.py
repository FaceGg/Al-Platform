import uuid
import time

import pytest

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.auth import get_current_user
from app.database import Base, get_db
from app.main import app
from app.models.labeling import LabelColumn, LabelSchema
from app.models.artifact import Artifact
from app.models.data_version import DatasetSample, DatasetSchemaColumn, DatasetVersion
from app.models.project import Project
from app.models.platform_models import GenericAnnotationTask, AnnotationTaskPreview
from app.models.user import User


@pytest.fixture(autouse=True)
def isolate_preview_dispatch(monkeypatch):
    monkeypatch.setattr("app.api.annotation_task_state.enqueue_annotation_preview", lambda *args: None)


def test_local_preview_dispatch_completes_with_independent_session(monkeypatch, tmp_path):
    from app.tasks import annotation_preview_tasks as workers
    from app.services.annotation_task_state import create_annotation_preview
    from app.models.operation import DurableOperation

    engine = create_engine(f"sqlite:///{(tmp_path / 'preview.db').as_posix()}")
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr(workers, "SessionLocal", sessions)
    monkeypatch.setattr(workers.settings, "task_backend", "local")
    try:
        with sessions() as db:
            user = User(username="local-preview-owner", password_hash="hash")
            db.add(user)
            db.flush()
            project = Project(name="Local preview", owner_id=user.id)
            db.add(project)
            db.flush()
            schema = LabelSchema(project_id=project.id, name="labels", version=1, status="active")
            db.add(schema)
            db.flush()
            task = GenericAnnotationTask(
                project_id=project.id, dataset_version_id=uuid.uuid4(),
                label_schema_id=schema.id, owner_id=user.id, mode="manual",
                status="draft", task_revision=0, sample_scope={"kind": "all"},
                task_snapshot={"sample_ids": [], "visible_columns": [], "label_schema": {"columns": []}},
            )
            db.add(task)
            db.commit()
            preview = create_annotation_preview(db, task.id, 0, "sha256:local", user.id)
            preview_id, operation_id = preview.id, preview.operation_id
            dispatch = workers.enqueue_annotation_preview(task.id, preview_id, user.id)
            assert dispatch is not None, "local preview must dispatch instead of staying queued"
            assert dispatch.id == str(preview_id)
        deadline = time.monotonic() + 10
        while True:
            with sessions() as db:
                operation = db.get(DurableOperation, operation_id)
                if operation.state in {"completed", "failed"}:
                    assert operation.state == "completed"
                    assert db.get(AnnotationTaskPreview, preview_id).progress == 100
                    assert db.get(GenericAnnotationTask, task.id).status == "preview_ready"
                    break
            assert time.monotonic() < deadline, "local worker did not complete"
            time.sleep(0.02)
    finally:
        engine.dispose()


class _SessionContext:
    def __init__(self, session):
        self.session = session

    def __enter__(self):
        return self.session

    def __exit__(self, *_):
        return False


def test_preview_transition_and_stale_preview_errors(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine, expire_on_commit=False)()
    user = User(username=f"api-task-{uuid.uuid4().hex}", password_hash="hash")
    db.add(user)
    db.flush()
    project = Project(name="API task project", owner_id=user.id)
    db.add(project)
    db.flush()
    schema = LabelSchema(project_id=project.id, name="api-labels", version=1, status="active")
    db.add(schema)
    db.flush()
    db.add(LabelColumn(schema_id=schema.id, machine_key="label", display_name="Label", ordinal=0, value_type="string"))
    version = DatasetVersion(project_id=project.id, operator_id=user.id, version=1, row_count=2, column_count=2, content_hash="sha256:data", schema_hash="sha256:schema")
    db.add(version)
    db.flush()
    db.add_all([
        DatasetSchemaColumn(dataset_version_id=version.id, name="feature", position=0, dtype="float", nullable=False),
        DatasetSchemaColumn(dataset_version_id=version.id, name="label", position=1, dtype="string", nullable=True),
        DatasetSample(dataset_version_id=version.id, sample_id="sample-1", row_index=0, values={"feature": 1.0}),
        DatasetSample(dataset_version_id=version.id, sample_id="sample-2", row_index=1, values={"feature": 2.0}),
    ])
    db.commit()
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: user
    client = TestClient(app)
    try:
        headers = {"X-Request-ID": str(uuid.uuid4()), "Idempotency-Key": f"task-{uuid.uuid4()}"}
        created = client.post("/api/annotation-tasks", headers=headers, json={"project_id": str(project.id), "dataset_version_id": str(version.id), "label_schema_id": str(schema.id), "mode": "manual", "sample_scope": {"kind": "all"}})
        assert created.status_code == 201, created.text
        task_id = created.json()["id"]
        assert created.json()["status"] == "draft"
        invalid_publish = client.post(f"/api/annotation-tasks/{task_id}/transition", json={"task_revision": 0, "action": "publish"})
        assert invalid_publish.status_code == 409
        assert invalid_publish.json()["detail"]["code"] == "TASK_STATE_INVALID"
        assert set(invalid_publish.json()["detail"]) >= {"request_id", "code", "message", "details"}
        preview = client.post(f"/api/annotation-tasks/{task_id}/preview", json={"task_revision": 0, "config_hash": "sha256:test"})
        assert preview.status_code == 202, preview.text
        repeated = client.post(f"/api/annotation-tasks/{task_id}/preview", json={"task_revision": 0, "config_hash": "sha256:test"})
        assert repeated.json()["operation_id"] == preview.json()["operation_id"]
        from app.tasks.annotation_preview_tasks import execute_annotation_preview
        monkeypatch.setattr("app.tasks.annotation_preview_tasks.SessionLocal", lambda: _SessionContext(db))
        execute_annotation_preview.run(task_id, preview.json()["preview_id"], str(user.id))
        monkeypatch.setattr("app.api.annotation_task_state.enqueue_annotation_execution", lambda *args: type("Dispatch", (), {"id": "execution-dispatch"})())
        executed = client.post(f"/api/annotation-tasks/{task_id}/execute", json={"task_revision": 0, "preview_id": preview.json()["preview_id"]})
        assert executed.status_code == 202, executed.text
        assert executed.json()["operation_id"]
        assert executed.json()["dispatch_id"] == "execution-dispatch"
        retried = client.post(f"/api/annotation-tasks/{task_id}/transition", json={"task_revision": 0, "action": "execute", "preview_id": preview.json()["preview_id"]})
        assert retried.status_code == 200
        assert retried.json()["operation_id"] == executed.json()["operation_id"]
    finally:
        app.dependency_overrides.clear()
        db.close()
        engine.dispose()


def test_task_creation_freezes_server_owned_snapshot():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine, expire_on_commit=False)()
    user = User(username=f"snapshot-{uuid.uuid4().hex}", password_hash="hash")
    db.add(user)
    db.flush()
    project = Project(name="Snapshot project", owner_id=user.id)
    db.add(project)
    db.flush()
    schema = LabelSchema(project_id=project.id, name="snapshot-labels", version=1, status="active")
    db.add(schema)
    db.flush()
    db.add(LabelColumn(schema_id=schema.id, machine_key="result", display_name="Result", ordinal=0, value_type="string"))
    version = DatasetVersion(project_id=project.id, operator_id=user.id, version=1, row_count=2, column_count=2, content_hash="sha256:data", schema_hash="sha256:schema")
    db.add(version)
    db.flush()
    db.add_all([
        DatasetSchemaColumn(dataset_version_id=version.id, name="feature", position=0, dtype="float", nullable=False),
        DatasetSchemaColumn(dataset_version_id=version.id, name="result", position=1, dtype="string", nullable=True),
        DatasetSample(dataset_version_id=version.id, sample_id="s-1", row_index=0, values={"feature": 1}),
        DatasetSample(dataset_version_id=version.id, sample_id="s-2", row_index=1, values={"feature": 2}),
    ])
    db.commit()
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: user
    client = TestClient(app)
    try:
        request_id = str(uuid.uuid4())
        response = client.post("/api/annotation-tasks", headers={"X-Request-ID": request_id, "Idempotency-Key": str(uuid.uuid4())}, json={"project_id": str(project.id), "dataset_version_id": str(version.id), "label_schema_id": str(schema.id), "mode": "automatic", "sample_scope": {"kind": "ids", "sample_ids": ["s-2"]}, "visible_columns": ["feature"], "instructions": "Review selected rows", "configuration": {"strategy": "model"}, "label_snapshot": {"client": "ignored"}})
        assert response.status_code == 201, response.text
        snapshot = response.json()["task_snapshot"]
        assert snapshot["dataset_version"]["id"] == str(version.id)
        assert snapshot["sample_ids"] == ["s-2"]
        assert snapshot["visible_columns"] == ["feature"]
        assert snapshot["label_schema"]["schema_id"] == str(schema.id)
        assert snapshot["instructions"] == "Review selected rows"
        assert snapshot["configuration"] == {"strategy": "model"}
        assert snapshot["config_hash"].startswith("sha256:")
        assert "client" not in snapshot["label_schema"]
    finally:
        app.dependency_overrides.clear()
        db.close()
        engine.dispose()


def test_configuration_update_creates_new_revision_and_invalidates_old_preview():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine, expire_on_commit=False)()
    user = User(username=f"config-update-{uuid.uuid4().hex}", password_hash="hash")
    db.add(user); db.flush()
    project = Project(name="Config update project", owner_id=user.id)
    db.add(project); db.flush()
    schema = LabelSchema(project_id=project.id, name="config-labels", version=1, status="active")
    db.add(schema); db.flush()
    db.add(LabelColumn(schema_id=schema.id, machine_key="label", display_name="Label", ordinal=0, value_type="string"))
    version = DatasetVersion(project_id=project.id, operator_id=user.id, version=1, row_count=1, column_count=1, content_hash="sha256:config-data", schema_hash="sha256:config-schema")
    db.add(version); db.flush()
    db.add(DatasetSample(dataset_version_id=version.id, sample_id="sample-1", row_index=0, values={"feature": 1.0})); db.commit()
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: user
    client = TestClient(app)
    try:
        headers = {"X-Request-ID": str(uuid.uuid4()), "Idempotency-Key": str(uuid.uuid4())}
        created = client.post("/api/annotation-tasks", headers=headers, json={"project_id": str(project.id), "dataset_version_id": str(version.id), "label_schema_id": str(schema.id), "mode": "automatic", "sample_scope": {"kind": "all"}, "configuration": {"strategy": "first"}})
        assert created.status_code == 201, created.text
        task_id = created.json()["id"]
        old_preview = client.post(f"/api/annotation-tasks/{task_id}/preview", json={"task_revision": 0, "config_hash": created.json()["task_snapshot"]["config_hash"]})
        assert old_preview.status_code == 202
        db.get(GenericAnnotationTask, uuid.UUID(task_id)).status = "failed"
        db.commit()
        updated = client.put(f"/api/annotation-tasks/{task_id}/configuration", json={"task_revision": 0, "visible_columns": ["feature"], "instructions": "updated", "configuration": {"strategy": "second"}})
        assert updated.status_code == 200, updated.text
        assert updated.json()["task_revision"] == 1
        assert updated.json()["task_snapshot"]["config_hash"] != created.json()["task_snapshot"]["config_hash"]
        refreshed = client.get(f"/api/annotation-tasks?project_id={project.id}")
        assert refreshed.status_code == 200
        assert refreshed.json()["items"][0]["task_revision"] == 1
        assert refreshed.json()["items"][0]["task_snapshot"]["config_hash"] == updated.json()["task_snapshot"]["config_hash"]
        stale = client.post(f"/api/annotation-tasks/{task_id}/execute", json={"task_revision": 0, "preview_id": old_preview.json()["preview_id"]})
        assert stale.status_code == 409
        assert stale.json()["detail"]["code"] == "TASK_REVISION_CONFLICT"
        new_preview = client.post(f"/api/annotation-tasks/{task_id}/preview", json={"task_revision": 1, "config_hash": updated.json()["task_snapshot"]["config_hash"]})
        assert new_preview.status_code == 202, new_preview.text
        assert new_preview.json()["task_revision"] == 1
    finally:
        app.dependency_overrides.clear(); db.close(); engine.dispose()


def test_preview_detail_is_owner_scoped():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine, expire_on_commit=False)()
    user = User(username=f"detail-{uuid.uuid4().hex}", password_hash="hash")
    db.add(user)
    db.flush()
    project = Project(name="Detail project", owner_id=user.id)
    db.add(project)
    db.flush()
    schema = LabelSchema(project_id=project.id, name="detail-labels", version=1, status="active")
    db.add(schema)
    db.flush()
    db.add(LabelColumn(schema_id=schema.id, machine_key="label", display_name="Label", ordinal=0, value_type="string"))
    task = GenericAnnotationTask(project_id=project.id, dataset_version_id=uuid.uuid4(), label_schema_id=schema.id, owner_id=user.id, mode="manual", status="draft", task_revision=0, sample_scope={"kind": "all"})
    db.add(task)
    db.commit()
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: user
    client = TestClient(app)
    try:
        preview = client.post(f"/api/annotation-tasks/{task.id}/preview", json={"task_revision": 0, "config_hash": "sha256:detail"})
        assert preview.status_code == 202
        detail = client.get(f"/api/annotation-tasks/{task.id}/previews/{preview.json()['preview_id']}")
        assert detail.status_code == 200
        assert detail.json()["progress"] == 0
        assert detail.json()["status"] == "queued"
    finally:
        app.dependency_overrides.clear()
        db.close()
        engine.dispose()


def test_automatic_preview_detail_exposes_strategy_summary_without_sample_provenance(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine, expire_on_commit=False)()
    user = User(username=f"strategy-detail-{uuid.uuid4().hex}", password_hash="hash")
    db.add(user)
    db.flush()
    project = Project(name="Strategy detail project", owner_id=user.id)
    db.add(project)
    db.flush()
    schema = LabelSchema(project_id=project.id, name="strategy-labels", version=1, status="active")
    db.add(schema)
    db.flush()
    db.add(LabelColumn(schema_id=schema.id, machine_key="label", display_name="Label", ordinal=0, value_type="string"))
    version = DatasetVersion(project_id=project.id, operator_id=user.id, version=1, row_count=1, column_count=1, content_hash="sha256:strategy-data", schema_hash="sha256:strategy-schema")
    db.add(version)
    db.flush()
    db.add_all([
        DatasetSchemaColumn(dataset_version_id=version.id, name="feature", position=0, dtype="float", nullable=False),
        DatasetSample(dataset_version_id=version.id, sample_id="strategy-sample", row_index=0, values={"feature": 1.0}),
    ])
    db.commit()
    task = GenericAnnotationTask(
        project_id=project.id,
        dataset_version_id=version.id,
        label_schema_id=schema.id,
        owner_id=user.id,
        mode="automatic",
        status="draft",
        task_revision=0,
        task_snapshot={
            "sample_ids": ["strategy-sample"],
            "visible_columns": ["feature"],
            "label_schema": {"columns": [{"machine_key": "label", "value_type": "string", "required": False}]},
            "configuration": {"clustering": True, "strategy": "cluster", "cluster_labels": {}, "other_values": {"label": "other"}, "model_outputs": {"strategy-sample": {"label": "a"}}},
        },
    )
    db.add(task)
    db.commit()
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: user
    client = TestClient(app)
    try:
        preview = client.post(f"/api/annotation-tasks/{task.id}/preview", json={"task_revision": 0, "config_hash": "sha256:strategy-preview"})
        assert preview.status_code == 202, preview.text
        from app.tasks.annotation_preview_tasks import execute_annotation_preview
        monkeypatch.setattr("app.tasks.annotation_preview_tasks.SessionLocal", lambda: _SessionContext(db))
        execute_annotation_preview.run(str(task.id), preview.json()["preview_id"], str(user.id))
        detail = client.get(f"/api/annotation-tasks/{task.id}/previews/{preview.json()['preview_id']}")
        assert detail.status_code == 200, detail.text
        assert detail.json()["summary"]["strategy"] == "cluster"
        assert detail.json()["summary"]["needs_review_count"] == 1
        assert "provenance" not in detail.json()["summary"]
    finally:
        app.dependency_overrides.clear()
        db.close()
        engine.dispose()


def test_automatic_task_rejects_model_artifact_from_another_project():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine, expire_on_commit=False)()
    user = User(username=f"artifact-contract-{uuid.uuid4().hex}", password_hash="hash")
    db.add(user)
    db.flush()
    project = Project(name="Artifact contract project", owner_id=user.id)
    other_project = Project(name="Other artifact project", owner_id=user.id)
    db.add_all([project, other_project])
    db.flush()
    schema = LabelSchema(project_id=project.id, name="artifact-contract-labels", version=1, status="active")
    db.add(schema)
    db.flush()
    db.add(LabelColumn(schema_id=schema.id, machine_key="label", display_name="Label", ordinal=0, value_type="string"))
    version = DatasetVersion(project_id=project.id, operator_id=user.id, version=1, row_count=1, column_count=1, content_hash="sha256:artifact-contract", schema_hash="sha256:artifact-contract-schema")
    foreign_artifact = Artifact(project_id=other_project.id, name="foreign-model", type="model", storage_path="missing.joblib", format="joblib")
    db.add_all([version, foreign_artifact])
    db.flush()
    db.add(DatasetSchemaColumn(dataset_version_id=version.id, name="feature", position=0, dtype="float", nullable=False))
    db.add(DatasetSample(dataset_version_id=version.id, sample_id="artifact-contract-sample", row_index=0, values={"feature": 1.0}))
    db.commit()
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: user
    client = TestClient(app)
    try:
        response = client.post(
            "/api/annotation-tasks",
            headers={"X-Request-ID": str(uuid.uuid4()), "Idempotency-Key": str(uuid.uuid4())},
            json={
                "project_id": str(project.id),
                "dataset_version_id": str(version.id),
                "label_schema_id": str(schema.id),
                "mode": "automatic",
                "sample_scope": {"kind": "all"},
                "configuration": {"model_artifact_id": str(foreign_artifact.id), "clustering": False, "strategy": "model"},
            },
        )
        assert response.status_code == 422
        assert response.json()["detail"]["code"] == "MODEL_ARTIFACT_NOT_FOUND"
    finally:
        app.dependency_overrides.clear()
        db.close()
        engine.dispose()


def test_preview_creation_dispatches_in_celery_mode(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine, expire_on_commit=False)()
    user = User(username=f"dispatch-{uuid.uuid4().hex}", password_hash="hash")
    db.add(user)
    db.flush()
    project = Project(name="Dispatch project", owner_id=user.id)
    db.add(project)
    db.flush()
    schema = LabelSchema(project_id=project.id, name="dispatch-labels", version=1, status="active")
    db.add(schema)
    db.flush()
    db.add(LabelColumn(schema_id=schema.id, machine_key="label", display_name="Label", ordinal=0, value_type="string"))
    task = GenericAnnotationTask(project_id=project.id, dataset_version_id=uuid.uuid4(), label_schema_id=schema.id, owner_id=user.id, mode="manual", status="draft", task_revision=0, sample_scope={"kind": "all"})
    db.add(task)
    db.commit()
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: user
    client = TestClient(app)
    calls = []
    class Result:
        id = "celery-operation-1"
    monkeypatch.setattr("app.api.annotation_task_state.enqueue_annotation_preview", lambda *args: calls.append(args) or Result())
    monkeypatch.setattr("app.config.settings.task_backend", "celery")
    try:
        response = client.post(f"/api/annotation-tasks/{task.id}/preview", json={"task_revision": 0, "config_hash": "sha256:dispatch"})
        assert response.status_code == 202
        assert response.json()["dispatch_id"] == "celery-operation-1"
        repeated = client.post(f"/api/annotation-tasks/{task.id}/preview", json={"task_revision": 0, "config_hash": "sha256:dispatch"})
        assert repeated.status_code == 202
        assert calls == [(task.id, uuid.UUID(response.json()["preview_id"]), user.id)]
    finally:
        app.dependency_overrides.clear()
        db.close()
        engine.dispose()


def test_preview_list_hides_task_from_non_owner_and_supports_cursor():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine, expire_on_commit=False)()
    owner = User(username=f"owner-{uuid.uuid4().hex}", password_hash="hash")
    other = User(username=f"other-{uuid.uuid4().hex}", password_hash="hash")
    db.add_all([owner, other])
    db.flush()
    project = Project(name="Preview project", owner_id=owner.id)
    db.add(project)
    db.flush()
    schema = LabelSchema(project_id=project.id, name="preview-labels", version=1, status="active")
    db.add(schema)
    db.flush()
    db.add(LabelColumn(schema_id=schema.id, machine_key="label", display_name="Label", ordinal=0, value_type="string"))
    db.commit()
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: owner
    client = TestClient(app)
    try:
        task_model = GenericAnnotationTask(project_id=project.id, dataset_version_id=uuid.uuid4(), label_schema_id=schema.id, owner_id=owner.id, mode="manual", status="draft", task_revision=0, sample_scope={"kind": "all"})
        db.add(task_model)
        db.commit()
        task = {"id": str(task_model.id)}
        for value in ("one", "two"):
            response = client.post(f"/api/annotation-tasks/{task['id']}/preview", json={"task_revision": 0, "config_hash": f"sha256:{value}"})
            assert response.status_code == 202
            db.flush()
        first = client.get(f"/api/annotation-tasks/{task['id']}/previews?limit=1")
        assert first.status_code == 200
        assert first.json()["next_cursor"]
        second = client.get(f"/api/annotation-tasks/{task['id']}/previews?limit=1&cursor={first.json()['next_cursor']}")
        assert second.status_code == 200
        assert second.json()["items"][0]["id"] != first.json()["items"][0]["id"]
        app.dependency_overrides[get_current_user] = lambda: other
        hidden = client.get(f"/api/annotation-tasks/{task['id']}/previews")
        assert hidden.status_code == 404
    finally:
        app.dependency_overrides.clear()
        db.close()
        engine.dispose()
