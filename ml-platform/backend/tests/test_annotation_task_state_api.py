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
from app.models.model_library import ModelLibrary
from app.models.model_registry import ModelVersion, RegisteredModel
from app.models.project import Project
from app.models.platform_models import AnnotationTaskScopeSample, GenericAnnotationTask, AnnotationTaskPreview
from app.models.user import User
from app.models.access import ProjectMember


def test_technical_annotation_task_routes_are_exposed():
    paths = app.openapi()["paths"]
    assert "post" in paths["/api/annotation-tasks/{task_id}/publish"]
    assert "post" in paths["/api/annotation-tasks/{task_id}/pause"]
    assert "post" in paths["/api/annotation-tasks/{task_id}/reopen"]
    assert "patch" in paths["/api/annotation-tasks/{task_id}/assignments/{assignment_id}"]


@pytest.mark.parametrize("role,expected_status", [("editor", 201), ("viewer", 403), ("outsider", 404)])
def test_annotation_draft_creation_uses_project_permission(role, expected_status):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine, expire_on_commit=False)()
    owner = User(username=f"draft-owner-{uuid.uuid4().hex}", password_hash="hash")
    member = User(username=f"draft-member-{uuid.uuid4().hex}", password_hash="hash")
    db.add_all([owner, member])
    db.flush()
    project = Project(name="Draft permissions", owner_id=owner.id)
    db.add(project)
    db.flush()
    if role != "outsider":
        db.add(ProjectMember(project_id=project.id, user_id=member.id, role=role, created_by=owner.id))
    version = DatasetVersion(
        project_id=project.id, operator_id=owner.id, version=1,
        row_count=1, column_count=1, content_hash="sha256:data", schema_hash="sha256:schema",
    )
    schema = LabelSchema(project_id=project.id, name="draft-labels", version=1, status="active")
    db.add_all([version, schema])
    db.flush()
    db.add_all([
        DatasetSchemaColumn(dataset_version_id=version.id, name="feature", position=0, dtype="float", nullable=False),
        DatasetSample(dataset_version_id=version.id, sample_id="s-1", row_index=0, values={"feature": 1.0}),
        LabelColumn(schema_id=schema.id, machine_key="label", display_name="Label", ordinal=0, value_type="string"),
    ])
    db.commit()
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: member
    try:
        request_id = str(uuid.uuid4())
        response = TestClient(app).post(
            "/api/annotation-tasks",
            headers={"X-Request-ID": request_id, "Idempotency-Key": f"draft-{request_id}"},
            json={"project_id": str(project.id), "dataset_version_id": str(version.id),
                  "label_schema_id": str(schema.id), "mode": "manual"},
        )
        assert response.status_code == expected_status, response.text
        if expected_status == 201:
            created = db.get(GenericAnnotationTask, uuid.UUID(response.json()["id"]))
            assert created.status == "draft"
            assert created.owner_id == member.id
            assert created.project_id == project.id
        else:
            assert db.query(GenericAnnotationTask).count() == 0
    finally:
        app.dependency_overrides.clear()
        db.close()
        engine.dispose()


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
                status="draft", task_revision=0, sample_scope={"kind": "all", "sample_count": 0},
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


def _enabled_annotation_model(db, project, user, *, columns=None):
    columns = columns or [
        {"name": "result", "dtype": "object", "task": "classification"},
        {"name": "score", "dtype": "int64", "task": "classification"},
    ]
    source = Artifact(
        project_id=project.id,
        name=f"annotation-source-{uuid.uuid4().hex}.joblib",
        type="model",
        storage_path="annotation-source.joblib",
        format="joblib",
    )
    converted = Artifact(
        project_id=project.id,
        name=f"annotation-source-{uuid.uuid4().hex}.onnx",
        type="model",
        storage_path="annotation-source.onnx",
        format="onnx",
    )
    library = ModelLibrary(
        name=f"annotation-library-{uuid.uuid4().hex[:8]}",
        project_id=project.id,
        owner_id=user.id,
        status="completed",
        format="joblib",
        model_artifact_id=source.id,
    )
    model = RegisteredModel(
        project_id=project.id,
        name=f"annotation-model-{uuid.uuid4().hex[:8]}",
        created_by_id=user.id,
    )
    db.add_all([source, converted, library, model])
    db.flush()
    target_columns = [column["name"] for column in columns]
    version = ModelVersion(
        registered_model_id=model.id,
        version_number=1,
        source_kind="platform_joblib",
        source_model_library_id=library.id,
        source_artifact_id=source.id,
        onnx_artifact_id=converted.id,
        framework="sklearn",
        algorithm="contract-test",
        feature_schema=[{"name": "feature", "dtype": "float64"}],
        output_schema={"task_type": "multioutput_classification", "target_columns": target_columns},
        conversion_metadata={"input_contract": {
            "input_columns": ["feature"],
            "target_columns": target_columns,
            "target_schema": columns,
        }},
        approval_status="approved",
        lifecycle_state="enabled",
        created_by_id=user.id,
    )
    db.add(version)
    db.flush()
    return version, source


def test_annotation_model_version_listing_flags_eligibility():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine, expire_on_commit=False)()
    user = User(username=f"model-list-{uuid.uuid4().hex}", password_hash="hash")
    db.add(user)
    db.flush()
    project = Project(name="Model listing", owner_id=user.id)
    db.add(project)
    db.flush()
    approved, _ = _enabled_annotation_model(db, project, user)

    pending_model = RegisteredModel(
        project_id=project.id,
        name=f"pending-model-{uuid.uuid4().hex[:8]}",
        created_by_id=user.id,
    )
    onnx_model = RegisteredModel(
        project_id=project.id,
        name=f"onnx-model-{uuid.uuid4().hex[:8]}",
        created_by_id=user.id,
    )
    pending_source = Artifact(
        project_id=project.id,
        name=f"pending-source-{uuid.uuid4().hex}.joblib",
        type="model",
        storage_path="pending-source.joblib",
        format="joblib",
    )
    pending_onnx = Artifact(
        project_id=project.id,
        name=f"pending-source-{uuid.uuid4().hex}.onnx",
        type="model",
        storage_path="pending-source.onnx",
        format="onnx",
    )
    onnx_source = Artifact(
        project_id=project.id,
        name=f"onnx-source-{uuid.uuid4().hex}.onnx",
        type="model",
        storage_path="onnx-source.onnx",
        format="onnx",
    )
    onnx_converted = Artifact(
        project_id=project.id,
        name=f"onnx-converted-{uuid.uuid4().hex}.onnx",
        type="model",
        storage_path="onnx-converted.onnx",
        format="onnx",
    )
    pending_library = ModelLibrary(
        name=f"pending-library-{uuid.uuid4().hex[:8]}",
        project_id=project.id,
        owner_id=user.id,
        status="completed",
        format="joblib",
        model_artifact_id=pending_source.id,
    )
    db.add_all([pending_model, onnx_model, pending_source, pending_onnx, onnx_source, onnx_converted, pending_library])
    db.flush()
    pending = ModelVersion(
        registered_model_id=pending_model.id,
        version_number=1,
        source_kind="platform_joblib",
        source_model_library_id=pending_library.id,
        source_artifact_id=pending_source.id,
        onnx_artifact_id=pending_onnx.id,
        framework="sklearn",
        algorithm="pending-test",
        feature_schema=[{"name": "feature", "dtype": "float64"}],
        output_schema={"task_type": "multioutput_classification", "target_columns": ["label"]},
        approval_status="pending",
        lifecycle_state="pending_review",
        created_by_id=user.id,
    )
    onnx_version = ModelVersion(
        registered_model_id=onnx_model.id,
        version_number=1,
        source_kind="onnx_artifact",
        source_artifact_id=onnx_source.id,
        onnx_artifact_id=onnx_converted.id,
        framework="sklearn",
        algorithm="onnx-test",
        feature_schema=[{"name": "feature", "dtype": "float64"}],
        output_schema={"task_type": "multioutput_classification", "target_columns": ["label"]},
        approval_status="approved",
        lifecycle_state="enabled",
        created_by_id=user.id,
    )
    db.add_all([pending, onnx_version])
    db.commit()

    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: user
    try:
        response = TestClient(app).get(f"/api/projects/{project.id}/annotation-model-versions")
        assert response.status_code == 200, response.text
        items = {item["id"]: item for item in response.json()["items"]}
        assert set(items) == {str(approved.id), str(pending.id), str(onnx_version.id)}
        assert items[str(approved.id)]["selectable"] is True
        assert items[str(approved.id)]["ineligible_reason"] is None
        assert items[str(pending.id)]["selectable"] is False
        assert items[str(pending.id)]["ineligible_reason"] == "MODEL_VERSION_NOT_ENABLED"
        assert items[str(onnx_version.id)]["selectable"] is False
        assert items[str(onnx_version.id)]["ineligible_reason"] == "MODEL_SOURCE_UNSUPPORTED"
    finally:
        app.dependency_overrides.clear()
        db.close()
        engine.dispose()


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


def test_project_dataset_versions_lists_generic_creation_inputs():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine, expire_on_commit=False)()
    user = User(username=f"dataset-version-{uuid.uuid4().hex}", password_hash="hash")
    db.add(user)
    db.flush()
    project = Project(name="Generic creation project", owner_id=user.id)
    db.add(project)
    db.flush()
    version = DatasetVersion(
        project_id=project.id,
        operator_id=user.id,
        version=2,
        row_count=3,
        column_count=2,
        content_hash="sha256:version",
        schema_hash="sha256:schema",
    )
    db.add(version)
    db.flush()
    db.add(DatasetSchemaColumn(dataset_version_id=version.id, name="feature", position=0, dtype="float", nullable=False))
    db.commit()
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: user
    try:
        response = TestClient(app).get(f"/api/projects/{project.id}/dataset-versions")
        assert response.status_code == 200, response.text
        assert response.json()["items"] == [{
            "id": str(version.id),
            "project_id": str(project.id),
            "source_name": None,
            "version": 2,
            "status": "ready",
            "row_count": 3,
            "column_count": 2,
            "columns": [{"name": "feature", "dtype": "float", "nullable": False, "position": 0}],
        }]
    finally:
        app.dependency_overrides.clear()
        db.close()
        engine.dispose()
        engine.dispose()


@pytest.mark.parametrize("visible_columns", [["missing"], ["feature", "feature"]])
def test_task_creation_rejects_non_source_or_duplicate_visible_columns(visible_columns):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine, expire_on_commit=False)()
    user = User(username=f"visible-columns-{uuid.uuid4().hex}", password_hash="hash")
    db.add(user)
    db.flush()
    project = Project(name="Visible column contract", owner_id=user.id)
    db.add(project)
    db.flush()
    version = DatasetVersion(
        project_id=project.id,
        operator_id=user.id,
        version=1,
        row_count=1,
        column_count=1,
        content_hash="sha256:visible-data",
        schema_hash="sha256:visible-schema",
    )
    schema = LabelSchema(project_id=project.id, name="visible-labels", version=1, status="active")
    db.add_all([version, schema])
    db.flush()
    db.add_all([
        DatasetSchemaColumn(dataset_version_id=version.id, name="feature", position=0, dtype="float", nullable=False),
        DatasetSample(dataset_version_id=version.id, sample_id="visible-1", row_index=0, values={"feature": 1.0}),
        LabelColumn(schema_id=schema.id, machine_key="label", display_name="Label", ordinal=0, value_type="string"),
    ])
    db.commit()
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: user
    try:
        request_id = str(uuid.uuid4())
        response = TestClient(app).post(
            "/api/annotation-tasks",
            headers={"X-Request-ID": request_id, "Idempotency-Key": f"visible-{request_id}"},
            json={
                "project_id": str(project.id),
                "dataset_version_id": str(version.id),
                "label_schema_id": str(schema.id),
                "mode": "manual",
                "visible_columns": visible_columns,
            },
        )

        assert response.status_code == 422, response.text
        assert response.json()["detail"]["code"] == "VISIBLE_COLUMN_INVALID"
        assert db.query(GenericAnnotationTask).count() == 0
    finally:
        app.dependency_overrides.clear()
        db.close()
        engine.dispose()


def test_manual_task_rejects_a_source_label_column_with_a_different_type():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine, expire_on_commit=False)()
    user = User(username=f"source-label-type-{uuid.uuid4().hex}", password_hash="hash")
    db.add(user)
    db.flush()
    project = Project(name="Source label type contract", owner_id=user.id)
    db.add(project)
    db.flush()
    version = DatasetVersion(
        project_id=project.id,
        operator_id=user.id,
        version=1,
        row_count=1,
        column_count=1,
        content_hash="sha256:source-label-data",
        schema_hash="sha256:source-label-schema",
    )
    schema = LabelSchema(project_id=project.id, name="source-labels", version=1, status="active")
    db.add_all([version, schema])
    db.flush()
    db.add_all([
        DatasetSchemaColumn(dataset_version_id=version.id, name="score", position=0, dtype="float64", nullable=False),
        DatasetSample(dataset_version_id=version.id, sample_id="source-label-1", row_index=0, values={"score": 1.0}),
        LabelColumn(schema_id=schema.id, machine_key="score", display_name="Score", ordinal=0, value_type="string"),
    ])
    db.commit()
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: user
    try:
        request_id = str(uuid.uuid4())
        response = TestClient(app).post(
            "/api/annotation-tasks",
            headers={"X-Request-ID": request_id, "Idempotency-Key": f"source-label-{request_id}"},
            json={
                "project_id": str(project.id),
                "dataset_version_id": str(version.id),
                "label_schema_id": str(schema.id),
                "mode": "manual",
            },
        )

        assert response.status_code == 422, response.text
        assert response.json()["detail"]["code"] == "LABEL_SOURCE_COLUMN_TYPE_MISMATCH"
        assert db.query(GenericAnnotationTask).count() == 0
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
    version = DatasetVersion(project_id=project.id, operator_id=user.id, version=1, row_count=2, column_count=2, content_hash="sha256:data", schema_hash="sha256:schema")
    db.add(version)
    db.flush()
    db.add_all([
        DatasetSchemaColumn(dataset_version_id=version.id, name="feature", position=0, dtype="float", nullable=False),
        DatasetSchemaColumn(dataset_version_id=version.id, name="result", position=1, dtype="string", nullable=True),
        DatasetSample(dataset_version_id=version.id, sample_id="s-1", row_index=0, values={"feature": 1}),
        DatasetSample(dataset_version_id=version.id, sample_id="s-2", row_index=1, values={"feature": 2}),
    ])
    model_version, source_artifact = _enabled_annotation_model(db, project, user)
    db.commit()
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: user
    client = TestClient(app)
    try:
        request_id = str(uuid.uuid4())
        response = client.post("/api/annotation-tasks", headers={"X-Request-ID": request_id, "Idempotency-Key": str(uuid.uuid4())}, json={"project_id": str(project.id), "dataset_version_id": str(version.id), "model_version_id": str(model_version.id), "mode": "automatic", "sample_scope": {"kind": "ids", "sample_ids": ["s-2"]}, "visible_columns": ["feature"], "instructions": "Review selected rows", "configuration": {"strategy": "model"}, "label_snapshot": {"client": "ignored"}})
        assert response.status_code == 201, response.text
        snapshot = response.json()["task_snapshot"]
        assert snapshot["dataset_version"]["id"] == str(version.id)
        assert snapshot["scope"]["storage"] == "annotation_task_scope_samples"
        assert snapshot["scope"]["sample_count"] == 1
        created_task_id = uuid.UUID(response.json()["id"])
        persisted_scope = db.query(AnnotationTaskScopeSample).filter_by(
            task_id=created_task_id,
            task_revision=0,
        ).one()
        assert (persisted_scope.sample_id, persisted_scope.row_index) == ("s-2", 1)
        assert snapshot["visible_columns"] == ["feature"]
        assert [column["machine_key"] for column in snapshot["label_schema"]["columns"]] == ["result", "score"]
        assert [column["value_type"] for column in snapshot["label_schema"]["columns"]] == ["string", "int"]
        assert all(column["required"] is True for column in snapshot["label_schema"]["columns"])
        assert snapshot["instructions"] == "Review selected rows"
        assert snapshot["configuration"]["strategy"] == "model"
        assert snapshot["configuration"]["model_version_id"] == str(model_version.id)
        assert snapshot["configuration"]["model_artifact_id"] == str(source_artifact.id)
        assert [column["machine_key"] for column in snapshot["configuration"]["model_output_contract"]["columns"]] == ["result", "score"]
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
    version = DatasetVersion(project_id=project.id, operator_id=user.id, version=1, row_count=1, column_count=1, content_hash="sha256:config-data", schema_hash="sha256:config-schema")
    db.add(version); db.flush()
    db.add_all([
        DatasetSchemaColumn(dataset_version_id=version.id, name="feature", position=0, dtype="float", nullable=False),
        DatasetSample(dataset_version_id=version.id, sample_id="sample-1", row_index=0, values={"feature": 1.0}),
    ])
    model_version, _source_artifact = _enabled_annotation_model(db, project, user, columns=[{"name": "label", "dtype": "object", "task": "classification"}])
    db.commit()
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: user
    client = TestClient(app)
    try:
        headers = {"X-Request-ID": str(uuid.uuid4()), "Idempotency-Key": str(uuid.uuid4())}
        created = client.post("/api/annotation-tasks", headers=headers, json={"project_id": str(project.id), "dataset_version_id": str(version.id), "model_version_id": str(model_version.id), "mode": "automatic", "sample_scope": {"kind": "all"}, "configuration": {"strategy": "model"}})
        assert created.status_code == 201, created.text
        task_id = created.json()["id"]
        old_preview = client.post(f"/api/annotation-tasks/{task_id}/preview", json={"task_revision": 0, "config_hash": created.json()["task_snapshot"]["config_hash"]})
        assert old_preview.status_code == 202
        db.get(GenericAnnotationTask, uuid.UUID(task_id)).status = "failed"
        db.commit()
        updated = client.put(f"/api/annotation-tasks/{task_id}/configuration", json={"task_revision": 0, "visible_columns": ["feature"], "instructions": "updated", "configuration": {"strategy": "model"}})
        assert updated.status_code == 200, updated.text
        assert updated.json()["task_revision"] == 1
        assert updated.json()["task_snapshot"]["config_hash"] != created.json()["task_snapshot"]["config_hash"]
        revision_scope = db.query(AnnotationTaskScopeSample).filter_by(
            task_id=uuid.UUID(task_id),
            task_revision=1,
        ).order_by(AnnotationTaskScopeSample.row_index.asc()).all()
        assert [(item.sample_id, item.row_index) for item in revision_scope] == [("sample-1", 0)]
        refreshed = client.get(f"/api/annotation-tasks?project_id={project.id}")
        assert refreshed.status_code == 200
        assert refreshed.json()["items"][0]["task_revision"] == 1
        assert refreshed.json()["items"][0]["task_snapshot"]["config_hash"] == updated.json()["task_snapshot"]["config_hash"]
        invalid_visible_columns = client.put(
            f"/api/annotation-tasks/{task_id}/configuration",
            json={
                "task_revision": 1,
                "visible_columns": ["not-a-source-column"],
                "instructions": "updated",
                "configuration": {"strategy": "model"},
            },
        )
        assert invalid_visible_columns.status_code == 422
        assert invalid_visible_columns.json()["detail"]["code"] == "VISIBLE_COLUMN_INVALID"
        assert db.get(GenericAnnotationTask, uuid.UUID(task_id)).task_revision == 1
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
    task = GenericAnnotationTask(project_id=project.id, dataset_version_id=uuid.uuid4(), label_schema_id=schema.id, owner_id=user.id, mode="manual", status="draft", task_revision=0, sample_scope={"kind": "all", "sample_count": 0})
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
                "configuration": {
                    "clustering": True,
                    "cluster_discovery": True,
                    "feature_importance": [1.0],
                    "cluster_ids": {"strategy-sample": 0},
                    "model_outputs": {"strategy-sample": {"label": "a"}},
                },
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
        assert detail.json()["summary"]["strategy"] == "cluster_discovery"
        assert detail.json()["summary"]["needs_review_count"] == 0
        assert detail.json()["summary"]["configuration_complete"] is False
        assert detail.json()["summary"]["clusters"] == [{"cluster_id": 0, "sample_count": 1}]
        assert "provenance" not in detail.json()["summary"]
    finally:
        app.dependency_overrides.clear()
        db.close()
        engine.dispose()


def test_automatic_task_rejects_client_supplied_model_artifact():
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
    version = DatasetVersion(project_id=project.id, operator_id=user.id, version=1, row_count=1, column_count=1, content_hash="sha256:artifact-contract", schema_hash="sha256:artifact-contract-schema")
    foreign_artifact = Artifact(project_id=other_project.id, name="foreign-model", type="model", storage_path="missing.joblib", format="joblib")
    db.add_all([version, foreign_artifact])
    db.flush()
    db.add(DatasetSchemaColumn(dataset_version_id=version.id, name="feature", position=0, dtype="float", nullable=False))
    db.add(DatasetSample(dataset_version_id=version.id, sample_id="artifact-contract-sample", row_index=0, values={"feature": 1.0}))
    model_version, _source_artifact = _enabled_annotation_model(db, project, user, columns=[{"name": "label", "dtype": "object", "task": "classification"}])
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
                "model_version_id": str(model_version.id),
                "mode": "automatic",
                "sample_scope": {"kind": "all"},
                "configuration": {"model_artifact_id": str(foreign_artifact.id), "clustering": False, "strategy": "model"},
            },
        )
        assert response.status_code == 422
        assert response.json()["detail"]["code"] == "AUTOMATIC_CONFIG_INTERNAL_FIELD"
    finally:
        app.dependency_overrides.clear()
        db.close()
        engine.dispose()


def test_automatic_task_rejects_invalid_strategy_before_persisting():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine, expire_on_commit=False)()
    user = User(username=f"strategy-contract-{uuid.uuid4().hex}", password_hash="hash")
    db.add(user)
    db.flush()
    project = Project(name="Strategy contract project", owner_id=user.id)
    db.add(project)
    db.flush()
    version = DatasetVersion(
        project_id=project.id,
        operator_id=user.id,
        version=1,
        row_count=1,
        column_count=1,
        content_hash="sha256:strategy-contract",
        schema_hash="sha256:strategy-contract-schema",
    )
    db.add(version)
    db.flush()
    db.add(DatasetSample(dataset_version_id=version.id, sample_id="strategy-contract-sample", row_index=0, values={"feature": 1.0}))
    model_version, _source_artifact = _enabled_annotation_model(db, project, user, columns=[{"name": "label", "dtype": "object", "task": "classification"}])
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
                "model_version_id": str(model_version.id),
                "mode": "automatic",
                "sample_scope": {"kind": "all"},
                "configuration": {
                    "clustering": True,
                    "strategy": "cluster_rule",
                    "other_values": {},
                    "rules": [{"id": "rule-1", "when": {"column": "feature", "operator": "eq", "value": 1}, "values": {"label": "hit"}}],
                },
            },
        )
        assert response.status_code == 422
        assert response.json()["detail"]["code"] == "CLUSTER_FALLBACK_REQUIRED"
        assert db.query(GenericAnnotationTask).count() == 0
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
    task = GenericAnnotationTask(project_id=project.id, dataset_version_id=uuid.uuid4(), label_schema_id=schema.id, owner_id=user.id, mode="manual", status="draft", task_revision=0, sample_scope={"kind": "all", "sample_count": 0})
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
        task_model = GenericAnnotationTask(project_id=project.id, dataset_version_id=uuid.uuid4(), label_schema_id=schema.id, owner_id=owner.id, mode="manual", status="draft", task_revision=0, sample_scope={"kind": "all", "sample_count": 0})
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


def test_publish_route_returns_and_replays_durable_command_receipt():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine, expire_on_commit=False)()
    user = User(username=f"publish-route-{uuid.uuid4().hex}", password_hash="hash")
    db.add(user)
    db.flush()
    project = Project(name="Publish route", owner_id=user.id)
    db.add(project)
    db.flush()
    schema = LabelSchema(project_id=project.id, name="publish-labels", version=1, status="active")
    db.add(schema)
    db.flush()
    db.add(LabelColumn(schema_id=schema.id, machine_key="label", display_name="Label", ordinal=0, value_type="string"))
    task = GenericAnnotationTask(
        project_id=project.id,
        dataset_version_id=uuid.uuid4(),
        label_schema_id=schema.id,
        owner_id=user.id,
        mode="manual",
        status="preview_ready",
        task_revision=0,
        sample_scope={"kind": "ids", "sample_ids": ["s-1"]},
        task_snapshot={"sample_ids": ["s-1"], "config_hash": "sha256:publish-route"},
    )
    db.add(task)
    db.flush()
    preview = AnnotationTaskPreview(
        task_id=task.id,
        task_revision=0,
        config_hash="sha256:publish-route",
        status="completed",
        progress=100,
        created_by=user.id,
        summary={"configuration_complete": True, "needs_review_count": 0},
    )
    db.add(preview)
    db.commit()
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: user
    client = TestClient(app)
    request_id = str(uuid.uuid4())
    headers = {"X-Request-ID": request_id, "Idempotency-Key": "publish-route-key"}
    try:
        first = client.post(
            f"/api/annotation-tasks/{task.id}/publish",
            headers=headers,
            json={"task_revision": 0, "preview_id": str(preview.id)},
        )
        assert first.status_code == 202, first.text
        assert first.json()["status"] == "awaiting_annotation"
        assert first.json()["operation_id"]

        repeated = client.post(
            f"/api/annotation-tasks/{task.id}/publish",
            headers=headers,
            json={"task_revision": 0, "preview_id": str(preview.id)},
        )
        assert repeated.status_code == 202, repeated.text
        assert repeated.json() == first.json()

        conflict = client.post(
            f"/api/annotation-tasks/{task.id}/publish",
            headers=headers,
            json={"task_revision": 1, "preview_id": str(preview.id)},
        )
        assert conflict.status_code == 409
        assert conflict.json()["detail"]["code"] == "IDEMPOTENCY_CONFLICT"
    finally:
        app.dependency_overrides.clear()
        db.close()
        engine.dispose()


def test_generic_task_name_round_trip_and_configuration_update():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine, expire_on_commit=False)()
    user = User(username=f"name-roundtrip-{uuid.uuid4().hex}", password_hash="hash")
    db.add(user)
    db.flush()
    project = Project(name="Name round trip", owner_id=user.id)
    db.add(project)
    db.flush()
    schema = LabelSchema(project_id=project.id, name="name-labels", version=1, status="active")
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
        created = client.post(
            "/api/annotation-tasks",
            headers={"X-Request-ID": str(uuid.uuid4()), "Idempotency-Key": f"name-{uuid.uuid4()}"},
            json={
                "project_id": str(project.id),
                "dataset_version_id": str(version.id),
                "label_schema_id": str(schema.id),
                "name": "  Q3 复检任务  ",
                "completion_criteria": "全部样本必填标签填写完整",
                "due_at": "2026-09-30T23:59:59+00:00",
                "mode": "manual",
                "sample_scope": {"kind": "all"},
            },
        )
        assert created.status_code == 201, created.text
        assert created.json()["name"] == "Q3 复检任务"
        assert created.json()["completion_criteria"] == "全部样本必填标签填写完整"
        assert created.json()["due_at"] is not None
        assert created.json()["due_at"].startswith("2026-09-30")
        assert created.json()["task_snapshot"]["completion_criteria"] == "全部样本必填标签填写完整"
        task_id = created.json()["id"]

        listed = client.get("/api/annotation-tasks", params={"project_id": str(project.id)})
        assert listed.status_code == 200, listed.text
        items = listed.json()["items"]
        assert [item["name"] for item in items] == ["Q3 复检任务"]
        assert items[0]["created_at"]
        assert items[0]["completion_criteria"] == "全部样本必填标签填写完整"
        assert items[0]["due_at"] is not None

        updated = client.put(
            f"/api/annotation-tasks/{task_id}/configuration",
            json={
                "task_revision": 0,
                "name": "Q3 复检任务 v2",
                "visible_columns": ["feature"],
                "instructions": "updated",
                "completion_criteria": "全部样本标签经复核",
                "due_at": "2026-10-15T23:59:59+00:00",
                "configuration": {},
            },
        )
        assert updated.status_code == 200, updated.text
        assert updated.json()["name"] == "Q3 复检任务 v2"
        assert updated.json()["completion_criteria"] == "全部样本标签经复核"
        assert updated.json()["due_at"] is not None
        assert updated.json()["due_at"].startswith("2026-10-15")
        assert updated.json()["task_revision"] == 1
        assert updated.json()["status"] == "draft"
    finally:
        app.dependency_overrides.clear()
        db.close()
        engine.dispose()
