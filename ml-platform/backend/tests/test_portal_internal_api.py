from __future__ import annotations

from datetime import datetime, timezone
import uuid

import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import settings
from app.database import Base, get_db
from app.main import app
from app.models.annotator import AnnotatorAccount, ProjectAnnotatorGrant
from app.models.data_version import DatasetSample, DatasetSchemaColumn, DatasetVersion
from app.models.labeling import (
    AnnotationAssignment,
    AnnotationAssignmentSample,
    AnnotationComment,
    AnnotationRevision,
    LabelColumn,
    LabelSchema,
)
from app.models.platform_models import GenericAnnotationTask
from app.models.project import Project
from app.models.user import User
from app.models.annotator import AnnotatorSubjectMapping


@pytest.fixture()
def portal_fixture():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine, expire_on_commit=False)()

    admin = User(username=f"portal-admin-{uuid.uuid4().hex}", password_hash="hash", role="admin")
    db.add(admin)
    db.flush()
    project = Project(name="Portal project", owner_id=admin.id)
    db.add(project)
    db.flush()

    dataset = DatasetVersion(
        project_id=project.id,
        operator_id=admin.id,
        version=1,
        row_count=2,
        column_count=1,
        content_hash="sha256:dataset",
        schema_hash="sha256:schema",
        parse_contract={"source_format": "json"},
    )
    db.add(dataset)
    db.flush()
    db.add(
        DatasetSchemaColumn(
            dataset_version_id=dataset.id,
            name="feature",
            position=0,
            dtype="int64",
            nullable=False,
        )
    )
    db.add_all(
        [
            DatasetSample(dataset_version_id=dataset.id, sample_id="sample-1", row_index=0, values={"feature": 1}),
            DatasetSample(dataset_version_id=dataset.id, sample_id="sample-2", row_index=1, values={"feature": 2}),
        ]
    )

    schema = LabelSchema(project_id=project.id, name="portal-labels", version=1, status="active")
    db.add(schema)
    db.flush()
    db.add(
        LabelColumn(
            schema_id=schema.id,
            machine_key="label",
            display_name="Label",
            ordinal=0,
            value_type="string",
            required=True,
        )
    )

    subject_id = uuid.uuid4()
    db.add(
        AnnotatorAccount(
            subject_id=subject_id,
            username=f"annotator-{uuid.uuid4().hex}",
            password_hash="hash",
            status="active",
        )
    )
    db.add(
        ProjectAnnotatorGrant(
            project_id=project.id,
            subject_id=subject_id,
            status="active",
            granted_by=admin.id,
        )
    )
    db.add(
        AnnotatorSubjectMapping(
            subject_id=subject_id,
            platform_principal_id=admin.id,
            created_by=admin.id,
        )
    )

    task = GenericAnnotationTask(
        project_id=project.id,
        dataset_version_id=dataset.id,
        label_schema_id=schema.id,
        owner_id=admin.id,
        mode="manual",
        status="awaiting_annotation",
        task_revision=3,
        sample_scope={"kind": "ids", "sample_ids": ["sample-1", "sample-2"]},
        label_snapshot={"columns": [{"machine_key": "label", "value_type": "string", "required": True}]},
        task_snapshot={"sample_ids": ["sample-1", "sample-2"], "visible_columns": ["feature"]},
    )
    db.add(task)
    db.flush()
    assignment = AnnotationAssignment(
        task_id=task.id,
        annotator_subject_id=subject_id,
        sample_scope={"kind": "ids", "sample_ids": ["sample-1", "sample-2"]},
        scope_hash="sha256:portal-scope",
        state="pending",
        task_revision=3,
        last_edit_revision=3,
        created_by=admin.id,
    )
    db.add(assignment)
    db.flush()
    db.add_all(
        [
            AnnotationAssignmentSample(
                assignment_id=assignment.id,
                sample_id="sample-1",
                revision_no=3,
                values={"label": "old-1"},
            ),
            AnnotationAssignmentSample(
                assignment_id=assignment.id,
                sample_id="sample-2",
                revision_no=3,
                values={"label": "old-2"},
            ),
        ]
    )
    db.commit()

    app.dependency_overrides[get_db] = lambda: db
    client = TestClient(app)
    try:
        yield {
            "db": db,
            "client": client,
            "project_id": project.id,
            "task_id": task.id,
            "subject_id": subject_id,
            "scope_hash": assignment.scope_hash,
        }
    finally:
        app.dependency_overrides.clear()
        db.close()
        engine.dispose()


def _token(*, project_id: uuid.UUID | str, subject_id: uuid.UUID, scopes: list[str]) -> str:
    now = datetime.now(timezone.utc)
    return jwt.encode(
        {
            "iss": settings.annotator_service_issuer,
            "aud": settings.annotator_service_audience,
            "sub": "annotator-portal",
            "project_id": str(project_id),
            "annotator_subject_id": str(subject_id),
            "scope": " ".join(scopes),
            "nonce": "portal-test-nonce",
            "iat": now,
            "exp": now.replace(microsecond=0).timestamp() + 60,
        },
        settings.resolved_annotator_service_secret.get_secret_value(),
        algorithm=settings.annotator_service_algorithm,
    )


def _headers(token: str, **extra: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}", **extra}


def test_internal_portal_task_and_sample_reads_are_subject_scoped(portal_fixture):
    token = _token(
        project_id=portal_fixture["project_id"],
        subject_id=portal_fixture["subject_id"],
        scopes=["assignment:read"],
    )
    client = portal_fixture["client"]

    tasks = client.get("/api/internal/portal/tasks", headers=_headers(token))
    assert tasks.status_code == 200, tasks.text
    assert tasks.json()["items"][0]["id"] == str(portal_fixture["task_id"])
    assert tasks.json()["items"][0]["assignment_id"]

    samples = client.get(
        f"/api/internal/portal/tasks/{portal_fixture['task_id']}/samples?limit=1",
        headers=_headers(token),
    )
    assert samples.status_code == 200, samples.text
    assert samples.json()["items"][0] == {
        "sample_id": "sample-1",
        "values": {"feature": 1},
        "labels": {"label": "old-1"},
        "revision": 3,
    }
    assert samples.json()["next_cursor"]


def test_internal_portal_label_write_returns_complete_revision_conflict(portal_fixture):
    token = _token(
        project_id=portal_fixture["project_id"],
        subject_id=portal_fixture["subject_id"],
        scopes=["assignment:write"],
    )
    client = portal_fixture["client"]
    path = f"/api/internal/portal/tasks/{portal_fixture['task_id']}/samples/sample-1/labels"

    saved = client.put(
        path,
        headers=_headers(token),
        json={"values": {"label": "new"}, "base_revision": 3},
    )
    assert saved.status_code == 200, saved.text
    assert saved.json() == {"values": {"label": "new"}, "revision": 4}

    conflict = client.put(
        path,
        headers=_headers(token),
        json={"values": {"label": "stale"}, "base_revision": 3},
    )
    assert conflict.status_code == 409, conflict.text
    assert conflict.json()["detail"]["code"] == "REVISION_CONFLICT"
    assert conflict.json()["detail"]["current_values"] == {"label": "new"}


def test_internal_portal_bulk_confirm_and_return_are_idempotent(portal_fixture):
    read_write = _token(
        project_id=portal_fixture["project_id"],
        subject_id=portal_fixture["subject_id"],
        scopes=["assignment:write", "assignment:return"],
    )
    client = portal_fixture["client"]
    task_path = f"/api/internal/portal/tasks/{portal_fixture['task_id']}"

    bulk = client.post(
        f"{task_path}/bulk-labels",
        headers=_headers(read_write),
        json={
            "items": [
                {"sample_id": "sample-1", "values": {"label": "bulk-1"}, "base_revision": 3},
                {"sample_id": "sample-2", "values": {"label": "bulk-2"}, "base_revision": 3},
            ]
        },
    )
    assert bulk.status_code == 200, bulk.text
    assert [item["revision"] for item in bulk.json()["items"]] == [4, 4]

    confirmed = client.post(
        f"{task_path}/confirm",
        headers=_headers(read_write),
        json={"task_revision": 4, "scope_hash": portal_fixture["scope_hash"]},
    )
    assert confirmed.status_code == 200, confirmed.text

    first = client.post(
        f"{task_path}/return",
        headers=_headers(read_write, **{"Idempotency-Key": "portal-return-1"}),
        json={"task_revision": 4, "scope_hash": portal_fixture["scope_hash"]},
    )
    second = client.post(
        f"{task_path}/return",
        headers=_headers(read_write, **{"Idempotency-Key": "portal-return-1"}),
        json={"task_revision": 4, "scope_hash": portal_fixture["scope_hash"]},
    )
    assert first.status_code == second.status_code == 200
    assert first.json()["return_batch_id"] == second.json()["return_batch_id"]


def test_internal_portal_bulk_labels_are_atomic_on_late_conflict(portal_fixture):
    token = _token(
        project_id=portal_fixture["project_id"],
        subject_id=portal_fixture["subject_id"],
        scopes=["assignment:write"],
    )
    client = portal_fixture["client"]
    task_path = f"/api/internal/portal/tasks/{portal_fixture['task_id']}"

    response = client.post(
        f"{task_path}/bulk-labels",
        headers=_headers(token),
        json={
            "items": [
                {"sample_id": "sample-1", "values": {"label": "first"}, "base_revision": 3},
                {"sample_id": "sample-2", "values": {"label": "stale"}, "base_revision": 99},
            ]
        },
    )
    assert response.status_code == 409, response.text
    assert portal_fixture["db"].query(AnnotationAssignmentSample).filter_by(
        sample_id="sample-1"
    ).one().values == {"label": "old-1"}


def test_internal_portal_supports_task_level_comments(portal_fixture):
    token = _token(
        project_id=portal_fixture["project_id"],
        subject_id=portal_fixture["subject_id"],
        scopes=["comment:write"],
    )
    client = TestClient(app, raise_server_exceptions=False)
    response = client.post(
        "/api/internal/portal/comments",
        headers=_headers(token),
        json={"task_id": str(portal_fixture["task_id"]), "content": "Task-level note"},
    )
    assert response.status_code == 201, response.text
    assert response.json()["sample_id"] is None
    assert portal_fixture["db"].query(AnnotationComment).filter_by(sample_id=None).count() == 1


def test_internal_portal_rejects_explicit_cross_project_token(portal_fixture):
    token = _token(
        project_id=uuid.uuid4(),
        subject_id=portal_fixture["subject_id"],
        scopes=["assignment:read"],
    )
    response = portal_fixture["client"].get(
        f"/api/internal/portal/tasks/{portal_fixture['task_id']}",
        headers=_headers(token),
    )
    assert response.status_code == 403, response.text
    assert response.json()["detail"]["code"] == "SERVICE_PROJECT_FORBIDDEN"


def test_internal_portal_comment_list_preserves_total_and_revision_reference(portal_fixture):
    db = portal_fixture["db"]
    task_id = portal_fixture["task_id"]
    subject_id = portal_fixture["subject_id"]
    db.add(AnnotationRevision(
        task_id=task_id,
        sample_id="sample-1",
        schema_id=db.query(LabelSchema).filter_by(project_id=portal_fixture["project_id"]).one().id,
        revision_no=3,
        base_revision=2,
        values={"label": "old-1"},
        author_id=db.query(User).filter(User.username.like("portal-admin-%")).first().id,
    ))
    db.flush()
    revision = db.query(AnnotationRevision).filter_by(task_id=task_id, sample_id="sample-1").one()
    db.add(AnnotationComment(task_id=task_id, sample_id="sample-1", revision_id=revision.id, author_id=revision.author_id, body="revision note"))
    db.add(AnnotationComment(task_id=task_id, sample_id=None, author_id=revision.author_id, body="task note"))
    db.commit()
    token = _token(project_id=portal_fixture["project_id"], subject_id=subject_id, scopes=["comment:read"])
    response = portal_fixture["client"].get("/api/internal/portal/comments?limit=1", headers=_headers(token))
    assert response.status_code == 200, response.text
    assert response.json()["total"] == 2
    assert response.json()["items"][0]["related_revision"] == 3
