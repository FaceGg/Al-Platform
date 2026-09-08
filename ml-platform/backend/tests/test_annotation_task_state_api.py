import uuid

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.auth import get_current_user
from app.database import Base, get_db
from app.main import app
from app.models.labeling import LabelColumn, LabelSchema
from app.models.data_version import DatasetSample, DatasetSchemaColumn, DatasetVersion
from app.models.project import Project
from app.models.platform_models import GenericAnnotationTask, AnnotationTaskPreview
from app.models.user import User


def test_preview_transition_and_stale_preview_errors():
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
        preview = client.post(f"/api/annotation-tasks/{task_id}/preview", json={"task_revision": 0, "config_hash": "sha256:test"})
        assert preview.status_code == 202, preview.text
        repeated = client.post(f"/api/annotation-tasks/{task_id}/preview", json={"task_revision": 0, "config_hash": "sha256:test"})
        assert repeated.json()["operation_id"] == preview.json()["operation_id"]
        executed = client.post(f"/api/annotation-tasks/{task_id}/transition", json={"task_revision": 0, "action": "execute", "preview_id": preview.json()["preview_id"]})
        assert executed.status_code == 200, executed.text
        stale = client.post(f"/api/annotation-tasks/{task_id}/transition", json={"task_revision": 0, "action": "execute", "preview_id": preview.json()["preview_id"]})
        assert stale.status_code == 409
        assert stale.json()["detail"]["code"] == "TASK_REVISION_CONFLICT"
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
