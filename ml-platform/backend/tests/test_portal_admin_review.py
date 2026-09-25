"""Admin portal review: login, identity resolution and internal admin endpoints."""

from __future__ import annotations

from datetime import datetime, timezone
import uuid

import jwt
import pytest
from fastapi import Request
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import settings
from app.database import Base, get_db
from app.main import app
from app.models.annotator import AnnotatorAccount, AnnotatorSubjectMapping
from app.models.data_version import DatasetSample, DatasetSchemaColumn, DatasetVersion
from app.models.labeling import (
    AnnotationAssignment,
    AnnotationAssignmentSample,
    AnnotationComment,
    AnnotationConfirmation,
    AnnotationReturnBatch,
    AnnotationRevision,
    AnnotationSampleCurrent,
    LabelColumn,
    LabelSchema,
)
from app.models.operation import DurableOperation
from app.models.platform_models import GenericAnnotationTask
from app.models.project import Project
from app.models.user import User
from app.services.annotator_identity import (
    pwd_context,
    resolve_portal_identity,
    service_token_for_project,
    verify_internal_service_token,
)
from app.tasks.annotation_return_tasks import _execute_with_session

ADMIN_PASSWORD = "admin-secret-123"
ANNOTATOR_PASSWORD = "annotator-pass-8"


@pytest.fixture()
def admin_review_fixture():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine, expire_on_commit=False)()

    admin = User(
        username=f"review-admin-{uuid.uuid4().hex}",
        password_hash=pwd_context.hash(ADMIN_PASSWORD),
        role="admin",
    )
    other_admin = User(
        username=f"other-admin-{uuid.uuid4().hex}",
        password_hash=pwd_context.hash(ADMIN_PASSWORD),
        role="admin",
    )
    member = User(
        username=f"member-{uuid.uuid4().hex}",
        password_hash=pwd_context.hash("member-pass-1234"),
        role="annotator",
    )
    db.add_all([admin, other_admin, member])
    db.flush()
    project = Project(name="Admin review project", owner_id=admin.id)
    db.add(project)
    db.flush()

    source = DatasetVersion(
        project_id=project.id,
        operator_id=admin.id,
        version=1,
        row_count=2,
        column_count=1,
        content_hash="sha256:review-source",
        schema_hash="sha256:review-schema",
        parse_contract={"source_format": "csv"},
    )
    db.add(source)
    db.flush()
    db.add(DatasetSchemaColumn(
        dataset_version_id=source.id,
        name="feature",
        position=0,
        dtype="int64",
        nullable=False,
    ))
    db.add_all([
        DatasetSample(dataset_version_id=source.id, sample_id="sample-1", row_index=0, values={"feature": 1, "private": "x"}),
        DatasetSample(dataset_version_id=source.id, sample_id="sample-2", row_index=1, values={"feature": 2}),
    ])
    schema = LabelSchema(project_id=project.id, name="review-labels", version=1, status="active")
    db.add(schema)
    db.flush()
    db.add(LabelColumn(
        schema_id=schema.id,
        machine_key="result",
        display_name="Result",
        ordinal=0,
        value_type="string",
        required=True,
    ))

    subject_id = uuid.uuid4()
    db.add(AnnotatorSubjectMapping(subject_id=subject_id, platform_principal_id=member.id, created_by=admin.id))
    db.add(AnnotatorAccount(
        subject_id=subject_id,
        username=f"annotator-{uuid.uuid4().hex}",
        password_hash=pwd_context.hash(ANNOTATOR_PASSWORD),
        status="active",
    ))

    task_snapshot = {
        "sample_ids": ["sample-1", "sample-2"],
        "visible_columns": ["feature"],
        "instructions": "Review the frozen rubric.",
        "label_schema": {
            "schema_id": str(schema.id),
            "columns": [{
                "machine_key": "result",
                "display_name": "Result",
                "value_type": "string",
                "required": True,
                "enum_values": [],
                "min_value": None,
                "max_value": None,
                "max_length": None,
            }],
        },
    }

    def _task(owner_id, status, *, archived=False, name="Review task"):
        row = GenericAnnotationTask(
            project_id=project.id,
            dataset_version_id=source.id,
            label_schema_id=schema.id,
            owner_id=owner_id,
            name=name,
            mode="manual",
            status=status,
            task_revision=4,
            sample_scope={"kind": "ids", "sample_ids": ["sample-1", "sample-2"]},
            task_snapshot=dict(task_snapshot),
            archived_at=datetime.now(timezone.utc).replace(tzinfo=None) if archived else None,
        )
        db.add(row)
        db.flush()
        return row

    returned_task = _task(admin.id, "returned_pending_acceptance", name="已回传任务")
    fresh_task = _task(admin.id, "awaiting_annotation", name="未回传任务")
    _task(other_admin.id, "returned_pending_acceptance", name="他人任务")
    _task(admin.id, "completed", archived=True, name="归档任务")

    assignment = AnnotationAssignment(
        task_id=returned_task.id,
        annotator_subject_id=subject_id,
        sample_scope={"kind": "ids", "sample_ids": ["sample-1", "sample-2"]},
        scope_hash="sha256:review-scope",
        state="returned_pending_acceptance",
        task_revision=4,
        last_edit_revision=4,
        created_by=admin.id,
    )
    db.add(assignment)
    db.flush()
    values_by_sample = {"sample-1": {"result": "pass"}, "sample-2": {"result": "fail"}}
    db.add_all([
        AnnotationAssignmentSample(assignment_id=assignment.id, sample_id=sample_id, revision_no=4, values=values)
        for sample_id, values in values_by_sample.items()
    ])
    db.add_all([
        AnnotationSampleCurrent(
            task_id=returned_task.id,
            sample_id=sample_id,
            schema_id=schema.id,
            revision_no=4,
            values=values,
        )
        for sample_id, values in values_by_sample.items()
    ])
    revisions = [
        AnnotationRevision(
            task_id=returned_task.id,
            sample_id=sample_id,
            schema_id=schema.id,
            revision_no=4,
            base_revision=3,
            values=values,
            author_id=member.id,
            source="manual",
            action="edit",
        )
        for sample_id, values in values_by_sample.items()
    ]
    db.add_all(revisions)
    db.flush()
    db.add_all([
        AnnotationConfirmation(
            task_id=returned_task.id,
            sample_id=revision.sample_id,
            revision_id=revision.id,
            confirmer_id=member.id,
            action="confirm",
        )
        for revision in revisions
    ])
    batch = AnnotationReturnBatch(
        assignment_id=assignment.id,
        task_revision=4,
        scope_hash=assignment.scope_hash,
        idempotency_key="review-return",
        state="pending",
    )
    db.add(batch)
    db.commit()

    app.dependency_overrides[get_db] = lambda: db
    client = TestClient(app)
    try:
        yield {
            "db": db,
            "client": client,
            "admin": admin,
            "other_admin": other_admin,
            "member": member,
            "subject_id": subject_id,
            "returned_task": returned_task,
            "fresh_task": fresh_task,
            "batch": batch,
        }
    finally:
        app.dependency_overrides.clear()
        db.close()
        engine.dispose()


def _admin_headers(admin_id: uuid.UUID, scope: str = "admin_review:read") -> dict[str, str]:
    token = service_token_for_project(
        None,
        scopes=[scope, "admin_review:read"],
        admin_user_id=admin_id,
    )
    return {"Authorization": f"Bearer {token}"}


def _subject_headers(subject_id: uuid.UUID, scope: str) -> dict[str, str]:
    token = service_token_for_project(None, scopes=[scope], annotator_subject_id=subject_id)
    return {"Authorization": f"Bearer {token}"}


def _freeze_return_batch(db, batch):
    operation = db.get(DurableOperation, batch.operation_id) if batch.operation_id else None
    if operation is None:
        task = db.query(GenericAnnotationTask).filter(
            GenericAnnotationTask.id == db.query(AnnotationAssignment).filter(
                AnnotationAssignment.id == batch.assignment_id,
            ).one().task_id,
        ).one()
        operation = DurableOperation(
            project_id=task.project_id,
            task_id=task.id,
            resource_type="annotation_return",
            resource_key=f"annotation-return:{batch.id}",
            idempotency_key=batch.id.hex,
            state="queued",
            stage="queued",
        )
        db.add(operation)
        db.flush()
        batch.operation_id = operation.id
        db.commit()
    result = _execute_with_session(db, str(batch.id), str(operation.id), "review-test-worker")
    db.refresh(operation)
    assert result["status"] == "completed"
    assert operation.state == "completed"
    return operation


def _login(client: TestClient, username: str, password: str):
    return client.post(
        "/portal/auth/login",
        data={"username": username, "password": password},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )


def _cookie_from(response, name: str = "portal_session") -> str:
    header = response.headers.get("set-cookie", "")
    marker = f"{name}="
    assert marker in header, header
    return header.split(marker, 1)[1].split(";", 1)[0]


# --- login & identity ------------------------------------------------------


def test_admin_portal_login_issues_jwt_cookie_and_me_reports_admin(admin_review_fixture):
    fixture = admin_review_fixture
    client = fixture["client"]
    response = _login(client, fixture["admin"].username, ADMIN_PASSWORD)
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["kind"] == "admin"
    assert payload["user_id"] == str(fixture["admin"].id)
    assert payload["subject_id"] is None
    token = _cookie_from(response, "admin_portal_session")
    me = client.get("/portal/auth/me", cookies={"admin_portal_session": token}, headers={"X-Portal-Viewer": "admin"})
    assert me.status_code == 200, me.text
    assert me.json() == {
        "subject_id": None,
        "username": fixture["admin"].username,
        "kind": "admin",
        "user_id": str(fixture["admin"].id),
    }
    request = Request({"type": "http", "method": "GET", "path": "/", "headers": [(b"cookie", f"admin_portal_session={token}".encode())]})
    identity = resolve_portal_identity(request, fixture["db"], viewer="admin")
    assert identity.kind == "admin"
    assert identity.user_id == fixture["admin"].id


def test_admin_portal_login_rejects_non_admin_and_wrong_password(admin_review_fixture):
    fixture = admin_review_fixture
    client = fixture["client"]
    for username, password in [
        (fixture["member"].username, "member-pass-1234"),
        (fixture["admin"].username, "wrong-password"),
        ("missing-user", ADMIN_PASSWORD),
    ]:
        response = _login(client, username, password)
        assert response.status_code == 401, response.text
        assert response.json()["detail"]["code"] == "INVALID_CREDENTIALS"


def test_annotator_portal_login_and_me_stay_annotator_kind(admin_review_fixture):
    fixture = admin_review_fixture
    client = fixture["client"]
    account = fixture["db"].query(AnnotatorAccount).one()
    response = _login(client, account.username, ANNOTATOR_PASSWORD)
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["kind"] == "annotator"
    assert payload["subject_id"] == str(account.subject_id)
    assert payload["user_id"] is None
    token = _cookie_from(response)
    me = client.get("/portal/auth/me", cookies={"portal_session": token})
    assert me.status_code == 200, me.text
    assert me.json()["kind"] == "annotator"
    assert me.json()["subject_id"] == str(account.subject_id)


def test_annotator_wrong_password_does_not_fall_through_to_admin(admin_review_fixture):
    fixture = admin_review_fixture
    account = fixture["db"].query(AnnotatorAccount).one()
    response = _login(fixture["client"], account.username, "wrong-password")
    assert response.status_code == 401
    assert response.json()["detail"]["code"] == "INVALID_CREDENTIALS"


def test_admin_session_jwt_expiry_is_enforced():
    import app.services.annotator_identity as identity_service

    token = jwt.encode(
        {
            "kind": "portal_admin",
            "sub": str(uuid.uuid4()),
            "username": "expired-admin",
            "iat": datetime.now(timezone.utc),
            "exp": datetime.now(timezone.utc).replace(microsecond=0).timestamp() - 60,
        },
        settings.resolved_annotator_service_secret.get_secret_value(),
        algorithm=settings.annotator_service_algorithm,
    )
    request = Request({"type": "http", "method": "GET", "path": "/", "headers": [(b"cookie", f"admin_portal_session={token}".encode())]})
    with pytest.raises(identity_service.PortalAuthError) as error:
        identity_service.resolve_portal_identity(request, None, viewer="admin")
    assert error.value.code == "PORTAL_SESSION_INVALID"


def test_annotator_and_admin_sessions_coexist_under_separate_cookies(admin_review_fixture):
    fixture = admin_review_fixture
    client = fixture["client"]
    account = fixture["db"].query(AnnotatorAccount).one()
    # Both identities log in within the same browser.
    admin_login = _login(client, fixture["admin"].username, ADMIN_PASSWORD)
    annotator_login = _login(client, account.username, ANNOTATOR_PASSWORD)
    assert admin_login.status_code == 200 and annotator_login.status_code == 200
    admin_token = _cookie_from(admin_login, "admin_portal_session")
    annotator_token = _cookie_from(annotator_login, "portal_session")
    # Each viewer resolves its own identity even with both cookies present.
    me_admin = client.get(
        "/portal/auth/me",
        cookies={"admin_portal_session": admin_token, "portal_session": annotator_token},
        headers={"X-Portal-Viewer": "admin"},
    )
    assert me_admin.status_code == 200, me_admin.text
    assert me_admin.json()["kind"] == "admin"
    assert me_admin.json()["username"] == fixture["admin"].username
    me_annotator = client.get(
        "/portal/auth/me",
        cookies={"admin_portal_session": admin_token, "portal_session": annotator_token},
        headers={"X-Portal-Viewer": "annotator"},
    )
    assert me_annotator.status_code == 200, me_annotator.text
    assert me_annotator.json()["kind"] == "annotator"
    assert me_annotator.json()["subject_id"] == str(account.subject_id)


def test_admin_jwt_in_annotator_cookie_is_rejected(admin_review_fixture):
    """A pre-split admin JWT left in portal_session must not resurrect an
    admin identity through the annotator viewer."""
    token = jwt.encode(
        {
            "kind": "portal_admin",
            "sub": str(uuid.uuid4()),
            "username": "legacy-admin",
            "iat": datetime.now(timezone.utc),
            "exp": datetime.now(timezone.utc).timestamp() + 600,
        },
        settings.resolved_annotator_service_secret.get_secret_value(),
        algorithm=settings.annotator_service_algorithm,
    )
    request = Request({"type": "http", "method": "GET", "path": "/", "headers": [(b"cookie", f"portal_session={token}".encode())]})
    import app.services.annotator_identity as identity_service
    with pytest.raises(identity_service.PortalAuthError) as error:
        identity_service.resolve_portal_identity(request, admin_review_fixture["db"])
    assert error.value.code == "PORTAL_SESSION_INVALID"


class _NoResult:
    def filter(self, *_args, **_kwargs):
        return self

    def first(self):
        return None


# --- service token admin claim ---------------------------------------------


def test_service_token_carries_and_verifies_admin_user_id(admin_review_fixture):
    fixture = admin_review_fixture
    token = service_token_for_project(
        fixture["returned_task"].project_id,
        scopes=["admin_review:read"],
        admin_user_id=fixture["admin"].id,
    )
    request = Request({"type": "http", "method": "GET", "path": "/", "headers": [(b"authorization", f"Bearer {token}".encode())]})
    principal = verify_internal_service_token(request, "admin_review:read", None, allow_wildcard=True)
    assert principal.admin_user_id == fixture["admin"].id
    assert principal.annotator_subject_id is None


# --- admin internal endpoints ----------------------------------------------


def test_admin_task_list_is_owner_scoped_and_excludes_archived(admin_review_fixture):
    fixture = admin_review_fixture
    client = fixture["client"]
    response = client.get("/api/internal/portal/admin/tasks", headers=_admin_headers(fixture["admin"].id))
    assert response.status_code == 200, response.text
    items = response.json()["items"]
    assert {item["id"] for item in items} == {str(fixture["returned_task"].id), str(fixture["fresh_task"].id)}
    returned = next(item for item in items if item["id"] == str(fixture["returned_task"].id))
    assert returned["pending_return_batch_id"] == str(fixture["batch"].id)
    assert returned["return_state"] == "pending"
    assert returned["return_operation_state"] is None
    assert returned["sample_count"] == 2
    assert returned["annotator_name"] == fixture["db"].query(AnnotatorAccount).one().username
    fresh = next(item for item in items if item["id"] == str(fixture["fresh_task"].id))
    assert fresh["pending_return_batch_id"] is None
    assert fresh["return_state"] is None
    assert fresh["return_operation_state"] is None
    assert fresh["annotator_name"] is None


def test_admin_task_list_exposes_completed_return_validation(admin_review_fixture):
    fixture = admin_review_fixture
    _freeze_return_batch(fixture["db"], fixture["batch"])

    response = fixture["client"].get(
        "/api/internal/portal/admin/tasks",
        headers=_admin_headers(fixture["admin"].id),
    )

    assert response.status_code == 200, response.text
    returned = next(
        item for item in response.json()["items"]
        if item["id"] == str(fixture["returned_task"].id)
    )
    assert returned["return_operation_state"] == "completed"
    assert returned["return_validated_row_count"] == 2


def test_admin_task_list_excludes_tasks_of_deleted_projects(admin_review_fixture):
    """Project deletion leaves annotation tasks orphaned; the admin portal must
    hide them just like the main platform's project-scoped task list does."""
    fixture = admin_review_fixture
    db = fixture["db"]
    orphan = GenericAnnotationTask(
        project_id=uuid.uuid4(),  # no matching Project row
        dataset_version_id=uuid.uuid4(),  # NOT NULL; value irrelevant here
        label_schema_id=uuid.uuid4(),  # NOT NULL; value irrelevant here
        owner_id=fixture["admin"].id,
        name="孤儿任务",
        mode="manual",
        status="running",
        task_revision=0,
        sample_scope={"kind": "ids", "sample_ids": []},
        task_snapshot={},
    )
    db.add(orphan)
    db.commit()
    response = fixture["client"].get(
        "/api/internal/portal/admin/tasks", headers=_admin_headers(fixture["admin"].id)
    )
    assert response.status_code == 200, response.text
    items = response.json()["items"]
    assert str(orphan.id) not in {item["id"] for item in items}
    assert {str(fixture["returned_task"].id), str(fixture["fresh_task"].id)} == {item["id"] for item in items}


def test_admin_task_list_search_matches_name_and_short_id(admin_review_fixture):
    fixture = admin_review_fixture
    client = fixture["client"]
    by_name = client.get(
        "/api/internal/portal/admin/tasks",
        params={"search": "未回传"},
        headers=_admin_headers(fixture["admin"].id),
    )
    assert [item["id"] for item in by_name.json()["items"]] == [str(fixture["fresh_task"].id)]
    short_id = str(fixture["fresh_task"].id).replace("-", "")[:8]
    by_id = client.get(
        "/api/internal/portal/admin/tasks",
        params={"search": short_id},
        headers=_admin_headers(fixture["admin"].id),
    )
    assert [item["id"] for item in by_id.json()["items"]] == [str(fixture["fresh_task"].id)]


def test_admin_task_detail_is_read_only_with_schema_and_return_state(admin_review_fixture):
    fixture = admin_review_fixture
    client = fixture["client"]
    response = client.get(
        f"/api/internal/portal/admin/tasks/{fixture['returned_task'].id}",
        headers=_admin_headers(fixture["admin"].id),
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["read_only"] is True
    assert payload["task_revision"] == 4
    assert payload["pending_return_batch_id"] == str(fixture["batch"].id)
    assert payload["return_state"] == "pending"
    assert payload["return_operation_state"] is None
    assert payload["visible_columns"] == ["feature"]
    assert payload["label_schema"]["columns"][0]["machine_key"] == "result"
    assert payload["sample_scope"]["sample_count"] == 2


def test_admin_task_detail_hides_other_owners_tasks(admin_review_fixture):
    fixture = admin_review_fixture
    other = fixture["db"].query(GenericAnnotationTask).filter(
        GenericAnnotationTask.owner_id == fixture["other_admin"].id,
    ).one()
    response = fixture["client"].get(
        f"/api/internal/portal/admin/tasks/{other.id}",
        headers=_admin_headers(fixture["admin"].id),
    )
    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "ANNOTATION_TASK_NOT_FOUND"


def test_admin_samples_browse_task_scope_with_readonly_labels(admin_review_fixture):
    fixture = admin_review_fixture
    client = fixture["client"]
    response = client.get(
        f"/api/internal/portal/admin/tasks/{fixture['returned_task'].id}/samples",
        headers=_admin_headers(fixture["admin"].id),
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["total"] == 2
    assert [item["sample_id"] for item in payload["items"]] == ["sample-1", "sample-2"]
    first = payload["items"][0]
    assert first["values"] == {"feature": 1}
    assert first["labels"] == {"result": "pass"}
    assert first["revision"] == 4
    filtered = client.get(
        f"/api/internal/portal/admin/tasks/{fixture['returned_task'].id}/samples",
        params={"sample_search": "sample-2"},
        headers=_admin_headers(fixture["admin"].id),
    )
    assert [item["sample_id"] for item in filtered.json()["items"]] == ["sample-2"]


def test_admin_comment_requires_pending_return_batch(admin_review_fixture):
    fixture = admin_review_fixture
    client = fixture["client"]
    response = client.post(
        f"/api/internal/portal/admin/tasks/{fixture['fresh_task'].id}/comments",
        json={"sample_id": "sample-1", "content": "缺标签"},
        headers=_admin_headers(fixture["admin"].id, "admin_review:write"),
    )
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "RETURN_BATCH_REQUIRED"


def test_admin_comment_creates_comment_authored_by_admin(admin_review_fixture):
    fixture = admin_review_fixture
    client = fixture["client"]
    response = client.post(
        f"/api/internal/portal/admin/tasks/{fixture['returned_task'].id}/comments",
        json={"sample_id": "sample-1", "content": "这批样本需要复核"},
        headers=_admin_headers(fixture["admin"].id, "admin_review:write"),
    )
    assert response.status_code == 201, response.text
    payload = response.json()
    assert payload["author_name"] == fixture["admin"].username
    assert payload["status"] == "open"
    comment = fixture["db"].query(AnnotationComment).one()
    assert comment.author_id == fixture["admin"].id
    assert comment.sample_id == "sample-1"
    assert comment.body == "这批样本需要复核"
    listed = client.get(
        f"/api/internal/portal/admin/tasks/{fixture['returned_task'].id}/comments",
        params={"sample_id": "sample-1"},
        headers=_admin_headers(fixture["admin"].id),
    )
    assert listed.status_code == 200, listed.text
    assert [item["id"] for item in listed.json()["items"]] == [str(comment.id)]
    assert listed.json()["items"][0]["author_name"] == fixture["admin"].username


def test_admin_comment_rejects_sample_outside_scope(admin_review_fixture):
    fixture = admin_review_fixture
    response = fixture["client"].post(
        f"/api/internal/portal/admin/tasks/{fixture['returned_task'].id}/comments",
        json={"sample_id": "sample-unknown", "content": "越界样本"},
        headers=_admin_headers(fixture["admin"].id, "admin_review:write"),
    )
    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "SAMPLE_SCOPE_FORBIDDEN"


def test_admin_accept_and_return_require_pending_batch(admin_review_fixture):
    fixture = admin_review_fixture
    client = fixture["client"]
    accept = client.post(
        f"/api/internal/portal/admin/tasks/{fixture['fresh_task'].id}/accept",
        headers=_admin_headers(fixture["admin"].id, "admin_review:write"),
    )
    assert accept.status_code == 409
    assert accept.json()["detail"]["code"] == "RETURN_BATCH_REQUIRED"
    returned = client.post(
        f"/api/internal/portal/admin/tasks/{fixture['fresh_task'].id}/return",
        json={"reason": "标签不完整"},
        headers=_admin_headers(fixture["admin"].id, "admin_review:write"),
    )
    assert returned.status_code == 409
    assert returned.json()["detail"]["code"] == "RETURN_BATCH_REQUIRED"


def test_admin_accept_rejects_unfrozen_batch(admin_review_fixture):
    fixture = admin_review_fixture
    response = fixture["client"].post(
        f"/api/internal/portal/admin/tasks/{fixture['returned_task'].id}/accept",
        headers=_admin_headers(fixture["admin"].id, "admin_review:write"),
    )
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "RETURN_BATCH_NOT_READY"


def test_admin_accept_creates_dataset_version(admin_review_fixture):
    fixture = admin_review_fixture
    db = fixture["db"]
    _freeze_return_batch(db, fixture["batch"])
    response = fixture["client"].post(
        f"/api/internal/portal/admin/tasks/{fixture['returned_task'].id}/accept",
        headers=_admin_headers(fixture["admin"].id, "admin_review:write"),
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["status"] == "completed"
    accepted = db.get(DatasetVersion, uuid.UUID(payload["dataset_version_id"]))
    assert accepted is not None
    assert accepted.parse_contract["return_batch_id"] == str(fixture["batch"].id)
    assert db.get(AnnotationReturnBatch, fixture["batch"].id).state == "accepted"
    assert db.get(AnnotationReturnBatch, fixture["batch"].id).reviewed_by == fixture["admin"].id


def test_admin_return_rejects_batch_and_reopens_task(admin_review_fixture):
    fixture = admin_review_fixture
    db = fixture["db"]
    _freeze_return_batch(db, fixture["batch"])
    response = fixture["client"].post(
        f"/api/internal/portal/admin/tasks/{fixture['returned_task'].id}/return",
        json={"reason": "样本 2 标签与规范不符，请修正后重新回传"},
        headers=_admin_headers(fixture["admin"].id, "admin_review:write"),
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["return_batch_id"] == str(fixture["batch"].id)
    assert payload["state"] == "returned_for_changes"
    batch = db.get(AnnotationReturnBatch, fixture["batch"].id)
    assert batch.state == "returned_for_changes"
    assert batch.rejection_reason.startswith("样本 2")
    assert batch.reviewed_by == fixture["admin"].id
    assignment = db.get(AnnotationAssignment, batch.assignment_id)
    assert assignment.state == "edit_for_return"
    task = db.get(GenericAnnotationTask, fixture["returned_task"].id)
    assert task.status == "in_progress"


def test_admin_return_requires_reason(admin_review_fixture):
    fixture = admin_review_fixture
    response = fixture["client"].post(
        f"/api/internal/portal/admin/tasks/{fixture['returned_task'].id}/return",
        json={"reason": "  "},
        headers=_admin_headers(fixture["admin"].id, "admin_review:write"),
    )
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "RETURN_REASON_REQUIRED"


def test_admin_endpoints_reject_subject_only_service_token(admin_review_fixture):
    fixture = admin_review_fixture
    client = fixture["client"]
    for path, method, scope in [
        (f"/api/internal/portal/admin/tasks/{fixture['returned_task'].id}", "GET", "admin_review:read"),
        (f"/api/internal/portal/admin/tasks/{fixture['returned_task'].id}/accept", "POST", "admin_review:write"),
    ]:
        response = client.request(
            method, path,
            headers=_subject_headers(fixture["subject_id"], scope),
        )
        assert response.status_code == 403, response.text
        assert response.json()["detail"]["code"] == "SERVICE_ADMIN_REQUIRED"


def test_admin_endpoints_reject_missing_scope(admin_review_fixture):
    fixture = admin_review_fixture
    response = fixture["client"].post(
        f"/api/internal/portal/admin/tasks/{fixture['returned_task'].id}/accept",
        headers=_admin_headers(fixture["admin"].id, "admin_review:read"),
    )
    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "SERVICE_SCOPE_FORBIDDEN"
