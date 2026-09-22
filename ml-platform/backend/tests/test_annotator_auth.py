import uuid
from datetime import timedelta

import pytest
from fastapi import Request
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.auth import get_current_user
from app.database import Base, get_db
from app.main import app
from app.models.annotator import (
    AnnotatorAccount,
    AnnotatorSession,
    AnnotatorSubjectMapping,
    ProjectAnnotatorGrant,
)
from app.models.labeling import AnnotationAssignment
from app.models.project import Project
from app.models.user import User
from app.services.annotator_identity import (
    PortalAuthError,
    authenticate_annotator,
    create_portal_session,
    delete_annotator,
    disable_annotator,
    grant_annotator_project,
    map_annotator_subject,
    register_annotator,
    require_portal_session,
    revoke_annotator_project,
    service_token_for_project,
    verify_internal_service_token,
)


@pytest.fixture()
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()


def test_portal_registration_requires_eight_character_password(db):
    with pytest.raises(PortalAuthError) as error:
        register_annotator(db, username="annotator-a", password="short")
    assert error.value.code == "PASSWORD_POLICY"


def test_portal_login_and_cookie_session_is_independent(db):
    account = register_annotator(db, username="annotator-a", password="valid-pass-8", status="active")
    session = authenticate_annotator(db, "annotator-a", "valid-pass-8")
    assert session.subject_id == account.subject_id
    assert session.cookie_name != "access_token"
    assert session.token


def test_disabled_or_reset_annotator_session_is_invalidated(db):
    account = register_annotator(db, username="annotator-a", password="valid-pass-8", status="active")
    portal = create_portal_session(db, account)
    disable_annotator(db, account.subject_id)
    request = Request({"type": "http", "method": "GET", "path": "/portal/tasks", "headers": [(b"cookie", f"{portal.cookie_name}={portal.token}".encode())]})
    with pytest.raises(PortalAuthError) as error:
        require_portal_session(request, db)
    assert error.value.code == "ANNOTATOR_SESSION_REVOKED"


def test_subject_mapping_uses_server_owned_subject_and_project_grant(db):
    account = register_annotator(db, username="annotator-a", password="valid-pass-8", status="active")
    actor = type("Actor", (), {"id": uuid.uuid4(), "role": "admin"})()
    mapping = map_annotator_subject(db, account.subject_id, None, actor)
    assert mapping.subject_id == account.subject_id
    assert mapping.platform_principal_id is not None
    shadow = db.get(User, mapping.platform_principal_id)
    assert shadow is not None
    assert shadow.role == "annotator"
    assert shadow.username.startswith("annotator-shadow-")
    with pytest.raises(PortalAuthError, match="PROJECT_ID"):
        map_annotator_subject(db, account.subject_id, None, actor, project_id=uuid.uuid4())


def test_delete_annotator_revokes_assignments_and_removes_identity(db):
    account = register_annotator(db, username="annotator-a", password="valid-pass-8", status="active")
    create_portal_session(db, account)
    owner = User(username=f"owner-{uuid.uuid4().hex}", password_hash="hash")
    db.add(owner)
    db.flush()
    project = Project(name="Delete annotator project", owner_id=owner.id)
    db.add(project)
    db.flush()
    other_subject = uuid.uuid4()
    db.add_all([
        AnnotatorSubjectMapping(subject_id=account.subject_id, created_by=owner.id),
        ProjectAnnotatorGrant(project_id=project.id, subject_id=account.subject_id, granted_by=owner.id, status="active"),
        AnnotationAssignment(task_id=uuid.uuid4(), annotator_subject_id=account.subject_id, sample_scope={}, scope_hash="scope-a", created_by=owner.id, state="in_progress"),
        AnnotationAssignment(task_id=uuid.uuid4(), annotator_subject_id=other_subject, sample_scope={}, scope_hash="scope-b", created_by=owner.id, state="in_progress"),
    ])
    db.commit()
    subject_id = account.subject_id
    delete_annotator(db, subject_id)
    assert db.query(AnnotatorAccount).filter(AnnotatorAccount.subject_id == subject_id).first() is None
    assert db.query(AnnotatorSession).count() == 0
    assert db.query(AnnotatorSubjectMapping).count() == 0
    assert db.query(ProjectAnnotatorGrant).count() == 0
    assignments = db.query(AnnotationAssignment).all()
    assert len(assignments) == 2
    states = {assignment.annotator_subject_id: assignment.state for assignment in assignments}
    assert states[subject_id] == "revoked"
    assert states[other_subject] == "in_progress"


def test_delete_annotator_requires_existing_account(db):
    with pytest.raises(PortalAuthError) as error:
        delete_annotator(db, uuid.uuid4())
    assert error.value.code == "ACCOUNT_NOT_FOUND"


def test_admin_delete_annotator_endpoint_enforces_admin_role():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine, expire_on_commit=False)()
    admin = User(username=f"admin-{uuid.uuid4().hex}", password_hash="hash", role="admin")
    engineer = User(username=f"engineer-{uuid.uuid4().hex}", password_hash="hash")
    db.add_all([admin, engineer])
    db.commit()
    account = register_annotator(db, username="annotator-del", password="valid-pass-8")
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: engineer
    try:
        client = TestClient(app)
        assert client.delete(f"/api/admin/annotators/{account.subject_id}").status_code == 403
        assert db.query(AnnotatorAccount).count() == 1
        app.dependency_overrides[get_current_user] = lambda: admin
        assert client.delete(f"/api/admin/annotators/{account.subject_id}").status_code == 204
        assert db.query(AnnotatorAccount).count() == 0
        assert client.delete(f"/api/admin/annotators/{account.subject_id}").status_code == 409
    finally:
        app.dependency_overrides.clear()
        db.close()
        engine.dispose()


def test_admin_approval_creates_and_preserves_subject_mapping():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine, expire_on_commit=False)()
    admin = User(username=f"admin-{uuid.uuid4().hex}", password_hash="hash", role="admin")
    db.add(admin)
    db.commit()
    account = register_annotator(db, username="annotator-approve", password="valid-pass-8")
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: admin
    try:
        client = TestClient(app)
        approved = client.patch(
            f"/api/admin/annotators/{account.subject_id}/status",
            json={"status": "active"},
        )
        assert approved.status_code == 200, approved.text
        mapping = db.query(AnnotatorSubjectMapping).filter_by(subject_id=account.subject_id).one()
        assert mapping.platform_principal_id is not None
        assert mapping.created_by == admin.id
        shadow = db.get(User, mapping.platform_principal_id)
        assert shadow is not None and shadow.role == "annotator"
        # Repeated status changes must not replace the existing mapping with a
        # fresh shadow principal.
        client.patch(f"/api/admin/annotators/{account.subject_id}/status", json={"status": "rejected"})
        reactivated = client.patch(
            f"/api/admin/annotators/{account.subject_id}/status",
            json={"status": "active"},
        )
        assert reactivated.status_code == 200, reactivated.text
        assert (
            db.query(AnnotatorSubjectMapping).filter_by(subject_id=account.subject_id).one().platform_principal_id
            == mapping.platform_principal_id
        )
    finally:
        app.dependency_overrides.clear()
        db.close()
        engine.dispose()


def test_list_annotator_subjects_returns_active_only_with_search():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine, expire_on_commit=False)()
    user = User(username=f"engineer-{uuid.uuid4().hex}", password_hash="hash")
    owner = User(username=f"owner-{uuid.uuid4().hex}", password_hash="hash")
    db.add_all([user, owner])
    db.commit()
    active = register_annotator(db, username="alice-active", password="valid-pass-8", email="alice@example.com", status="active")
    register_annotator(db, username="bob-pending", password="valid-pass-8")
    carol = register_annotator(db, username="carol-active", password="valid-pass-8", status="active")
    granted_project = Project(name="Granted filter project", owner_id=owner.id)
    ungranted_project = Project(name="Ungated filter project", owner_id=owner.id)
    db.add_all([granted_project, ungranted_project])
    db.commit()
    grant_annotator_project(db, granted_project.id, carol.subject_id, user)
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: user
    try:
        client = TestClient(app)
        response = client.get("/api/annotators")
        assert response.status_code == 200
        items = response.json()["items"]
        assert [item["username"] for item in items] == ["alice-active", "carol-active"]
        assert all(item["status"] == "active" for item in items)
        assert str(active.subject_id) in {item["id"] for item in items}
        by_username = {item["username"]: item for item in items}
        assert by_username["alice-active"]["email"] == "alice@example.com"
        assert by_username["carol-active"]["email"] is None
        search = client.get("/api/annotators", params={"q": "carol"})
        assert [item["username"] for item in search.json()["items"]] == ["carol-active"]
        granted = client.get("/api/annotators", params={"project_id": str(granted_project.id)})
        assert granted.status_code == 200
        granted_items = granted.json()["items"]
        assert [item["username"] for item in granted_items] == ["carol-active"]
        assert str(carol.subject_id) in {item["id"] for item in granted_items}
        ungranted = client.get("/api/annotators", params={"project_id": str(ungranted_project.id)})
        assert ungranted.status_code == 200
        assert ungranted.json()["items"] == []
    finally:
        app.dependency_overrides.clear()
        db.close()
        engine.dispose()


def test_admin_annotator_grants_endpoint_requires_admin_and_lists_all_statuses():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine, expire_on_commit=False)()
    admin = User(username=f"admin-{uuid.uuid4().hex}", password_hash="hash", role="admin")
    engineer = User(username=f"engineer-{uuid.uuid4().hex}", password_hash="hash")
    owner = User(username=f"owner-{uuid.uuid4().hex}", password_hash="hash")
    db.add_all([admin, engineer, owner])
    db.commit()
    account = register_annotator(db, username="annotator-grants", password="valid-pass-8", status="active")
    granted_project = Project(name="Granted project", owner_id=owner.id)
    revoked_project = Project(name="Revoked project", owner_id=owner.id)
    db.add_all([granted_project, revoked_project])
    db.commit()
    grant_annotator_project(db, granted_project.id, account.subject_id, admin)
    grant_annotator_project(db, revoked_project.id, account.subject_id, admin)
    revoke_annotator_project(db, revoked_project.id, account.subject_id, admin)
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: engineer
    try:
        client = TestClient(app)
        assert client.get(f"/api/admin/annotators/{account.subject_id}/grants").status_code == 403
        app.dependency_overrides[get_current_user] = lambda: admin
        response = client.get(f"/api/admin/annotators/{account.subject_id}/grants")
        assert response.status_code == 200
        items = {(item["project_id"], item["status"]) for item in response.json()["items"]}
        assert (str(granted_project.id), "active") in items
        assert (str(revoked_project.id), "revoked") in items
    finally:
        app.dependency_overrides.clear()
        db.close()
        engine.dispose()


def test_internal_service_token_validates_scope_audience_issuer_and_project(db):
    project_id = uuid.uuid4()
    token = service_token_for_project(project_id, scopes=["assignment:read"])
    request = Request({"type": "http", "method": "GET", "path": "/internal", "headers": [(b"authorization", f"Bearer {token}".encode())]})
    principal = verify_internal_service_token(request, required_scope="assignment:read", project_id=project_id)
    assert principal.project_id == project_id
    with pytest.raises(PortalAuthError) as error:
        verify_internal_service_token(request, required_scope="assignment:write", project_id=project_id)
    assert error.value.code == "SERVICE_SCOPE_FORBIDDEN"
