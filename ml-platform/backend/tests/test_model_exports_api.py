from pathlib import Path
from types import SimpleNamespace
import uuid

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.auth import get_current_user
from app.api.model_exports import router
from app.database import Base, get_db
from app.models.artifact import Artifact
from app.models.model_export import ModelExport
from app.models.model_registry import ModelVersion, RegisteredModel
from app.models.operation import DurableOperation
from app.models.project import Project
from app.models.user import User
from app.services.model_export import build_export_package
from app.tasks.model_export_tasks import execute_model_export


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


def test_export_record_is_bound_to_durable_operation(db):
    export = ModelExport(
        model_version_id=uuid.uuid4(),
        idempotency_scope="model-version:x:task:none:revision:none",
        idempotency_key="export-key",
        request_hash="a" * 64,
        status="queued",
    )
    db.add(export)
    db.flush()
    operation = DurableOperation(
        resource_key=f"model-export:{export.id}",
        idempotency_key=export.idempotency_key,
        state="queued",
        stage="queued",
    )
    db.add(operation)
    db.flush()
    export.operation_id = operation.id
    db.commit()
    assert db.get(ModelExport, export.id).operation_id == operation.id


def test_export_worker_claims_lease_and_fails_closed(monkeypatch, db):
    export = ModelExport(
        model_version_id=uuid.uuid4(),
        idempotency_scope="scope",
        idempotency_key="key",
        request_hash="b" * 64,
        status="queued",
    )
    operation = DurableOperation(resource_key="model-export:test", idempotency_key="key", state="queued", stage="queued")
    db.add_all([export, operation])
    db.flush()
    export.operation_id = operation.id
    db.commit()
    monkeypatch.setattr("app.tasks.model_export_tasks.SessionLocal", lambda: db)
    result = execute_model_export.run(str(export.id))
    assert result["status"] == "failed"
    assert db.get(DurableOperation, operation.id).state == "failed"
    assert db.get(ModelExport, export.id).status == "failed"


def _route_context(db, monkeypatch):
    user = User(username=f"export-user-{uuid.uuid4().hex}", password_hash="hash")
    db.add(user)
    db.flush()
    project = Project(name="export-project", owner_id=user.id)
    db.add(project)
    db.flush()
    artifact = Artifact(project_id=project.id, name="source", type="model", storage_path="missing.joblib")
    registered = RegisteredModel(project_id=project.id, name=f"export-model-{uuid.uuid4().hex}", created_by_id=user.id)
    db.add_all([artifact, registered])
    db.flush()
    version = ModelVersion(
        registered_model_id=registered.id,
        version_number=1,
        source_kind="onnx_artifact",
        source_artifact_id=artifact.id,
        onnx_artifact_id=artifact.id,
        approval_status="approved",
        lifecycle_state="enabled",
        feature_schema=[],
        output_schema={},
        metrics={},
        conversion_metadata={},
        created_by_id=user.id,
    )
    db.add(version)
    db.commit()
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: user
    monkeypatch.setattr("app.api.model_exports.enqueue_model_export", lambda _export_id: None)
    return TestClient(app), user, project, version


def test_create_export_api_creates_matching_durable_operation(db, monkeypatch):
    client, _user, _project, version = _route_context(db, monkeypatch)
    response = client.post(
        f"/api/model-versions/{version.id}/exports",
        headers={"Idempotency-Key": "api-key"},
        json={"model_version_id": str(version.id), "include_runtime": False},
    )
    assert response.status_code == 202
    payload = response.json()
    operation = db.get(DurableOperation, uuid.UUID(payload["operation_id"]))
    assert operation.resource_key == f"model-export:{payload['id']}"
    assert operation.idempotency_key == "api-key"
    assert operation.state == "queued"


def test_download_api_consumes_authorization_once(db, monkeypatch, tmp_path: Path):
    client, user, project, version = _route_context(db, monkeypatch)
    model = tmp_path / "model.joblib"
    model.write_bytes(b"not-used-for-download")
    package = build_export_package(
        SimpleNamespace(
            id=version.id,
            project_id=project.id,
            source_artifact_path=str(model),
            framework="test",
            algorithm="test",
            feature_schema=[],
            output_schema={},
            conversion_metadata={"input_contract": {}},
            approval_status="approved",
            lifecycle_state="enabled",
        ),
        output_dir=tmp_path,
        signing_key="download-test-key",
    )
    export = ModelExport(
        model_version_id=version.id,
        idempotency_scope="download-scope",
        idempotency_key="download-key",
        request_hash="c" * 64,
        status="completed",
        package_path=str(package.path),
        created_by_id=user.id,
    )
    db.add(export)
    db.commit()
    first = client.get(f"/api/model-exports/{export.id}/download")
    second = client.get(f"/api/model-exports/{export.id}/download")
    assert first.status_code == 200
    assert second.status_code == 409
    assert second.json()["detail"]["code"] == "MODEL_EXPORT_DOWNLOAD_ALREADY_USED"
