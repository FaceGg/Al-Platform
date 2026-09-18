from fastapi.testclient import TestClient
import uuid
import pytest

from app.main import app
from app.services.session import PortalPrincipal, require_portal_session


def test_portal_exposes_task_and_comment_routes():
    paths = TestClient(app).get("/openapi.json").json()["paths"]
    assert "/portal/tasks" in paths
    assert "/portal/tasks/{task_id}/samples" in paths
    assert "/portal/comments" in paths


def test_portal_notification_routes_require_session_and_forward_owned_identity(monkeypatch):
    from unittest.mock import AsyncMock
    from app.services.platform_client import PlatformClient

    client = TestClient(app)
    assert client.get("/portal/notifications").status_code == 401
    subject = uuid.uuid4()
    notification = uuid.uuid4()
    upstream = AsyncMock(return_value={"items": [], "total": 0, "unread_count": 0, "next_cursor": None})
    monkeypatch.setattr(PlatformClient, "internal_request", upstream)
    app.dependency_overrides[require_portal_session] = lambda: PortalPrincipal(subject_id=subject, username="reader")
    try:
        response = client.get("/portal/notifications", params={"limit": 12, "unread_only": True, "recipient_user_id": str(uuid.uuid4())})
        assert response.status_code == 200, response.text
        assert upstream.call_args.kwargs == {
            "subject_id": str(subject), "scope": "notification:read",
            "params": {"limit": 12, "unread_only": True},
        }
        assert client.post(f"/portal/notifications/{notification}/read").status_code == 200
        assert upstream.call_args.args == ("POST", f"/api/internal/portal/notifications/{notification}/read")
        assert upstream.call_args.kwargs == {"subject_id": str(subject), "scope": "notification:write"}
    finally:
        app.dependency_overrides.clear()


def test_portal_task_queue_accepts_server_side_query_controls(monkeypatch):
    from unittest.mock import AsyncMock
    from app.services.platform_client import PlatformClient

    upstream = AsyncMock(return_value={"items": [], "total": 0, "next_cursor": None})
    monkeypatch.setattr(PlatformClient, "internal_request", upstream)
    app.dependency_overrides[require_portal_session] = lambda: PortalPrincipal(
        subject_id=uuid.UUID("11111111-1111-1111-1111-111111111111"),
        username="annotator-a",
    )
    client = TestClient(app)
    try:
        response = client.get(
            "/portal/tasks",
            params={
                "search": "weld",
                "status": "awaiting_annotation",
                "assignment_state": "pending",
                "sort": "due_at",
                "direction": "asc",
            },
        )
        assert response.status_code == 200, response.text
        assert upstream.await_count == 1
        forwarded = upstream.call_args.kwargs
        assert forwarded["subject_id"] == "11111111-1111-1111-1111-111111111111"
        assert forwarded["params"] == {
            "limit": 50, "search": "weld", "status": "awaiting_annotation",
            "assignment_state": "pending", "sort": "due_at", "direction": "asc",
        }
    finally:
        app.dependency_overrides.clear()


def test_portal_sample_filter_forwards_authorized_field_and_modified_after(monkeypatch):
    from unittest.mock import AsyncMock
    from app.services.platform_client import PlatformClient

    upstream = AsyncMock(return_value={"items": [], "total": 0, "next_cursor": None})
    monkeypatch.setattr(PlatformClient, "internal_request", upstream)
    subject_id, task_id = uuid.uuid4(), uuid.uuid4()
    app.dependency_overrides[require_portal_session] = lambda: PortalPrincipal(
        subject_id=subject_id, username="annotator",
    )
    try:
        response = TestClient(app).get(
            f"/portal/tasks/{task_id}/samples",
            params={
                "authorized_field": "feature",
                "authorized_value": "weld",
                "modified_after": "2026-09-16T00:00:00Z",
            },
        )
        assert response.status_code == 200, response.text
        assert upstream.call_args.kwargs["params"] == {
            "limit": 50,
            "authorized_field": "feature",
            "authorized_value": "weld",
            "modified_after": "2026-09-16T00:00:00+00:00",
        }
    finally:
        app.dependency_overrides.clear()


def test_portal_task_requests_require_portal_cookie():
    client = TestClient(app)
    response = client.get("/portal/tasks")
    assert response.status_code == 401


def test_portal_does_not_accept_client_owned_identity_fields():
    app.dependency_overrides[require_portal_session] = lambda: PortalPrincipal(
        subject_id=uuid.UUID("11111111-1111-1111-1111-111111111111"),
        username="annotator-a",
    )
    client = TestClient(app)
    try:
        response = client.put(
            "/portal/tasks/11111111-1111-1111-1111-111111111112/samples/sample-1/labels",
            json={"annotator_id": "client-owned", "project_id": "client-owned", "values": {"label": "x"}, "base_revision": 0},
        )
        assert response.status_code == 422
    finally:
        app.dependency_overrides.clear()


@pytest.mark.parametrize("method,suffix,payload", [
    ("GET", "", None), ("GET", "/samples", None),
    ("PUT", "/samples/sample-1/labels", {"values": {"label": "x"}, "base_revision": 0}),
    ("POST", "/bulk-labels", {"items": [{"sample_id": "sample-1", "values": {"label": "x"}, "base_revision": 0}]}),
    ("POST", "/confirm", {"task_revision": 3, "scope_hash": "scope"}),
    ("POST", "/edit-for-return", {"task_revision": 3, "scope_hash": "scope"}),
    ("POST", "/return", {"task_revision": 3, "scope_hash": "scope"}),
])
def test_portal_forwards_assignment_selection_and_complete_confirmation(monkeypatch, method, suffix, payload):
    from unittest.mock import AsyncMock
    from app.services.platform_client import PlatformClient

    upstream = AsyncMock(return_value={})
    monkeypatch.setattr(PlatformClient, "internal_request", upstream)
    subject_id, task_id, assignment_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    app.dependency_overrides[require_portal_session] = lambda: PortalPrincipal(subject_id=subject_id, username="annotator")
    try:
        response = TestClient(app).request(
            method, f"/portal/tasks/{task_id}{suffix}",
            params={"assignment_id": str(assignment_id)}, json=payload,
            headers={"Idempotency-Key": str(uuid.uuid4())},
        )
        assert response.status_code == 200, response.text
        assert upstream.call_args.kwargs["subject_id"] == str(subject_id)
        assert upstream.call_args.kwargs.get("params", {}).get("assignment_id") == str(assignment_id)
        if payload:
            assert upstream.call_args.kwargs["json"] == payload
    finally:
        app.dependency_overrides.clear()


@pytest.mark.parametrize("status,detail", [
    (409, {"code": "REVISION_CONFLICT", "current_revision": 7, "current_values": {"label": "server"}, "diff_summary": {"label": {"current": "server"}}}),
    (404, {"code": "ASSIGNMENT_NOT_FOUND"}),
    (403, {"code": "SAMPLE_SCOPE_FORBIDDEN"}),
    (422, {"code": "LABEL_VALUE_INVALID", "message": "invalid label"}),
])
def test_portal_preserves_structured_platform_rejections(monkeypatch, status, detail):
    import httpx
    from app.services import platform_client

    transport = httpx.MockTransport(lambda request: httpx.Response(status, json={"detail": detail}))
    original = httpx.AsyncClient
    monkeypatch.setattr(platform_client.httpx, "AsyncClient", lambda **kwargs: original(transport=transport, **kwargs))
    app.dependency_overrides[require_portal_session] = lambda: PortalPrincipal(subject_id=uuid.uuid4(), username="annotator")
    try:
        response = TestClient(app).put(
            f"/portal/tasks/{uuid.uuid4()}/samples/sample-1/labels",
            params={"assignment_id": str(uuid.uuid4())},
            json={"values": {"label": "mine"}, "base_revision": 3},
        )
        assert response.status_code == status, response.text
        assert response.json()["detail"] == detail
    finally:
        app.dependency_overrides.clear()


def test_portal_comment_forwards_selected_assignment(monkeypatch):
    from unittest.mock import AsyncMock
    from app.services.platform_client import PlatformClient

    upstream = AsyncMock(return_value={})
    monkeypatch.setattr(PlatformClient, "internal_request", upstream)
    assignment_id = uuid.uuid4()
    app.dependency_overrides[require_portal_session] = lambda: PortalPrincipal(subject_id=uuid.uuid4(), username="annotator")
    try:
        response = TestClient(app).post(
            "/portal/comments", params={"assignment_id": str(assignment_id)},
            json={"task_id": str(uuid.uuid4()), "sample_id": "sample-2", "content": "note"},
        )
        assert response.status_code == 201, response.text
        assert upstream.call_args.kwargs["params"]["assignment_id"] == str(assignment_id)
    finally:
        app.dependency_overrides.clear()


@pytest.mark.parametrize("status,body", [
    (500, '{"detail": {"code": "INTERNAL_FAILURE", "message": "private upstream details"}}'),
    (401, '{"detail": {"code": "SERVICE_TOKEN_INVALID"}}'),
    (409, "<html>private upstream details</html>"),
    (422, '{"detail": "private upstream details"}'),
])
def test_portal_hides_nonbusiness_upstream_errors(monkeypatch, status, body):
    import httpx
    from app.services import platform_client

    original = httpx.AsyncClient
    transport = httpx.MockTransport(lambda request: httpx.Response(status, content=body))
    monkeypatch.setattr(platform_client.httpx, "AsyncClient", lambda **kwargs: original(transport=transport, **kwargs))
    app.dependency_overrides[require_portal_session] = lambda: PortalPrincipal(subject_id=uuid.uuid4(), username="annotator")
    try:
        response = TestClient(app).get(f"/portal/tasks/{uuid.uuid4()}")
        assert response.status_code == 502
        assert response.json()["detail"]["code"] == "PORTAL_PLATFORM_UNAVAILABLE"
        assert "private upstream details" not in response.text
        assert "SERVICE_TOKEN_INVALID" not in response.text
    finally:
        app.dependency_overrides.clear()
