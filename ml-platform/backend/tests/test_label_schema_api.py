import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.auth import get_current_user
from app.database import Base, get_db
from app.main import app
from app.models.data_version import DatasetSample, DatasetSchemaColumn, DatasetVersion
from app.models.labeling import (
    AnnotationRevision,
    AnnotationSampleCurrent,
    AnnotationTaskLabel,
    LabelColumn,
    LabelSchema,
)
from app.models.project import Project
from app.models.user import User


@pytest.fixture()
def api_context():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, expire_on_commit=False)()
    owner = User(username=f"label-owner-{uuid.uuid4().hex}", password_hash="hash")
    other = User(username=f"label-other-{uuid.uuid4().hex}", password_hash="hash")
    project = Project(name="Label API project", owner_id=owner.id)
    session.add_all([owner, other])
    session.flush()
    project.owner_id = owner.id
    session.add(project)
    session.commit()
    app.dependency_overrides[get_db] = lambda: session
    app.dependency_overrides[get_current_user] = lambda: owner
    client = TestClient(app)
    try:
        yield client, session, owner, other, project
    finally:
        app.dependency_overrides.clear()
        session.close()
        engine.dispose()


def _schema_payload(project_id):
    return {
        "project_id": str(project_id),
        "name": "quality-labels",
        "columns": [
            {"machine_key": "status", "display_name": "Status", "value_type": "string", "required": True, "enum_values": ["ok", "ng"]},
            {"machine_key": "score", "display_name": "Score", "value_type": "int", "required": True},
        ],
    }


def test_schema_create_read_and_non_owner_access_is_denied(api_context):
    client, _, _, other, project = api_context
    created = client.post("/api/annotations/label-schemas", json=_schema_payload(project.id))
    assert created.status_code == 201, created.text
    schema_id = created.json()["id"]
    assert client.get(f"/api/annotations/label-schemas/{schema_id}").status_code == 200

    app.dependency_overrides[get_current_user] = lambda: other
    denied = client.get(f"/api/annotations/label-schemas/{schema_id}")
    assert denied.status_code == 404


def test_generic_task_creation_freezes_schema_binding(api_context):
    client, db, owner, _, project = api_context
    created = client.post("/api/annotations/label-schemas", json=_schema_payload(project.id))
    schema_id = created.json()["id"]
    version = DatasetVersion(
        project_id=project.id,
        operator_id=owner.id,
        version=1,
        row_count=1,
        column_count=1,
        content_hash="sha256:label-schema-api-data",
        schema_hash="sha256:label-schema-api-schema",
    )
    db.add(version)
    db.flush()
    db.add_all([
        DatasetSchemaColumn(
            dataset_version_id=version.id,
            name="feature",
            position=0,
            dtype="float",
            nullable=False,
        ),
        DatasetSample(
            dataset_version_id=version.id,
            sample_id="label-schema-api-sample-1",
            row_index=0,
            values={"feature": 1.0},
        ),
    ])
    db.commit()
    request_id = str(uuid.uuid4())
    response = client.post(
        "/api/annotation-tasks",
        headers={"X-Request-ID": request_id, "Idempotency-Key": f"label-task-{uuid.uuid4()}"},
        json={
            "project_id": str(project.id),
            "dataset_version_id": str(version.id),
            "label_schema_id": schema_id,
            "mode": "manual",
            "sample_scope": {"kind": "all"},
        },
    )
    assert response.status_code == 201, response.text
    binding = db.query(AnnotationTaskLabel).filter_by(task_id=uuid.UUID(response.json()["id"])).one()
    assert str(binding.schema_id) == schema_id
    assert [column["machine_key"] for column in binding.schema_snapshot["columns"]] == ["status", "score"]


def test_sample_api_rejects_task_without_schema_binding(api_context):
    client, db, owner, _, project = api_context
    schema = LabelSchema(project_id=project.id, name="bound", version=1, status="active")
    db.add(schema)
    db.flush()
    db.add_all([
        LabelColumn(schema_id=schema.id, machine_key="status", display_name="Status", ordinal=0, value_type="string", required=True),
        AnnotationSampleCurrent(task_id=uuid.uuid4(), sample_id="sample-1", schema_id=schema.id, values={}, revision_no=0),
    ])
    db.commit()
    task_id = db.query(AnnotationSampleCurrent).first().task_id
    response = client.get(f"/api/annotations/label-schemas/{schema.id}/samples/sample-1", params={"task_id": str(task_id)})
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "LABEL_TASK_SCHEMA_UNBOUND"


def test_revision_conflict_required_and_confirm_success(api_context):
    client, db, owner, _, project = api_context
    schema = LabelSchema(project_id=project.id, name="confirm", version=1, status="active")
    db.add(schema)
    db.flush()
    db.add_all([
        LabelColumn(schema_id=schema.id, machine_key="status", display_name="Status", ordinal=0, value_type="string", required=True),
        LabelColumn(schema_id=schema.id, machine_key="score", display_name="Score", ordinal=1, value_type="int", required=True),
    ])
    task_id = uuid.uuid4()
    db.add(AnnotationTaskLabel(task_id=task_id, schema_id=schema.id, schema_snapshot={"columns": ["status", "score"]}))
    db.add(AnnotationSampleCurrent(task_id=task_id, sample_id="sample-1", schema_id=schema.id, values={}, revision_no=0))
    db.commit()

    missing = client.post(f"/api/annotations/label-schemas/{schema.id}/samples/sample-1/confirm", params={"task_id": str(task_id)})
    assert missing.status_code == 422
    assert missing.json()["detail"]["code"] == "LABEL_REQUIRED_MISSING"

    first = client.put(
        f"/api/annotations/label-schemas/{schema.id}/samples/sample-1",
        params={"task_id": str(task_id)},
        json={"values": {"status": "ok"}, "base_revision": 0},
    )
    assert first.status_code == 200, first.text
    stale = client.put(
        f"/api/annotations/label-schemas/{schema.id}/samples/sample-1",
        params={"task_id": str(task_id)},
        json={"values": {"score": 7}, "base_revision": 0},
    )
    assert stale.status_code == 409
    assert stale.json()["detail"]["code"] == "LABEL_REVISION_CONFLICT"

    complete = client.put(
        f"/api/annotations/label-schemas/{schema.id}/samples/sample-1",
        params={"task_id": str(task_id)},
        json={"values": {"score": 7}, "base_revision": 1},
    )
    assert complete.status_code == 200, complete.text
    confirmed = client.post(f"/api/annotations/label-schemas/{schema.id}/samples/sample-1/confirm", params={"task_id": str(task_id)})
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["action"] == "confirm"
