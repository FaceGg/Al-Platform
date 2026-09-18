from __future__ import annotations

from datetime import datetime, timezone
import uuid

import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Query, sessionmaker
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
    AnnotationConfirmation,
    AnnotationRevision,
    LabelColumn,
    LabelSchema,
)
from app.models.platform_models import GenericAnnotationTask
from app.models.project import Project
from app.models.user import User
from app.models.annotator import AnnotatorSubjectMapping
from app.api.auth import get_current_user
from app.models.notifications import InAppNotification


def test_comment_resolution_repeated_requests_and_reopen_cycles_notify_once_per_change(portal_fixture):
    from app.models.notifications import NotificationOutbox
    from app.models.access import AuditEvent

    db = portal_fixture["db"]
    admin = db.query(User).filter(User.role == "admin").one()
    app.dependency_overrides[get_current_user] = lambda: admin
    comment = AnnotationComment(
        task_id=portal_fixture["task_id"], author_id=portal_fixture["annotator_principal_id"],
        body="please review", status="open",
    )
    db.add(comment)
    db.commit()
    path = f"/api/annotation-comments/{comment.id}/status"
    for status in ["resolved", "resolved", "open", "resolved"]:
        response = portal_fixture["client"].patch(path, json={"status": status})
        assert response.status_code == 200, response.text
    notices = db.query(InAppNotification).all()
    assert len(notices) == 3
    assert all(len(row.deduplication_key) <= 64 for row in notices)
    assert db.query(NotificationOutbox).count() == 3
    assert db.query(AuditEvent).filter(AuditEvent.action == "annotation.comment.status").count() == 3


def test_repeated_comment_notification_has_one_outbox_and_one_inbox_item(portal_fixture):
    from app.models.notifications import NotificationOutbox
    from app.services.notification_outbox import emit_annotation_comment_notification

    db = portal_fixture["db"]
    arguments = {
        "project_id": portal_fixture["project_id"],
        "actor_id": db.query(User).filter(User.role == "admin").one().id,
        "recipient_user_id": portal_fixture["annotator_principal_id"],
        "comment_id": uuid.uuid4(),
        "event_type": "annotation_comment.replied",
    }
    for _ in range(2):
        emit_annotation_comment_notification(db, **arguments)
        db.commit()
    assert db.query(NotificationOutbox).count() == 1
    notice = db.query(InAppNotification).one()
    assert len(notice.deduplication_key) <= 64
    notice.deduplication_key = "legacy-notice-key"
    db.commit()
    emit_annotation_comment_notification(db, **arguments)
    db.commit()
    assert db.query(InAppNotification).count() == 1


@pytest.mark.parametrize("change", ["body", "author_id", "delete"])
def test_comment_moderation_keeps_original_content_and_author_immutable(portal_fixture, change):
    db = portal_fixture["db"]
    row = AnnotationComment(
        task_id=portal_fixture["task_id"], author_id=portal_fixture["annotator_principal_id"],
        body="original", status="open",
    )
    db.add(row)
    db.commit()
    if change == "delete":
        db.delete(row)
    elif change == "body":
        row.body = "rewritten"
    else:
        row.author_id = db.query(User).filter(User.role == "admin").one().id
    with pytest.raises(ValueError, match="IMMUTABLE_LABEL_HISTORY"):
        db.flush()
    db.rollback()


def test_portal_notifications_are_recipient_scoped_paginated_and_read_idempotently(portal_fixture):
    db = portal_fixture["db"]
    comment = AnnotationComment(
        task_id=portal_fixture["task_id"], author_id=portal_fixture["annotator_principal_id"],
        body="targeted notice", sample_id="sample-1",
    )
    db.add(comment)
    db.flush()
    own = []
    for index in range(3):
        row = InAppNotification(
            recipient_user_id=portal_fixture["annotator_principal_id"],
            project_id=portal_fixture["project_id"], event_id=uuid.uuid4(),
            event_type="annotation_comment.replied", severity="info",
            title=f"notice-{index}", body="reply",
            payload={"comment_id": str(comment.id)} if index == 0 else {},
        )
        db.add(row)
        own.append(row)
    foreign = InAppNotification(
        recipient_user_id=db.query(User).filter(User.role == "admin").one().id,
        project_id=portal_fixture["project_id"], event_id=uuid.uuid4(),
        event_type="annotation_comment.replied", severity="info",
        title="private notice", body="private", payload={},
    )
    db.add(foreign)
    db.commit()
    headers = _headers(_token(project_id="*", subject_id=portal_fixture["subject_id"], scopes=["notification:read", "notification:write"]))
    client = portal_fixture["client"]
    path = "/api/internal/portal/notifications"
    first = client.get(path, params={"limit": 2}, headers=headers)
    assert first.status_code == 200, first.text
    assert first.json()["total"] == first.json()["unread_count"] == 3
    second = client.get(path, params={"limit": 2, "cursor": first.json()["next_cursor"]}, headers=headers)
    assert second.status_code == 200, second.text
    ids = [item["id"] for item in first.json()["items"] + second.json()["items"]]
    assert len(ids) == len(set(ids)) == 3
    assert set(ids) == {str(row.id) for row in own}
    first_item = next(item for item in first.json()["items"] + second.json()["items"] if item["id"] == str(own[0].id))
    assert first_item["target"] == {
        "task_id": str(portal_fixture["task_id"]),
        "assignment_id": str(db.query(AnnotationAssignment).one().id),
    }
    marked = client.post(f"{path}/{ids[0]}/read", headers=headers)
    assert marked.status_code == 200, marked.text
    assert marked.json()["read_at"]
    repeated = client.post(f"{path}/{ids[0]}/read", headers=headers)
    assert repeated.json()["read_at"] == marked.json()["read_at"]
    unread = client.get(path, params={"unread_only": True}, headers=headers).json()
    assert unread["total"] == unread["unread_count"] == 2
    assert client.post(f"{path}/{foreign.id}/read", headers=headers).status_code == 404
    assert client.get(path, params={"cursor": str(foreign.id)}, headers=headers).status_code == 422


@pytest.mark.parametrize("restriction", ["grant", "account", "token_project", "scope"])
def test_portal_notifications_revalidate_access(portal_fixture, restriction):
    db = portal_fixture["db"]
    row = InAppNotification(
        recipient_user_id=portal_fixture["annotator_principal_id"],
        project_id=portal_fixture["project_id"], event_id=uuid.uuid4(),
        event_type="annotation_return.returned_for_changes", severity="info",
        title="Return updated", body="Return updated", payload={},
    )
    db.add(row)
    if restriction == "grant":
        db.query(ProjectAnnotatorGrant).one().status = "revoked"
    elif restriction == "account":
        db.query(AnnotatorAccount).one().status = "disabled"
    db.commit()
    headers = _headers(_token(
        project_id=uuid.uuid4() if restriction == "token_project" else "*",
        subject_id=portal_fixture["subject_id"],
        scopes=["assignment:read"] if restriction == "scope" else ["notification:read", "notification:write"],
    ))
    path = "/api/internal/portal/notifications"
    response = portal_fixture["client"].get(path, headers=headers)
    if restriction in {"account", "scope"}:
        assert response.status_code == 403
    else:
        assert response.status_code == 200, response.text
        assert response.json()["total"] == response.json()["unread_count"] == 0
        assert portal_fixture["client"].post(f"{path}/{row.id}/read", headers=headers).status_code == 404


def test_admin_comments_filter_and_stable_cursor(portal_fixture):
    db = portal_fixture["db"]
    admin = db.query(User).filter(User.role == "admin").one()
    app.dependency_overrides[get_current_user] = lambda: admin
    ids = [uuid.UUID(f"abcdefab-0000-0000-0000-{n:012x}") for n in (100, 200, 300)]
    for index, identifier in enumerate(ids):
        db.add(AnnotationComment(
            id=identifier, task_id=portal_fixture["task_id"], author_id=admin.id,
            body=f"comment-{index}", sample_id="sample-1",
            status="resolved" if index == 2 else "open",
            created_at=datetime(2026, 9, 1),
        ))
    db.commit()
    params = {"task_id": str(portal_fixture["task_id"]), "limit": 1,
              "status": "open", "sample_id": "sample-1"}
    first = portal_fixture["client"].get("/api/annotation-comments", params=params)
    assert first.status_code == 200, first.text
    assert [item["id"] for item in first.json()["items"]] == [str(ids[0])]
    assert first.json()["total"] == 2
    second = portal_fixture["client"].get(
        "/api/annotation-comments",
        params={**params, "cursor": first.json()["next_cursor"]},
    )
    assert [item["id"] for item in second.json()["items"]] == [str(ids[1])]
    assert second.json()["next_cursor"] is None
    invalid = portal_fixture["client"].get(
        "/api/annotation-comments", params={**params, "cursor": str(ids[2])},
    )
    assert invalid.status_code == 422
    empty = portal_fixture["client"].get(
        "/api/annotation-comments", params={**params, "sample_id": "absent"},
    )
    assert empty.json()["total"] == 0


def test_admin_comments_can_filter_roots_and_replies(portal_fixture):
    db = portal_fixture["db"]
    admin = db.query(User).filter(User.role == "admin").one()
    app.dependency_overrides[get_current_user] = lambda: admin
    root = AnnotationComment(
        task_id=portal_fixture["task_id"], author_id=admin.id, body="root",
        sample_id="sample-1", created_at=datetime(2026, 9, 2),
    )
    db.add(root)
    db.flush()
    db.add(AnnotationComment(
        task_id=portal_fixture["task_id"], author_id=admin.id, body="reply",
        sample_id="sample-1", parent_id=root.id, created_at=datetime(2026, 9, 3),
    ))
    db.commit()
    base = {"task_id": str(portal_fixture["task_id"]), "limit": 50}
    client = portal_fixture["client"]

    roots = client.get("/api/annotation-comments", params={**base, "thread": "roots"})
    replies = client.get("/api/annotation-comments", params={**base, "thread": "replies"})
    all_rows = client.get("/api/annotation-comments", params={**base, "thread": "all"})
    assert roots.status_code == replies.status_code == all_rows.status_code == 200
    assert [item["content"] for item in roots.json()["items"]] == ["root"]
    assert [item["content"] for item in replies.json()["items"]] == ["reply"]
    assert all_rows.json()["total"] == 2


@pytest.mark.parametrize("params", [{"limit": 201}, {"limit": 0}, {"status": "unknown"}, {"cursor": "bad"}])
def test_admin_comments_reject_invalid_page(portal_fixture, params):
    db = portal_fixture["db"]
    app.dependency_overrides[get_current_user] = lambda: db.query(User).filter(User.role == "admin").one()
    response = portal_fixture["client"].get(
        "/api/annotation-comments", params={"task_id": str(portal_fixture["task_id"]), **params},
    )
    assert response.status_code == 422


def test_admin_comments_reaches_beyond_two_hundred_with_default_timestamps(portal_fixture):
    db = portal_fixture["db"]
    admin = db.query(User).filter(User.role == "admin").one()
    app.dependency_overrides[get_current_user] = lambda: admin
    identifiers = {str(uuid.uuid4()) for _ in range(205)}
    db.add_all([
        AnnotationComment(
            id=uuid.UUID(identifier), task_id=portal_fixture["task_id"],
            author_id=admin.id, body="paged comment",
        ) for identifier in identifiers
    ])
    db.commit()
    seen = []
    cursor = None
    for _ in range(6):
        response = portal_fixture["client"].get(
            "/api/annotation-comments",
            params={"task_id": str(portal_fixture["task_id"]), "limit": 50,
                    **({"cursor": cursor} if cursor else {})},
        )
        assert response.status_code == 200, response.text
        assert response.json()["total"] == 205
        seen.extend(item["id"] for item in response.json()["items"])
        cursor = response.json()["next_cursor"]
        if cursor is None:
            break
    assert cursor is None
    assert len(seen) == 205
    assert set(seen) == identifiers


def test_admin_comments_requires_admin_and_existing_task(portal_fixture):
    db = portal_fixture["db"]
    app.dependency_overrides[get_current_user] = lambda: db.query(User).filter(User.role == "annotator").one()
    response = portal_fixture["client"].get(
        "/api/annotation-comments", params={"task_id": str(portal_fixture["task_id"])},
    )
    assert response.status_code == 403
    app.dependency_overrides[get_current_user] = lambda: db.query(User).filter(User.role == "admin").one()
    missing = portal_fixture["client"].get(
        "/api/annotation-comments", params={"task_id": str(uuid.uuid4())},
    )
    assert missing.status_code == 404


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
    annotator_principal = User(
        username=f"portal-annotator-principal-{uuid.uuid4().hex}",
        password_hash="hash",
        role="annotator",
    )
    db.add_all([admin, annotator_principal])
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
            DatasetSample(dataset_version_id=dataset.id, sample_id="sample-1", row_index=0, values={"feature": 1, "private_note": "not authorized"}),
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
            platform_principal_id=annotator_principal.id,
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
        task_snapshot={
            "sample_ids": ["sample-1", "sample-2"],
            "visible_columns": ["feature"],
            "instructions": "Use the frozen rubric.",
            "label_schema": {
                "columns": [{
                    "machine_key": "label", "display_name": "Frozen label",
                    "value_type": "string", "required": True, "max_length": 128,
                }],
            },
        },
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
            "annotator_principal_id": annotator_principal.id,
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


def test_portal_sample_filters_use_authorized_fields_and_own_revisions(portal_fixture):
    db = portal_fixture["db"]
    schema_id = db.query(LabelSchema).one().id
    admin_id = db.query(User).filter(User.role == "admin").one().id
    db.add_all([
        AnnotationRevision(
            task_id=portal_fixture["task_id"],
            sample_id="sample-1",
            schema_id=schema_id,
            revision_no=4,
            base_revision=3,
            values={"label": "annotator-edit"},
            author_id=portal_fixture["annotator_principal_id"],
            created_at=datetime(2026, 9, 10, 12, 0),
        ),
        AnnotationRevision(
            task_id=portal_fixture["task_id"],
            sample_id="sample-2",
            schema_id=schema_id,
            revision_no=4,
            base_revision=3,
            values={"label": "admin-edit"},
            author_id=admin_id,
            created_at=datetime(2026, 9, 11, 12, 0),
        ),
    ])
    db.commit()
    token = _token(
        project_id=portal_fixture["project_id"],
        subject_id=portal_fixture["subject_id"],
        scopes=["assignment:read"],
    )
    path = f"/api/internal/portal/tasks/{portal_fixture['task_id']}/samples"
    headers = _headers(token)

    by_field = portal_fixture["client"].get(
        path,
        params={"authorized_field": "feature", "authorized_value": "2"},
        headers=headers,
    )
    assert by_field.status_code == 200, by_field.text
    assert [item["sample_id"] for item in by_field.json()["items"]] == ["sample-2"]

    by_author = portal_fixture["client"].get(
        path,
        params={"modified_after": "2026-09-09T00:00:00Z"},
        headers=headers,
    )
    assert by_author.status_code == 200, by_author.text
    assert [item["sample_id"] for item in by_author.json()["items"]] == ["sample-1"]

    forbidden_field = portal_fixture["client"].get(
        path,
        params={"authorized_field": "private_note", "authorized_value": "not authorized"},
        headers=headers,
    )
    assert forbidden_field.status_code == 422
    assert forbidden_field.json()["detail"]["code"] == "AUTHORIZED_FIELD_INVALID"


def test_internal_portal_task_queue_supports_server_side_search_filter_and_sort(portal_fixture):
    token = _token(
        project_id=portal_fixture["project_id"],
        subject_id=portal_fixture["subject_id"],
        scopes=["assignment:read"],
    )
    response = portal_fixture["client"].get(
        "/api/internal/portal/tasks",
        params={
            "search": "Annotation task",
            "status": "awaiting_annotation",
            "assignment_state": "pending",
            "sort": "due_at",
            "direction": "asc",
            "limit": 10,
        },
        headers=_headers(token),
    )
    assert response.status_code == 200, response.text
    assert response.json()["items"][0]["id"] == str(portal_fixture["task_id"])


@pytest.mark.parametrize("sort", ["created_at", "due_at", "status", "assignment_state"])
@pytest.mark.parametrize("direction", ["asc", "desc"])
def test_portal_queue_keyset_preserves_ties_and_nulls(portal_fixture, sort, direction):
    db = portal_fixture["db"]
    first = db.query(AnnotationAssignment).filter_by(task_id=portal_fixture["task_id"]).one()
    first.created_at = datetime(2026, 9, 1)
    first.due_at = datetime(2026, 9, 20)
    assignments = [first]
    for index in range(3):
        row = AnnotationAssignment(
            task_id=first.task_id, annotator_subject_id=first.annotator_subject_id,
            sample_scope=first.sample_scope, scope_hash=f"sha256:page-{index}",
            state="pending", task_revision=first.task_revision,
            created_by=first.created_by, created_at=datetime(2026, 9, 2),
            due_at=datetime(2026, 9, 20) if index == 0 else None,
        )
        db.add(row)
        assignments.append(row)
    db.commit()
    key = {"created_at": "created_at", "due_at": "due_at", "assignment_state": "state"}.get(sort)
    values = {row.id: getattr(row, key) if key else "awaiting_annotation" for row in assignments}
    nonnull = sorted((row.id for row in assignments if values[row.id] is not None),
                     key=lambda ident: (values[ident], ident), reverse=direction == "desc")
    nulls = sorted((row.id for row in assignments if values[row.id] is None), reverse=direction == "desc")
    expected = [str(ident) for ident in nonnull + nulls]
    seen = []
    cursor = None
    for _ in range(4):
        token = _token(project_id=portal_fixture["project_id"], subject_id=portal_fixture["subject_id"], scopes=["assignment:read"])
        params = {"sort": sort, "direction": direction, "limit": 1}
        if cursor:
            params["cursor"] = cursor
        response = portal_fixture["client"].get("/api/internal/portal/tasks", params=params, headers=_headers(token))
        assert response.status_code == 200, response.text
        data = response.json()
        assert data["total"] == 4
        seen.extend(row["assignment_id"] for row in data["items"])
        cursor = data["next_cursor"]
    assert cursor is None
    assert seen == expected


@pytest.mark.parametrize("params", [
    {"search": "Annotation task not-a-real-id"},
    {"search": "%"},
    {"status": "completed"},
    {"assignment_state": "paused"},
])
def test_portal_queue_filters_before_counting(portal_fixture, params):
    token = _token(project_id=portal_fixture["project_id"], subject_id=portal_fixture["subject_id"], scopes=["assignment:read"])
    response = portal_fixture["client"].get("/api/internal/portal/tasks", params=params, headers=_headers(token))
    assert response.status_code == 200, response.text
    assert response.json() == {"items": [], "total": 0, "next_cursor": None}


def test_portal_queue_search_accepts_displayed_uuid(portal_fixture):
    token = _token(project_id=portal_fixture["project_id"], subject_id=portal_fixture["subject_id"], scopes=["assignment:read"])
    response = portal_fixture["client"].get(
        "/api/internal/portal/tasks", params={"search": str(portal_fixture["task_id"])}, headers=_headers(token),
    )
    assert response.status_code == 200, response.text
    assert response.json()["total"] == 1


def test_portal_task_summary_does_not_load_every_assignment_sample(portal_fixture, monkeypatch):
    original_all = Query.all

    def bounded_all(query):
        assert query._limit_clause is not None, f"unbounded row query: {query}"
        return original_all(query)

    monkeypatch.setattr(Query, "all", bounded_all)
    token = _token(
        project_id=portal_fixture["project_id"],
        subject_id=portal_fixture["subject_id"],
        scopes=["assignment:read"],
    )

    response = portal_fixture["client"].get(
        f"/api/internal/portal/tasks/{portal_fixture['task_id']}",
        headers=_headers(token),
    )

    assert response.status_code == 200, response.text
    assert response.json()["total_samples"] == 2
    assert response.json()["completed_samples"] == 2


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
    assert saved.json() == {"values": {"label": "new"}, "revision": 4, "task_revision": 3}
    revision = portal_fixture["db"].query(AnnotationRevision).filter_by(
        task_id=portal_fixture["task_id"],
        sample_id="sample-1",
        revision_no=4,
    ).one()
    assert revision.author_id == portal_fixture["annotator_principal_id"]

    conflict = client.put(
        path,
        headers=_headers(token),
        json={"values": {"label": "stale"}, "base_revision": 3},
    )
    assert conflict.status_code == 409, conflict.text
    assert conflict.json()["detail"]["code"] == "REVISION_CONFLICT"
    assert conflict.json()["detail"]["current_values"] == {"label": "new"}


def test_internal_portal_detail_returns_frozen_editing_contract(portal_fixture):
    token = _token(
        project_id=portal_fixture["project_id"],
        subject_id=portal_fixture["subject_id"],
        scopes=["assignment:read"],
    )
    response = portal_fixture["client"].get(
        f"/api/internal/portal/tasks/{portal_fixture['task_id']}",
        headers=_headers(token),
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["label_schema"] == {"columns": [{
        "machine_key": "label", "display_name": "Frozen label",
        "value_type": "string", "required": True, "max_length": 128,
    }]}
    assert body["instructions"] == "Use the frozen rubric."
    assert body["visible_columns"] == ["feature"]
    assert "sample_ids" not in body


def test_internal_portal_samples_follow_cursor_without_leaking_columns(portal_fixture):
    token = _token(
        project_id=portal_fixture["project_id"],
        subject_id=portal_fixture["subject_id"],
        scopes=["assignment:read"],
    )
    client = portal_fixture["client"]
    path = f"/api/internal/portal/tasks/{portal_fixture['task_id']}/samples"
    first = client.get(path, params={"limit": 1}, headers=_headers(token)).json()
    assert first["items"][0]["values"] == {"feature": 1}
    second = client.get(
        path, params={"limit": 1, "cursor": first["next_cursor"]}, headers=_headers(token),
    ).json()
    assert [item["sample_id"] for item in second["items"]] == ["sample-2"]
    assert second["next_cursor"] is None
    assert second["total"] == 2
    assert client.get(path, params={"limit": 201}, headers=_headers(token)).status_code == 422
    assert client.get(path, params={"cursor": "not-assigned"}, headers=_headers(token)).status_code == 422


@pytest.mark.parametrize("explicit_assignment", [False, True])
def test_internal_portal_bulk_confirm_and_return_are_idempotent(portal_fixture, explicit_assignment):
    read_write = _token(
        project_id=portal_fixture["project_id"],
        subject_id=portal_fixture["subject_id"],
        scopes=["assignment:write", "assignment:return"],
    )
    client = portal_fixture["client"]
    task_path = f"/api/internal/portal/tasks/{portal_fixture['task_id']}"
    params = {"assignment_id": str(portal_fixture["db"].query(AnnotationAssignment).one().id)} if explicit_assignment else {}

    bulk = client.post(
        f"{task_path}/bulk-labels",
        params=params,
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
        params=params,
        headers=_headers(read_write),
        json={"task_revision": 3, "scope_hash": portal_fixture["scope_hash"]},
    )
    assert confirmed.status_code == 200, confirmed.text
    confirmations = portal_fixture["db"].query(AnnotationConfirmation).filter_by(
        task_id=portal_fixture["task_id"],
    ).all()
    assert confirmations
    assert {row.confirmer_id for row in confirmations} == {portal_fixture["annotator_principal_id"]}

    first = client.post(
        f"{task_path}/return",
        params=params,
        headers=_headers(read_write, **{"Idempotency-Key": "portal-return-1"}),
        json={"task_revision": 3, "scope_hash": portal_fixture["scope_hash"]},
    )
    second = client.post(
        f"{task_path}/return",
        params=params,
        headers=_headers(read_write, **{"Idempotency-Key": "portal-return-1"}),
        json={"task_revision": 3, "scope_hash": portal_fixture["scope_hash"]},
    )
    assert first.status_code == second.status_code == 202
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


def test_internal_portal_comment_reply_stays_in_same_sample_thread(portal_fixture):
    token = _token(
        project_id=portal_fixture["project_id"],
        subject_id=portal_fixture["subject_id"],
        scopes=["comment:write", "comment:read"],
    )
    client = portal_fixture["client"]
    root = client.post(
        "/api/internal/portal/comments",
        params={"assignment_id": str(portal_fixture["db"].query(AnnotationAssignment).one().id)},
        headers=_headers(token),
        json={"task_id": str(portal_fixture["task_id"]), "sample_id": "sample-1", "content": "root"},
    )
    assert root.status_code == 201, root.text
    reply = client.post(
        "/api/internal/portal/comments",
        params={"assignment_id": str(portal_fixture["db"].query(AnnotationAssignment).one().id)},
        headers=_headers(token),
        json={
            "task_id": str(portal_fixture["task_id"]), "sample_id": "sample-1",
            "content": "reply", "parent_id": root.json()["id"],
        },
    )
    assert reply.status_code == 201, reply.text
    assert reply.json()["parent_id"] == root.json()["id"]
    wrong_scope = client.post(
        "/api/internal/portal/comments",
        params={"assignment_id": str(portal_fixture["db"].query(AnnotationAssignment).one().id)},
        headers=_headers(token),
        json={
            "task_id": str(portal_fixture["task_id"]), "sample_id": "sample-2",
            "content": "wrong reply", "parent_id": root.json()["id"],
        },
    )
    assert wrong_scope.status_code == 422
    assert wrong_scope.json()["detail"]["code"] == "COMMENT_SCOPE_MISMATCH"


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
    next_page = portal_fixture["client"].get(
        "/api/internal/portal/comments",
        params={"limit": 1, "cursor": response.json()["next_cursor"]},
        headers=_headers(_token(project_id=portal_fixture["project_id"], subject_id=subject_id, scopes=["comment:read"])),
    )
    assert next_page.status_code == 200, next_page.text
    assert [item["content"] for item in next_page.json()["items"]] == ["task note"]
    assert next_page.json()["next_cursor"] is None


def test_comment_cursor_follows_timestamp_order_not_uuid_order(portal_fixture):
    db = portal_fixture["db"]
    rows = [
        AnnotationComment(
            id=uuid.UUID(f"abcdefab-abcd-abcd-abcd-{index:012x}"),
            task_id=portal_fixture["task_id"],
            author_id=portal_fixture["annotator_principal_id"],
            body=f"note-{index}",
            created_at=datetime(2026, 9, index),
        )
        for index in [3, 1, 2]
    ]
    # The second item has a larger UUID than the first despite its older date.
    rows[0].created_at = datetime(2026, 9, 1)
    rows[1].created_at = datetime(2026, 9, 3)
    db.add_all(rows)
    db.commit()
    seen = []
    cursor = None
    for _ in range(4):
        token = _token(project_id=portal_fixture["project_id"], subject_id=portal_fixture["subject_id"], scopes=["comment:read"])
        response = portal_fixture["client"].get(
            "/api/internal/portal/comments",
            params={"task_id": str(portal_fixture["task_id"]), "limit": 1, **({"cursor": cursor} if cursor else {})},
            headers=_headers(token),
        )
        assert response.status_code == 200, response.text
        data = response.json()
        seen.extend(item["content"] for item in data["items"])
        cursor = data["next_cursor"]
        if cursor is None:
            break
    assert seen == ["note-1", "note-2", "note-3"]


@pytest.mark.parametrize("restriction", ["sample", "grant", "project"])
def test_comment_read_enforces_current_authorization(portal_fixture, restriction):
    db = portal_fixture["db"]
    comment = AnnotationComment(
        task_id=portal_fixture["task_id"], sample_id="outside-scope" if restriction == "sample" else "sample-1",
        author_id=portal_fixture["annotator_principal_id"], body="private comment",
    )
    db.add(comment)
    if restriction == "grant":
        db.query(ProjectAnnotatorGrant).filter_by(subject_id=portal_fixture["subject_id"]).one().status = "revoked"
    db.commit()
    token = _token(
        project_id=uuid.uuid4() if restriction == "project" else portal_fixture["project_id"],
        subject_id=portal_fixture["subject_id"], scopes=["comment:read"],
    )
    response = portal_fixture["client"].get("/api/internal/portal/comments", headers=_headers(token))
    assert response.status_code == 200, response.text
    assert response.json()["items"] == []
    assert response.json()["total"] == 0
    response = portal_fixture["client"].get(
        "/api/internal/portal/comments", params={"cursor": str(comment.id)},
        headers=_headers(_token(
            project_id=uuid.uuid4() if restriction == "project" else portal_fixture["project_id"],
            subject_id=portal_fixture["subject_id"], scopes=["comment:read"],
        )),
    )
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "INVALID_CURSOR"


def test_comment_cursor_orders_equal_timestamps_and_accepts_all_active_scopes(portal_fixture):
    db = portal_fixture["db"]
    assignment = db.query(AnnotationAssignment).one()
    second = AnnotationAssignment(
        task_id=assignment.task_id, annotator_subject_id=assignment.annotator_subject_id,
        sample_scope={"kind": "ids", "sample_ids": ["sample-3"]},
        scope_hash="second-scope", state="pending", task_revision=3, created_by=assignment.created_by,
    )
    db.add(second)
    db.flush()
    db.add(AnnotationAssignmentSample(assignment_id=second.id, sample_id="sample-3", revision_no=0, values={}))
    ids = sorted([uuid.uuid4() for _ in range(3)], reverse=True)
    for identifier in ids:
        db.add(AnnotationComment(
            id=identifier, task_id=assignment.task_id, sample_id="sample-3",
            author_id=assignment.created_by, body="same timestamp",
            created_at=datetime(2026, 9, 1),
        ))
    db.commit()
    seen = []
    cursor = None
    for _ in range(4):
        response = portal_fixture["client"].get(
            "/api/internal/portal/comments",
            params={"limit": 1, **({"cursor": cursor} if cursor else {})},
            headers=_headers(_token(project_id=portal_fixture["project_id"], subject_id=portal_fixture["subject_id"], scopes=["comment:read"])),
        )
        assert response.status_code == 200, response.text
        seen.extend(item["id"] for item in response.json()["items"])
        cursor = response.json()["next_cursor"]
        if cursor is None:
            break
    assert seen == [str(identifier) for identifier in ids]


def test_portal_requires_explicit_selection_for_multiple_assignments(portal_fixture):
    db = portal_fixture["db"]
    first = db.query(AnnotationAssignment).one()
    second = AnnotationAssignment(
        task_id=first.task_id, annotator_subject_id=first.annotator_subject_id,
        sample_scope={"kind": "ids", "sample_ids": ["sample-2"]},
        scope_hash="second-scope", state="pending", task_revision=3, created_by=first.created_by,
        created_at=datetime(2026, 9, 17),
    )
    db.add(second)
    db.flush()
    db.add(AnnotationAssignmentSample(assignment_id=second.id, sample_id="sample-2", revision_no=0, values={}))
    db.commit()
    path = f"/api/internal/portal/tasks/{first.task_id}"
    def headers():
        return _headers(_token(project_id=portal_fixture["project_id"], subject_id=portal_fixture["subject_id"], scopes=["assignment:read", "assignment:write", "comment:write"]))
    ambiguous = portal_fixture["client"].get(path, headers=headers())
    assert ambiguous.status_code == 409, ambiguous.text
    assert ambiguous.json()["detail"]["code"] == "ASSIGNMENT_SELECTION_REQUIRED"
    for assignment, expected in [(first, ["sample-1", "sample-2"]), (second, ["sample-2"])]:
        params = {"assignment_id": str(assignment.id)}
        detail = portal_fixture["client"].get(path, params=params, headers=headers())
        assert detail.status_code == 200, detail.text
        assert detail.json()["assignment_id"] == str(assignment.id)
        samples = portal_fixture["client"].get(path + "/samples", params=params, headers=headers())
        assert samples.status_code == 200, samples.text
        assert [item["sample_id"] for item in samples.json()["items"]] == expected
    saved = portal_fixture["client"].put(
        path + "/samples/sample-1/labels", params={"assignment_id": str(first.id)},
        json={"values": {"label": "selected-first"}, "base_revision": 3}, headers=headers(),
    )
    assert saved.status_code == 200, saved.text
    forbidden = portal_fixture["client"].put(
        path + "/samples/sample-1/labels", params={"assignment_id": str(second.id)},
        json={"values": {"label": "wrong-scope"}, "base_revision": 4}, headers=headers(),
    )
    assert forbidden.status_code in {403, 422}, forbidden.text
    assert forbidden.json()["detail"]["code"] == "SAMPLE_SCOPE_FORBIDDEN"
    comment = portal_fixture["client"].post(
        "/api/internal/portal/comments", params={"assignment_id": str(second.id)},
        json={"task_id": str(first.task_id), "sample_id": "sample-2", "content": "selected scope"}, headers=headers(),
    )
    assert comment.status_code == 201, comment.text
    comment = portal_fixture["client"].post(
        "/api/internal/portal/comments", params={"assignment_id": str(second.id)},
        json={"task_id": str(first.task_id), "sample_id": "sample-1", "content": "wrong scope"}, headers=headers(),
    )
    assert comment.status_code == 403, comment.text


@pytest.mark.parametrize("method,suffix,payload", [
    ("GET", "", None), ("GET", "/samples", None),
    ("PUT", "/samples/sample-1/labels", {"values": {"label": "new"}, "base_revision": 3}),
    ("POST", "/bulk-labels", {"items": [{"sample_id": "sample-1", "values": {"label": "new"}, "base_revision": 3}]}),
    ("POST", "/confirm", {"task_revision": 3, "scope_hash": "sha256:portal-scope"}),
    ("POST", "/edit-for-return", {"task_revision": 3, "scope_hash": "sha256:portal-scope"}),
    ("POST", "/return", {"task_revision": 3, "scope_hash": "sha256:portal-scope"}),
])
@pytest.mark.parametrize("restriction", ["unknown", "other_subject", "other_task", "revoked"])
def test_portal_never_falls_back_from_unknown_assignment(portal_fixture, method, suffix, payload, restriction):
    db = portal_fixture["db"]
    assignment = db.query(AnnotationAssignment).one()
    selected_id = assignment.id
    if restriction == "unknown":
        selected_id = uuid.uuid4()
    elif restriction == "other_subject":
        assignment.annotator_subject_id = uuid.uuid4()
    elif restriction == "other_task":
        assignment.task_id = uuid.uuid4()
    else:
        assignment.state = "revoked"
    db.commit()
    token = _token(project_id=portal_fixture["project_id"], subject_id=portal_fixture["subject_id"], scopes=["assignment:read", "assignment:write", "assignment:return"])
    response = portal_fixture["client"].request(
        method, f"/api/internal/portal/tasks/{portal_fixture['task_id']}{suffix}",
        params={"assignment_id": str(selected_id)}, json=payload,
        headers={**_headers(token), "Idempotency-Key": str(uuid.uuid4())},
    )
    assert response.status_code == 404, response.text
    assert response.json()["detail"]["code"] == "ASSIGNMENT_NOT_FOUND"
