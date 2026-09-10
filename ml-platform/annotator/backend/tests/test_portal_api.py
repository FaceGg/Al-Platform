from fastapi.testclient import TestClient
import uuid

from app.main import app
from app.services.session import PortalPrincipal, require_portal_session


def test_portal_exposes_task_and_comment_routes():
    paths = TestClient(app).get("/openapi.json").json()["paths"]
    assert "/portal/tasks" in paths
    assert "/portal/tasks/{task_id}/samples" in paths
    assert "/portal/comments" in paths


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
