import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.auth import get_current_user
from app.database import Base, get_db
from app.main import app
from app.models.labeling import SavedAnnotationStrategy
from app.models.project import Project
from app.models.user import User


@pytest.fixture()
def api_context():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, expire_on_commit=False)()
    owner = User(username=f"strategy-owner-{uuid.uuid4().hex}", password_hash="hash")
    other = User(username=f"strategy-other-{uuid.uuid4().hex}", password_hash="hash")
    session.add_all([owner, other])
    session.flush()
    project = Project(name="Saved strategy project", owner_id=owner.id)
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


def _strategy_payload(project_id, name="default-strategy", strategy="cluster"):
    return {
        "project_id": str(project_id),
        "name": name,
        "payload": {
            "strategy": strategy,
            "selectedClusters": ["cluster-1"],
            "otherValues": {"label": "ng"},
            "clusterLabels": {"cluster-1": {"label": "ok"}},
            "rules": [],
        },
    }


def test_save_strategy_creates_lists_and_upserts_by_name(api_context):
    client, db, owner, _, project = api_context

    first = client.post("/api/annotations/saved-strategies", json=_strategy_payload(project.id))
    assert first.status_code == 200, first.text
    first_id = first.json()["id"]

    listed = client.get("/api/annotations/saved-strategies", params={"project_id": str(project.id)})
    assert listed.status_code == 200, listed.text
    assert [item["id"] for item in listed.json()["items"]] == [first_id]
    assert listed.json()["items"][0]["payload"]["strategy"] == "cluster"

    updated = client.post(
        "/api/annotations/saved-strategies",
        json=_strategy_payload(project.id, name="default-strategy", strategy="rule"),
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["id"] == first_id
    assert updated.json()["payload"]["strategy"] == "rule"

    count = db.query(SavedAnnotationStrategy).filter_by(project_id=project.id).count()
    assert count == 1


def test_save_strategy_rejects_invalid_payload(api_context):
    client, _, _, _, project = api_context
    payload = _strategy_payload(project.id)
    payload["payload"]["strategy"] = "unknown"
    response = client.post("/api/annotations/saved-strategies", json=payload)
    assert response.status_code == 422


def test_saved_strategy_access_requires_project_membership(api_context):
    client, _, _, other, project = api_context
    client.post("/api/annotations/saved-strategies", json=_strategy_payload(project.id))

    app.dependency_overrides[get_current_user] = lambda: other
    denied_list = client.get("/api/annotations/saved-strategies", params={"project_id": str(project.id)})
    assert denied_list.status_code in (403, 404)
    denied_save = client.post("/api/annotations/saved-strategies", json=_strategy_payload(project.id))
    assert denied_save.status_code in (403, 404)
