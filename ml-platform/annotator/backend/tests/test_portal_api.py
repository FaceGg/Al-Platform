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
    assert "/portal/auth/me" in paths
    assert "/portal/admin/tasks" in paths
    assert "/portal/admin/tasks/{task_id}" in paths
    assert "/portal/admin/tasks/{task_id}/samples" in paths
    assert "/portal/admin/tasks/{task_id}/comments" in paths
    assert "/portal/admin/tasks/{task_id}/accept" in paths
    assert "/portal/admin/tasks/{task_id}/return" in paths


def test_portal_me_requires_session_and_returns_owned_identity(monkeypatch):
    from unittest.mock import AsyncMock
    from app.services.platform_client import PlatformClient

    client = TestClient(app)
    assert client.get("/portal/auth/me").status_code == 401
    subject = uuid.uuid4()
    # /portal/auth/me resolves the cookie server-side; no upstream call needed.
    resolve = AsyncMock(return_value={"subject_id": str(subject), "username": "annotator-a"})
    monkeypatch.setattr(PlatformClient, "resolve_portal_session", resolve)
    client.cookies.set("portal_session", "session-token")
    response = client.get("/portal/auth/me")
    assert response.status_code == 200, response.text
    assert response.json() == {
        "subject_id": str(subject),
        "username": "annotator-a",
        "kind": "annotator",
        "user_id": None,
    }
    client.cookies.delete("portal_session")


def test_portal_me_returns_admin_identity_without_subject(monkeypatch):
    from unittest.mock import AsyncMock
    from app.services.platform_client import PlatformClient

    user_id = uuid.uuid4()
    resolve = AsyncMock(return_value={
        "kind": "admin", "user_id": str(user_id), "username": "admin-a",
    })
    monkeypatch.setattr(PlatformClient, "resolve_portal_session", resolve)
    client = TestClient(app)
    client.cookies.set("portal_session", "admin-token")
    try:
        response = client.get("/portal/auth/me")
        assert response.status_code == 200, response.text
        assert response.json() == {
            "subject_id": None,
            "username": "admin-a",
            "kind": "admin",
            "user_id": str(user_id),
        }
    finally:
        client.cookies.delete("portal_session")


def test_portal_logout_deletes_cookie_with_matching_secure_flags():
    client = TestClient(app)
    response = client.post("/portal/auth/logout")
    assert response.status_code == 204
    set_cookie = response.headers.get("set-cookie", "")
    assert 'portal_session=""' in set_cookie
    assert "Max-Age=0" in set_cookie
    # Secure cookies can only be deleted by Set-Cookie headers that also carry
    # Secure (RFC 6265bis); a bare deletion is silently ignored by browsers.
    assert "Secure" in set_cookie
    assert "HttpOnly" in set_cookie
    assert "SameSite=lax" in set_cookie
    # Only the active viewer's cookie is cleared so the coexisting annotator
    # and admin sessions do not log each other out.
    assert "admin_portal_session" not in set_cookie


def test_portal_logout_admin_viewer_only_clears_admin_cookie():
    client = TestClient(app)
    response = client.post("/portal/auth/logout", headers={"X-Portal-Viewer": "admin"})
    assert response.status_code == 204
    set_cookie = response.headers.get("set-cookie", "")
    assert 'admin_portal_session=""' in set_cookie
    assert "Max-Age=0" in set_cookie
    assert "Secure" in set_cookie
    assert "HttpOnly" in set_cookie
    assert "SameSite=lax" in set_cookie
    assert "portal_session" not in set_cookie.replace("admin_portal_session", "")


def test_portal_annotator_routes_reject_admin_sessions_with_clear_code():
    from app.services.session import require_portal_session
    app.dependency_overrides[require_portal_session] = lambda: PortalPrincipal(
        subject_id=None, username="admin-a", kind="admin", user_id=uuid.uuid4(),
    )
    client = TestClient(app)
    try:
        for method, path in [
            ("GET", "/portal/tasks"),
            ("GET", "/portal/notifications"),
            ("GET", "/portal/comments"),
        ]:
            response = client.request(method, path)
            assert response.status_code == 403, response.text
            assert response.json()["detail"] == {"code": "PORTAL_ANNOTATOR_REQUIRED"}
    finally:
        app.dependency_overrides.clear()


def test_portal_admin_routes_require_admin_kind():
    app.dependency_overrides[require_portal_session] = lambda: PortalPrincipal(
        subject_id=uuid.uuid4(), username="annotator-a",
    )
    client = TestClient(app)
    try:
        response = client.get("/portal/admin/tasks")
        assert response.status_code == 403, response.text
        assert response.json()["detail"] == {"code": "PORTAL_ADMIN_REQUIRED"}
        assert client.get(f"/portal/admin/tasks/{uuid.uuid4()}").status_code == 403
        assert client.get(f"/portal/admin/tasks/{uuid.uuid4()}/samples").status_code == 403
        assert client.get(f"/portal/admin/tasks/{uuid.uuid4()}/comments").status_code == 403
        assert client.post(f"/portal/admin/tasks/{uuid.uuid4()}/comments", json={"sample_id": "s1", "content": "note"}).status_code == 403
        assert client.post(f"/portal/admin/tasks/{uuid.uuid4()}/accept").status_code == 403
        assert client.post(f"/portal/admin/tasks/{uuid.uuid4()}/return", json={"reason": "fix"}).status_code == 403
    finally:
        app.dependency_overrides.clear()


def test_portal_admin_routes_forward_admin_identity_and_scopes(monkeypatch):
    from unittest.mock import AsyncMock
    from app.services.platform_client import PlatformClient

    upstream = AsyncMock(return_value={})
    monkeypatch.setattr(PlatformClient, "internal_request", upstream)
    admin_id, task_id = uuid.uuid4(), uuid.uuid4()
    app.dependency_overrides[require_portal_session] = lambda: PortalPrincipal(
        subject_id=None, username="admin-a", kind="admin", user_id=admin_id,
    )
    client = TestClient(app)
    try:
        response = client.get("/portal/admin/tasks", params={"search": "weld", "limit": 20})
        assert response.status_code == 200, response.text
        assert upstream.call_args.args == ("GET", "/api/internal/portal/admin/tasks")
        assert upstream.call_args.kwargs == {
            "admin_user_id": str(admin_id),
            "scope": "admin_review:read",
            "params": {"limit": 20, "search": "weld"},
        }

        assert client.get(f"/portal/admin/tasks/{task_id}").status_code == 200
        assert upstream.call_args.args == ("GET", f"/api/internal/portal/admin/tasks/{task_id}")
        assert upstream.call_args.kwargs["scope"] == "admin_review:read"

        response = client.get(
            f"/portal/admin/tasks/{task_id}/samples",
            params={"cursor": "abc", "sample_search": "weld"},
        )
        assert response.status_code == 200, response.text
        assert upstream.call_args.kwargs["params"] == {"cursor": "abc", "limit": 50, "sample_search": "weld"}

        response = client.get(f"/portal/admin/tasks/{task_id}/comments", params={"sample_id": "sample-1"})
        assert response.status_code == 200, response.text
        assert upstream.call_args.kwargs["params"] == {"limit": 200, "sample_id": "sample-1"}

        comment = {"sample_id": "sample-1", "content": "check this", "parent_id": None}
        response = client.post(f"/portal/admin/tasks/{task_id}/comments", json=comment)
        assert response.status_code == 201, response.text
        assert upstream.call_args.args == ("POST", f"/api/internal/portal/admin/tasks/{task_id}/comments")
        assert upstream.call_args.kwargs == {
            "admin_user_id": str(admin_id),
            "scope": "admin_review:write",
            "json": comment,
        }

        assert client.post(f"/portal/admin/tasks/{task_id}/accept").status_code == 200
        assert upstream.call_args.args == ("POST", f"/api/internal/portal/admin/tasks/{task_id}/accept")
        assert upstream.call_args.kwargs["scope"] == "admin_review:write"

        response = client.post(f"/portal/admin/tasks/{task_id}/return", json={"reason": "请补充说明"})
        assert response.status_code == 200, response.text
        assert upstream.call_args.args == ("POST", f"/api/internal/portal/admin/tasks/{task_id}/return")
        assert upstream.call_args.kwargs["json"] == {"reason": "请补充说明"}
        assert upstream.call_args.kwargs["scope"] == "admin_review:write"
    finally:
        app.dependency_overrides.clear()


def test_portal_admin_routes_preserve_structured_rejections(monkeypatch):
    from app.services.platform_client import PlatformClient, PlatformClientError

    def reject(*args, **kwargs):
        raise PlatformClientError(
            "internal portal request rejected",
            status_code=409,
            detail={"code": "RETURN_BATCH_REQUIRED"},
        )

    monkeypatch.setattr(PlatformClient, "internal_request", reject)
    admin_id = uuid.uuid4()
    app.dependency_overrides[require_portal_session] = lambda: PortalPrincipal(
        subject_id=None, username="admin-a", kind="admin", user_id=admin_id,
    )
    client = TestClient(app)
    try:
        response = client.post(f"/portal/admin/tasks/{uuid.uuid4()}/comments", json={"sample_id": "s1", "content": "note"})
        assert response.status_code == 409, response.text
        assert response.json()["detail"] == {"code": "RETURN_BATCH_REQUIRED"}
    finally:
        app.dependency_overrides.clear()


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
