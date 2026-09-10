import uuid
from datetime import timedelta

import pytest
from fastapi import Request
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models.annotator import AnnotatorAccount
from app.services.annotator_identity import (
    PortalAuthError,
    authenticate_annotator,
    create_portal_session,
    disable_annotator,
    map_annotator_subject,
    register_annotator,
    require_portal_session,
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
    assert mapping.platform_principal_id is None
    with pytest.raises(PortalAuthError, match="PROJECT_ID"):
        map_annotator_subject(db, account.subject_id, None, actor, project_id=uuid.uuid4())


def test_internal_service_token_validates_scope_audience_issuer_and_project(db):
    project_id = uuid.uuid4()
    token = service_token_for_project(project_id, scopes=["assignment:read"])
    request = Request({"type": "http", "method": "GET", "path": "/internal", "headers": [(b"authorization", f"Bearer {token}".encode())]})
    principal = verify_internal_service_token(request, required_scope="assignment:read", project_id=project_id)
    assert principal.project_id == project_id
    with pytest.raises(PortalAuthError) as error:
        verify_internal_service_token(request, required_scope="assignment:write", project_id=project_id)
    assert error.value.code == "SERVICE_SCOPE_FORBIDDEN"
