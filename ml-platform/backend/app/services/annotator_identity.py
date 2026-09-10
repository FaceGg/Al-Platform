"""Independent annotator authentication, sessions and service identity."""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import secrets
import uuid

import jwt
from fastapi import Request
from passlib.context import CryptContext
from sqlalchemy.orm import Session

from app.config import settings
from app.models.annotator import AnnotatorAccount, AnnotatorSession, AnnotatorSubjectMapping, ProjectAnnotatorGrant
from app.models.labeling import AnnotationAssignment
from app.models.platform_models import GenericAnnotationTask

pwd_context = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto")
PORTAL_COOKIE_NAME = "portal_session"

class PortalAuthError(ValueError):
    def __init__(self, code: str, message: str | None = None):
        self.code = code
        super().__init__(message or code)

@dataclass(frozen=True)
class PortalSession:
    token: str
    cookie_name: str
    subject_id: uuid.UUID
    expires_at: datetime

@dataclass(frozen=True)
class AnnotatorPrincipal:
    subject_id: uuid.UUID
    account_id: uuid.UUID
    username: str

@dataclass(frozen=True)
class ServicePrincipal:
    service_id: str
    project_id: uuid.UUID | None
    scopes: frozenset[str]
    annotator_subject_id: uuid.UUID | None = None

def _now() -> datetime:
    return datetime.now(timezone.utc)

def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()

def register_annotator(db: Session, *, username: str, password: str, email: str | None = None, status: str = "pending") -> AnnotatorAccount:
    if len(password) < 8 or len(password) > 128:
        raise PortalAuthError("PASSWORD_POLICY", "Password must contain 8-128 characters")
    if not username or len(username) > 64:
        raise PortalAuthError("USERNAME_POLICY")
    if db.query(AnnotatorAccount).filter(AnnotatorAccount.username == username).first():
        raise PortalAuthError("ACCOUNT_EXISTS")
    account = AnnotatorAccount(username=username, email=email, password_hash=pwd_context.hash(password), status=status)
    db.add(account)
    db.commit()
    db.refresh(account)
    return account

def authenticate_annotator(db: Session, username: str, password: str) -> PortalSession:
    account = db.query(AnnotatorAccount).filter(AnnotatorAccount.username == username).first()
    if account is None or not pwd_context.verify(password, account.password_hash):
        raise PortalAuthError("INVALID_CREDENTIALS")
    if account.status != "active":
        raise PortalAuthError("ACCOUNT_NOT_ACTIVE")
    return create_portal_session(db, account)

def create_portal_session(db: Session, account: AnnotatorAccount, ttl_seconds: int | None = None) -> PortalSession:
    now = _now()
    expires = now + timedelta(seconds=ttl_seconds or settings.annotator_session_ttl_seconds)
    token = secrets.token_urlsafe(48)
    db.add(AnnotatorSession(account_id=account.id, token_hash=_hash_token(token), session_version=account.session_version, expires_at=expires.replace(tzinfo=None)))
    db.commit()
    return PortalSession(token=token, cookie_name=PORTAL_COOKIE_NAME, subject_id=account.subject_id, expires_at=expires)

def disable_annotator(db: Session, subject_id: uuid.UUID) -> None:
    account = db.query(AnnotatorAccount).filter(AnnotatorAccount.subject_id == subject_id).first()
    if account is None:
        raise PortalAuthError("ACCOUNT_NOT_FOUND")
    account.status = "disabled"
    account.session_version += 1
    db.query(AnnotatorSession).filter(AnnotatorSession.account_id == account.id, AnnotatorSession.revoked_at.is_(None)).update({AnnotatorSession.revoked_at: _now().replace(tzinfo=None)}, synchronize_session=False)
    db.commit()

def reset_annotator_password(db: Session, subject_id: uuid.UUID, password: str) -> None:
    if len(password) < 8 or len(password) > 128:
        raise PortalAuthError("PASSWORD_POLICY")
    account = db.query(AnnotatorAccount).filter(AnnotatorAccount.subject_id == subject_id).first()
    if account is None:
        raise PortalAuthError("ACCOUNT_NOT_FOUND")
    account.password_hash = pwd_context.hash(password)
    account.session_version += 1
    db.query(AnnotatorSession).filter(AnnotatorSession.account_id == account.id, AnnotatorSession.revoked_at.is_(None)).update({AnnotatorSession.revoked_at: _now().replace(tzinfo=None)}, synchronize_session=False)
    db.commit()

def grant_annotator_project(db: Session, project_id: uuid.UUID, subject_id: uuid.UUID, actor) -> ProjectAnnotatorGrant:
    if getattr(actor, "id", None) is None:
        raise PortalAuthError("GRANT_ACTOR_REQUIRED")
    account = db.query(AnnotatorAccount).filter(AnnotatorAccount.subject_id == subject_id, AnnotatorAccount.status == "active").first()
    if account is None:
        raise PortalAuthError("ANNOTATOR_NOT_ACTIVE")
    grant = db.query(ProjectAnnotatorGrant).filter(ProjectAnnotatorGrant.project_id == project_id, ProjectAnnotatorGrant.subject_id == subject_id).first()
    if grant is None:
        grant = ProjectAnnotatorGrant(project_id=project_id, subject_id=subject_id, granted_by=actor.id, status="active")
        db.add(grant)
    else:
        grant.status = "active"; grant.revoked_at = None; grant.granted_by = actor.id
    db.commit(); db.refresh(grant)
    return grant

def revoke_annotator_project(db: Session, project_id: uuid.UUID, subject_id: uuid.UUID, actor) -> None:
    grant = db.query(ProjectAnnotatorGrant).filter(ProjectAnnotatorGrant.project_id == project_id, ProjectAnnotatorGrant.subject_id == subject_id, ProjectAnnotatorGrant.status == "active").first()
    if grant is None:
        raise PortalAuthError("PROJECT_GRANT_NOT_FOUND")
    account = db.query(AnnotatorAccount).filter(AnnotatorAccount.subject_id == subject_id).first()
    grant.status = "revoked"; grant.revoked_at = _now().replace(tzinfo=None)
    # Existing assignments are resource grants too; revoking a project grant
    # must immediately prevent reads/writes through previously issued scopes.
    task_ids = [row.id for row in db.query(GenericAnnotationTask.id).filter(GenericAnnotationTask.project_id == project_id).all()]
    if task_ids:
        db.query(AnnotationAssignment).filter(
            AnnotationAssignment.task_id.in_(task_ids),
            AnnotationAssignment.annotator_subject_id == subject_id,
            AnnotationAssignment.state != "revoked",
        ).update({AnnotationAssignment.state: "revoked"}, synchronize_session=False)
    if account is not None:
        account.session_version += 1
        db.query(AnnotatorSession).filter(AnnotatorSession.account_id == account.id, AnnotatorSession.revoked_at.is_(None)).update({AnnotatorSession.revoked_at: _now().replace(tzinfo=None)}, synchronize_session=False)
    db.commit()

def require_portal_session(request: Request, db: Session) -> AnnotatorPrincipal:
    token = request.cookies.get(PORTAL_COOKIE_NAME)
    if not token:
        raise PortalAuthError("PORTAL_SESSION_REQUIRED")
    session = db.query(AnnotatorSession).filter(AnnotatorSession.token_hash == _hash_token(token)).first()
    if session is None or session.revoked_at is not None:
        raise PortalAuthError("ANNOTATOR_SESSION_REVOKED")
    expires = session.expires_at.replace(tzinfo=timezone.utc) if session.expires_at.tzinfo is None else session.expires_at
    if expires <= _now():
        raise PortalAuthError("ANNOTATOR_SESSION_EXPIRED")
    account = db.query(AnnotatorAccount).filter(AnnotatorAccount.id == session.account_id).first()
    if account is None or account.status != "active" or account.session_version != session.session_version:
        raise PortalAuthError("ANNOTATOR_SESSION_REVOKED")
    return AnnotatorPrincipal(account.subject_id, account.id, account.username)

def map_annotator_subject(db: Session, subject_id: uuid.UUID, platform_principal_id: uuid.UUID | None, actor, *, project_id: uuid.UUID | None = None) -> AnnotatorSubjectMapping:
    if project_id is not None:
        raise PortalAuthError("PROJECT_ID_NOT_CLIENT_SUPPLIED")
    if getattr(actor, "role", None) != "admin":
        raise PortalAuthError("MAPPING_ADMIN_REQUIRED")
    if db.query(AnnotatorAccount).filter(AnnotatorAccount.subject_id == subject_id).first() is None:
        raise PortalAuthError("ACCOUNT_NOT_FOUND")
    mapping = db.query(AnnotatorSubjectMapping).filter(AnnotatorSubjectMapping.subject_id == subject_id).first()
    if mapping is None:
        mapping = AnnotatorSubjectMapping(subject_id=subject_id, platform_principal_id=platform_principal_id, created_by=getattr(actor, "id", None))
        db.add(mapping)
    else:
        mapping.platform_principal_id = platform_principal_id
    db.commit()
    db.refresh(mapping)
    return mapping

def service_token_for_project(
    project_id: uuid.UUID | str | None,
    *,
    scopes: list[str],
    service_id: str = "annotator-portal",
    annotator_subject_id: uuid.UUID | None = None,
) -> str:
    now = _now()
    payload = {
        "iss": settings.annotator_service_issuer,
        "aud": settings.annotator_service_audience,
        "sub": service_id,
        "project_id": "*" if project_id is None else str(project_id),
        "scope": " ".join(sorted(set(scopes))),
        "nonce": secrets.token_urlsafe(16),
        "iat": now,
        "exp": now + timedelta(seconds=60),
    }
    if annotator_subject_id is not None:
        payload["annotator_subject_id"] = str(annotator_subject_id)
    return jwt.encode(payload, settings.resolved_annotator_service_secret.get_secret_value(), algorithm=settings.annotator_service_algorithm)

def verify_internal_service_token(
    request: Request,
    required_scope: str,
    project_id: uuid.UUID | None,
    *,
    allow_wildcard: bool = False,
) -> ServicePrincipal:
    header = request.headers.get("Authorization", "")
    if not header.startswith("Bearer "):
        raise PortalAuthError("SERVICE_TOKEN_REQUIRED")
    try:
        payload = jwt.decode(header[7:], settings.resolved_annotator_service_secret.get_secret_value(), algorithms=[settings.annotator_service_algorithm], audience=settings.annotator_service_audience, issuer=settings.annotator_service_issuer)
    except jwt.InvalidTokenError as error:
        raise PortalAuthError("SERVICE_TOKEN_INVALID") from error
    scopes = frozenset(str(payload.get("scope", "")).split())
    if required_scope not in scopes:
        raise PortalAuthError("SERVICE_SCOPE_FORBIDDEN")
    if not payload.get("nonce"):
        raise PortalAuthError("SERVICE_NONCE_REQUIRED")
    project_claim = payload.get("project_id")
    if not isinstance(project_claim, str) or not project_claim:
        raise PortalAuthError("SERVICE_PROJECT_REQUIRED")
    if project_id is not None:
        if project_claim != str(project_id) and not (allow_wildcard and project_claim == "*"):
            raise PortalAuthError("SERVICE_PROJECT_FORBIDDEN")
        resolved_project = project_id
    elif project_claim == "*":
        resolved_project = None
    else:
        try:
            resolved_project = uuid.UUID(project_claim)
        except (TypeError, ValueError, AttributeError) as error:
            raise PortalAuthError("SERVICE_PROJECT_INVALID") from error
    subject_claim = payload.get("annotator_subject_id")
    subject_id = None
    if subject_claim is not None:
        try:
            subject_id = uuid.UUID(str(subject_claim))
        except (TypeError, ValueError, AttributeError) as error:
            raise PortalAuthError("SERVICE_SUBJECT_INVALID") from error
    service_id = payload.get("sub")
    if not isinstance(service_id, str) or not service_id:
        raise PortalAuthError("SERVICE_ID_REQUIRED")
    return ServicePrincipal(service_id, resolved_project, scopes, subject_id)
