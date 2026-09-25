"""Portal authentication and controlled internal identity endpoints."""

import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import String, and_, case, cast, func, or_, select
from sqlalchemy.orm import Session

from app.api.auth import get_current_user
from app.database import get_db
from app.models.data_version import DatasetSample
from app.models.labeling import (
    AnnotationAssignment,
    AnnotationAssignmentSample,
    AnnotationComment,
    AnnotationRevision,
    AnnotationReturnBatch,
    AnnotationSampleCurrent,
)
from app.models.platform_models import AnnotationTaskScopeSample, GenericAnnotationTask
from app.models.operation import DurableOperation
from app.models.project import Project
from app.models.user import User
from app.models.access import AuditEvent
from app.models.annotator import AnnotatorAccount, AnnotatorSubjectMapping, ProjectAnnotatorGrant
from app.models.notifications import InAppNotification
from app.services.annotator_identity import (
    PortalAuthError, authenticate_annotator, map_annotator_subject, register_annotator,
    require_portal_session, disable_annotator, delete_annotator, reset_annotator_password,
    grant_annotator_project, revoke_annotator_project, set_annotator_status, PORTAL_COOKIE_NAME,
    ADMIN_PORTAL_COOKIE_NAME, verify_internal_service_token, ensure_annotator_mapping,
    issue_admin_portal_token, resolve_portal_identity,
)
from app.services.annotation_returns import (
    AnnotationReturnError,
    accept_return_batch,
    reject_return_batch,
)
from app.services.annotation_concurrency import (
    AssignmentError,
    AssignmentLockedError,
    confirm_assignment,
    edit_for_return,
    return_assignment,
    save_labels,
)
from app.services.annotation_task_state import current_annotation_task_snapshot
from app.services.notification_outbox import emit_annotation_comment_notification
from app.services.security import PASSWORD_RESET_LIMIT, enforce_rate_limit

router = APIRouter(tags=["annotator-auth"])

class AnnotatorRegisterRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=8, max_length=128)
    email: str | None = Field(default=None, max_length=320)

def _error(error: PortalAuthError):
    status = 422 if error.code in {"PASSWORD_POLICY", "USERNAME_POLICY"} else 401 if error.code in {"INVALID_CREDENTIALS", "ACCOUNT_NOT_ACTIVE", "PORTAL_SESSION_REQUIRED", "PORTAL_SESSION_INVALID", "ANNOTATOR_SESSION_REVOKED", "ANNOTATOR_SESSION_EXPIRED"} else 409
    return HTTPException(status_code=status, detail={"code": error.code, "message": str(error)})

@router.post("/portal/auth/register", status_code=201)
def portal_register(data: AnnotatorRegisterRequest, db: Session = Depends(get_db)):
    try:
        account = register_annotator(db, username=data.username, password=data.password, email=data.email)
    except PortalAuthError as error:
        raise _error(error) from error
    return {"id": str(account.id), "subject_id": str(account.subject_id), "username": account.username, "status": account.status}

@router.post("/portal/auth/login")
def portal_login(response: Response, form: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    account = db.query(AnnotatorAccount).filter(AnnotatorAccount.username == form.username).first()
    if account is not None:
        # An existing annotator account owns this username: a wrong password
        # must NOT fall through to the platform-admin path.
        try:
            session = authenticate_annotator(db, form.username, form.password)
        except PortalAuthError as error:
            raise _error(error) from error
    else:
        try:
            session = issue_admin_portal_token(db, form.username, form.password)
        except PortalAuthError as error:
            raise _error(error) from error
    response.set_cookie(session.cookie_name, session.token, httponly=True, secure=True, samesite="lax", max_age=1800, path="/")
    return {
        "subject_id": str(session.subject_id) if session.subject_id is not None else None,
        "expires_at": session.expires_at.isoformat(),
        "kind": session.kind,
        "user_id": str(session.user_id) if session.user_id is not None else None,
    }

@router.post("/portal/auth/logout", status_code=204)
def portal_logout(response: Response):
    # Deletion must mirror the login cookie's Secure/HttpOnly/SameSite flags:
    # browsers ignore non-Secure deletions of Secure cookies (RFC 6265bis).
    # Both identity cookies are cleared so a viewer switch never keeps a
    # stale session of the other kind.
    for cookie_name in (PORTAL_COOKIE_NAME, ADMIN_PORTAL_COOKIE_NAME):
        response.delete_cookie(cookie_name, path="/", secure=True, httponly=True, samesite="lax")

@router.get("/portal/auth/me")
def portal_me(
    request: Request,
    viewer: str = Header(default="annotator", alias="X-Portal-Viewer"),
    db: Session = Depends(get_db),
):
    try:
        identity = resolve_portal_identity(request, db, viewer=viewer)
    except PortalAuthError as error:
        raise _error(error) from error
    return {
        "subject_id": str(identity.subject_id) if identity.subject_id is not None else None,
        "username": identity.username,
        "kind": identity.kind,
        "user_id": str(identity.user_id) if identity.user_id is not None else None,
    }

@router.post("/api/internal/annotators/{subject_id}/disable", status_code=204)
def internal_disable(subject_id: uuid.UUID, db: Session = Depends(get_db), admin: User = Depends(get_current_user)):
    if admin.role != "admin":
        raise HTTPException(403, {"code": "ADMIN_REQUIRED"})
    try:
        disable_annotator(db, subject_id)
    except PortalAuthError as error:
        raise _error(error) from error

@router.get("/api/admin/annotators")
def list_admin_annotators(
    status: str | None = Query(default=None, pattern="^(pending|active|rejected|disabled)$"),
    db: Session = Depends(get_db),
    admin: User = Depends(get_current_user),
):
    if admin.role != "admin":
        raise HTTPException(403, {"code": "ADMIN_REQUIRED"})
    query = db.query(AnnotatorAccount).order_by(AnnotatorAccount.created_at.desc(), AnnotatorAccount.id.desc())
    if status:
        query = query.filter(AnnotatorAccount.status == status)
    return {
        "items": [
            {
                "id": str(account.id),
                "subject_id": str(account.subject_id),
                "username": account.username,
                "email": account.email,
                "status": account.status,
                "created_at": account.created_at.isoformat() if account.created_at else None,
            }
            for account in query.all()
        ]
    }

@router.get("/api/annotators")
def list_annotator_subjects(
    q: str | None = Query(default=None, max_length=64),
    project_id: uuid.UUID | None = Query(default=None),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Assignable annotator subjects: approved (active) accounts only.

    `id` is the annotator subject id expected by assignment creation.
    With `project_id`, only annotators holding an active project grant are returned.
    """
    query = db.query(AnnotatorAccount).filter(AnnotatorAccount.status == "active")
    if q and q.strip():
        needle = f"%{q.strip().lower()}%"
        query = query.filter(func.lower(AnnotatorAccount.username).like(needle))
    if project_id is not None:
        query = query.join(
            ProjectAnnotatorGrant,
            and_(
                ProjectAnnotatorGrant.subject_id == AnnotatorAccount.subject_id,
                ProjectAnnotatorGrant.project_id == project_id,
                ProjectAnnotatorGrant.status == "active",
            ),
        )
    accounts = query.order_by(AnnotatorAccount.username, AnnotatorAccount.id).all()
    return {
        "items": [
            {
                "id": str(account.subject_id),
                "username": account.username,
                "email": account.email,
                "display_name": None,
                "status": account.status,
            }
            for account in accounts
        ]
    }

class AnnotatorStatusRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: str = Field(pattern="^(active|rejected|disabled)$")

@router.patch("/api/admin/annotators/{subject_id}/status")
def update_admin_annotator_status(
    subject_id: uuid.UUID,
    data: AnnotatorStatusRequest,
    db: Session = Depends(get_db),
    admin: User = Depends(get_current_user),
):
    if admin.role != "admin":
        raise HTTPException(403, {"code": "ADMIN_REQUIRED"})
    try:
        account = set_annotator_status(db, subject_id, data.status)
    except PortalAuthError as error:
        raise _error(error) from error
    if data.status == "active":
        # Approval must make the annotator fully operational in the portal;
        # without a subject mapping every label write fails with
        # ANNOTATOR_SUBJECT_UNMAPPED.
        ensure_annotator_mapping(db, subject_id, admin)
    return {
        "id": str(account.id),
        "subject_id": str(account.subject_id),
        "username": account.username,
        "email": account.email,
        "status": account.status,
        "created_at": account.created_at.isoformat() if account.created_at else None,
    }

@router.delete("/api/admin/annotators/{subject_id}", status_code=204)
def delete_admin_annotator(
    subject_id: uuid.UUID,
    db: Session = Depends(get_db),
    admin: User = Depends(get_current_user),
):
    if admin.role != "admin":
        raise HTTPException(403, {"code": "ADMIN_REQUIRED"})
    try:
        delete_annotator(db, subject_id)
    except PortalAuthError as error:
        raise _error(error) from error

class PasswordResetRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    password: str = Field(min_length=8, max_length=128)

@router.post("/api/internal/annotators/{subject_id}/reset-password", status_code=204)
def internal_reset_password(subject_id: uuid.UUID, data: PasswordResetRequest, request: Request, db: Session = Depends(get_db), admin: User = Depends(get_current_user)):
    # The reset endpoint is an administrative state change; rate-limit by the
    # caller address before revealing whether the subject exists.
    host = request.client.host if request.client is not None else "unknown"
    enforce_rate_limit(f"auth:password-reset:ip:{host or 'unknown'}", PASSWORD_RESET_LIMIT)
    enforce_rate_limit(f"auth:password-reset:subject:{subject_id}", PASSWORD_RESET_LIMIT)
    if admin.role != "admin":
        raise HTTPException(403, {"code": "ADMIN_REQUIRED"})
    try:
        reset_annotator_password(db, subject_id, data.password)
    except PortalAuthError as error:
        raise _error(error) from error

@router.post("/api/internal/projects/{project_id}/annotators/{subject_id}/grant", status_code=201)
def internal_grant(project_id: uuid.UUID, subject_id: uuid.UUID, db: Session = Depends(get_db), admin: User = Depends(get_current_user)):
    if admin.role != "admin":
        raise HTTPException(403, {"code": "ADMIN_REQUIRED"})
    try:
        grant = grant_annotator_project(db, project_id, subject_id, admin)
    except PortalAuthError as error:
        raise _error(error) from error
    return {"id": str(grant.id), "project_id": str(grant.project_id), "subject_id": str(grant.subject_id), "status": grant.status}

@router.delete("/api/internal/projects/{project_id}/annotators/{subject_id}/grant", status_code=204)
def internal_revoke(project_id: uuid.UUID, subject_id: uuid.UUID, db: Session = Depends(get_db), admin: User = Depends(get_current_user)):
    if admin.role != "admin":
        raise HTTPException(403, {"code": "ADMIN_REQUIRED"})
    try:
        revoke_annotator_project(db, project_id, subject_id, admin)
    except PortalAuthError as error:
        raise _error(error) from error

@router.get("/api/admin/annotators/{subject_id}/grants")
def list_admin_annotator_grants(
    subject_id: uuid.UUID,
    db: Session = Depends(get_db),
    admin: User = Depends(get_current_user),
):
    if admin.role != "admin":
        raise HTTPException(403, {"code": "ADMIN_REQUIRED"})
    grants = db.query(ProjectAnnotatorGrant).filter(
        ProjectAnnotatorGrant.subject_id == subject_id,
    ).order_by(ProjectAnnotatorGrant.created_at.desc(), ProjectAnnotatorGrant.id.desc()).all()
    return {"items": [{"project_id": str(grant.project_id), "status": grant.status} for grant in grants]}

@router.post("/api/internal/annotators/{subject_id}/map")
def internal_map(subject_id: uuid.UUID, platform_principal_id: uuid.UUID | None = None, db: Session = Depends(get_db), admin: User = Depends(get_current_user)):
    try:
        mapping = map_annotator_subject(db, subject_id, platform_principal_id, admin)
    except PortalAuthError as error:
        raise _error(error) from error
    return {"id": str(mapping.id), "subject_id": str(mapping.subject_id), "platform_principal_id": str(mapping.platform_principal_id) if mapping.platform_principal_id else None}


class PortalLabelWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")
    values: dict[str, Any]
    base_revision: int = Field(ge=0)


class PortalBulkLabelItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    sample_id: str = Field(min_length=1, max_length=256)
    values: dict[str, Any]
    base_revision: int = Field(ge=0)


class PortalBulkLabelWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")
    items: list[PortalBulkLabelItem] = Field(min_length=1, max_length=200)


class PortalTaskConfirmation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    task_revision: int = Field(ge=0)
    scope_hash: str = Field(min_length=1, max_length=128)


class PortalCommentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    task_id: uuid.UUID
    content: str = Field(min_length=1, max_length=4000)
    sample_id: str | None = Field(default=None, min_length=1, max_length=256)
    related_revision: int | None = Field(default=None, ge=0)
    parent_id: uuid.UUID | None = None


class CommentResolution(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: str = Field(pattern="^(open|resolved)$")


def _portal_notification_query(db: Session, principal):
    account = db.query(AnnotatorAccount).filter(
        AnnotatorAccount.subject_id == principal.annotator_subject_id,
        AnnotatorAccount.status == "active",
    ).first()
    if account is None:
        raise _portal_error("ANNOTATOR_ACCOUNT_INACTIVE")
    recipients = db.query(AnnotatorSubjectMapping.platform_principal_id).filter(
        AnnotatorSubjectMapping.subject_id == principal.annotator_subject_id,
    )
    projects = db.query(ProjectAnnotatorGrant.project_id).filter(
        ProjectAnnotatorGrant.subject_id == principal.annotator_subject_id,
        ProjectAnnotatorGrant.status == "active",
    )
    query = db.query(InAppNotification).filter(
        InAppNotification.recipient_user_id.in_(recipients),
        InAppNotification.archived_at.is_(None),
        or_(InAppNotification.project_id.is_(None), InAppNotification.project_id.in_(projects)),
    )
    if principal.project_id is not None:
        query = query.filter(InAppNotification.project_id == principal.project_id)
    return query


def _portal_notification_target(db: Session, row: InAppNotification, principal) -> dict[str, str] | None:
    resource_id = row.payload.get("return_batch_id") if isinstance(row.payload, dict) else None
    assignment = None
    task = None
    if row.event_type.startswith("annotation_return") and resource_id:
        try:
            batch = db.get(AnnotationReturnBatch, uuid.UUID(str(resource_id)))
        except (TypeError, ValueError, AttributeError):
            batch = None
        if batch:
            assignment = db.get(AnnotationAssignment, batch.assignment_id)
            task = db.get(GenericAnnotationTask, assignment.task_id) if assignment else None
    elif row.event_type.startswith("annotation_comment"):
        comment_id = row.payload.get("comment_id") if isinstance(row.payload, dict) else None
        try:
            comment = db.get(AnnotationComment, uuid.UUID(str(comment_id))) if comment_id else None
        except (TypeError, ValueError, AttributeError):
            comment = None
        if comment:
            task = db.get(GenericAnnotationTask, comment.task_id)
            assignment = db.query(AnnotationAssignment).filter(
                AnnotationAssignment.task_id == comment.task_id,
                AnnotationAssignment.annotator_subject_id == principal.annotator_subject_id,
                AnnotationAssignment.state != "revoked",
            ).order_by(AnnotationAssignment.created_at.desc()).first()
    if not assignment or not task or assignment.annotator_subject_id != principal.annotator_subject_id:
        return None
    if not _assignment_granted(db, task, principal.annotator_subject_id):
        return None
    return {"task_id": str(task.id), "assignment_id": str(assignment.id)}


@router.get("/api/internal/portal/notifications")
def internal_portal_notifications(
    request: Request,
    cursor: uuid.UUID | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    unread_only: bool = Query(default=False),
    db: Session = Depends(get_db),
):
    principal = _service_principal(request, scope="notification:read", allow_wildcard=True)
    query = _portal_notification_query(db, principal)
    unread_count = query.filter(InAppNotification.read_at.is_(None)).count()
    if unread_only:
        query = query.filter(InAppNotification.read_at.is_(None))
    total = query.count()
    timestamp = InAppNotification.created_at
    sqlite = db.get_bind().dialect.name == "sqlite"
    if sqlite:
        text_timestamp = cast(timestamp, String)
        timestamp = case(
            (func.length(text_timestamp) == 19, text_timestamp + ".000000"),
            else_=text_timestamp,
        )
    if cursor is not None:
        marker = query.filter(InAppNotification.id == cursor).first()
        if marker is None:
            raise _portal_error("INVALID_CURSOR", status_code=422)
        marker_timestamp = marker.created_at.strftime("%Y-%m-%d %H:%M:%S.%f") if sqlite else marker.created_at
        query = query.filter(or_(
            timestamp < marker_timestamp,
            and_(timestamp == marker_timestamp, InAppNotification.id < marker.id),
        ))
    rows = query.order_by(timestamp.desc(), InAppNotification.id.desc()).limit(limit + 1).all()
    has_next = len(rows) > limit
    rows = rows[:limit]
    return {
        "items": [{
            "id": str(row.id), "title": row.title, "body": row.body,
            "event_type": row.event_type, "severity": row.severity,
            "created_at": row.created_at.isoformat(),
            "read_at": row.read_at.isoformat() if row.read_at else None,
            "target": _portal_notification_target(db, row, principal),
        } for row in rows],
        "total": total,
        "unread_count": unread_count,
        "next_cursor": str(rows[-1].id) if has_next else None,
    }


@router.post("/api/internal/portal/notifications/{notification_id}/read")
def internal_portal_read_notification(
    notification_id: uuid.UUID,
    request: Request,
    db: Session = Depends(get_db),
):
    principal = _service_principal(request, scope="notification:write", allow_wildcard=True)
    query = _portal_notification_query(db, principal).filter(InAppNotification.id == notification_id)
    row = query.first()
    if row is None:
        raise _portal_error("NOTIFICATION_NOT_FOUND", status_code=404)
    query.filter(InAppNotification.read_at.is_(None)).update(
        {InAppNotification.read_at: datetime.now(timezone.utc).replace(tzinfo=None)},
        synchronize_session=False,
    )
    db.commit()
    db.refresh(row)
    return {"id": str(row.id), "read_at": row.read_at.isoformat()}


@router.get("/api/annotation-comments")
def list_admin_comments(
    task_id: uuid.UUID,
    status: str | None = Query(default=None, pattern="^(open|resolved)$"),
    sample_id: str | None = Query(default=None, min_length=1, max_length=256),
    thread: str = Query(default="all", pattern="^(all|roots|replies)$"),
    cursor: uuid.UUID | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail={"code": "ADMIN_REQUIRED"})
    task = db.get(GenericAnnotationTask, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail={"code": "ANNOTATION_TASK_NOT_FOUND"})
    query = db.query(AnnotationComment).filter(
        AnnotationComment.task_id == task_id,
    )
    if status is not None:
        query = query.filter(AnnotationComment.status == status)
    if sample_id is not None:
        query = query.filter(AnnotationComment.sample_id == sample_id)
    if thread == "roots":
        query = query.filter(AnnotationComment.parent_id.is_(None))
    elif thread == "replies":
        query = query.filter(AnnotationComment.parent_id.is_not(None))
    total = query.count()
    timestamp = AnnotationComment.created_at
    sqlite = db.get_bind().dialect.name == "sqlite"
    if sqlite:
        text_timestamp = cast(timestamp, String)
        timestamp = case(
            (func.length(text_timestamp) == 19, text_timestamp + ".000000"),
            else_=text_timestamp,
        )
    if cursor is not None:
        marker = query.filter(AnnotationComment.id == cursor).first()
        if marker is None:
            raise HTTPException(status_code=422, detail={"code": "INVALID_CURSOR"})
        marker_timestamp = marker.created_at.strftime("%Y-%m-%d %H:%M:%S.%f") if sqlite else marker.created_at
        query = query.filter(or_(
            timestamp > marker_timestamp,
            and_(timestamp == marker_timestamp, AnnotationComment.id > marker.id),
        ))
    rows = query.order_by(timestamp.asc(), AnnotationComment.id.asc()).limit(limit + 1).all()
    has_next = len(rows) > limit
    rows = rows[:limit]
    return {
        "total": total,
        "next_cursor": str(rows[-1].id) if has_next else None,
        "items": [{
            "id": str(row.id),
            "task_id": str(row.task_id),
            "sample_id": row.sample_id,
            "parent_id": str(row.parent_id) if row.parent_id else None,
            "content": row.body,
            "status": row.status,
            "related_revision": row.revision.revision_no if row.revision else None,
            "resolved_by": str(row.resolved_by) if row.resolved_by else None,
            "resolved_at": row.resolved_at.isoformat() if row.resolved_at else None,
        } for row in rows],
    }


def _portal_error(code: str, *, status_code: int = 403, message: str | None = None) -> HTTPException:
    return HTTPException(status_code=status_code, detail={"code": code, "message": message or code})


def _service_principal(
    request: Request,
    *,
    scope: str,
    project_id: uuid.UUID | None = None,
    allow_wildcard: bool = False,
):
    try:
        principal = verify_internal_service_token(
            request,
            required_scope=scope,
            project_id=project_id,
            allow_wildcard=allow_wildcard,
        )
    except PortalAuthError as error:
        status_code = 401 if error.code in {"SERVICE_TOKEN_REQUIRED", "SERVICE_TOKEN_INVALID"} else 403
        raise _portal_error(error.code, status_code=status_code) from error
    if principal.annotator_subject_id is None:
        raise _portal_error("SERVICE_SUBJECT_REQUIRED")
    return principal


def _assignment_for_subject(db: Session, task_id: uuid.UUID, subject_id: uuid.UUID, assignment_id: uuid.UUID | None = None) -> tuple[GenericAnnotationTask, AnnotationAssignment]:
    task = db.get(GenericAnnotationTask, task_id)
    if task is None or task.archived_at is not None:
        raise _portal_error("ANNOTATION_TASK_NOT_FOUND", status_code=404)
    query = db.query(AnnotationAssignment).filter(
        AnnotationAssignment.task_id == task.id,
        AnnotationAssignment.annotator_subject_id == subject_id,
        AnnotationAssignment.state != "revoked",
    )
    if assignment_id is not None:
        query = query.filter(AnnotationAssignment.id == assignment_id)
    assignments = query.limit(2).all()
    if not assignments:
        raise _portal_error("ASSIGNMENT_NOT_FOUND", status_code=404)
    if len(assignments) > 1:
        raise _portal_error("ASSIGNMENT_SELECTION_REQUIRED", status_code=409)
    return task, assignments[0]


def _task_view(task: GenericAnnotationTask, assignment: AnnotationAssignment, db: Session) -> dict[str, Any]:
    sample_query = db.query(AnnotationAssignmentSample).filter_by(assignment_id=assignment.id)
    total_samples = sample_query.count()
    completed_samples = sample_query.filter(
        func.length(cast(AnnotationAssignmentSample.values, String)) > 2,
    ).count()
    snapshot = current_annotation_task_snapshot(db, task)
    return {
        "id": str(task.id),
        "title": task.name or f"Annotation task {str(task.id)[:8]}",
        "project_id": str(task.project_id),
        "status": task.status,
        "task_revision": assignment.task_revision,
        "scope_hash": assignment.scope_hash,
        "due_at": assignment.due_at.isoformat() if assignment.due_at else None,
        "read_only": assignment.state == "returned_pending_acceptance",
        "assignment_id": str(assignment.id),
        "total_samples": total_samples,
        "completed_samples": completed_samples,
        "state": assignment.state,
        "label_schema": snapshot.get("label_schema") or {"columns": []},
        "instructions": snapshot.get("instructions") or "",
        "visible_columns": list(snapshot.get("visible_columns") or []),
    }


def _assignment_granted(db: Session, task: GenericAnnotationTask, subject_id: uuid.UUID) -> bool:
    grant = db.query(ProjectAnnotatorGrant).filter(
        ProjectAnnotatorGrant.project_id == task.project_id,
        ProjectAnnotatorGrant.subject_id == subject_id,
        ProjectAnnotatorGrant.status == "active",
    ).first()
    return grant is not None


def _assignment_contains_sample(db: Session, assignment: AnnotationAssignment, sample_id: str) -> bool:
    return db.query(AnnotationAssignmentSample.id).filter(
        AnnotationAssignmentSample.assignment_id == assignment.id,
        AnnotationAssignmentSample.sample_id == str(sample_id),
    ).first() is not None


def _portal_platform_principal(db: Session, subject_id: uuid.UUID) -> uuid.UUID:
    # Approval normally creates the mapping, but subjects activated before that
    # guarantee (or via direct database edits) self-heal here with a shadow
    # principal instead of failing every label write with ANNOTATOR_SUBJECT_UNMAPPED.
    mapping = ensure_annotator_mapping(db, subject_id)
    return mapping.platform_principal_id


def _assignment_error(error: AssignmentError) -> HTTPException:
    status_code = 409 if isinstance(error, AssignmentLockedError) or error.code in {
        "REVISION_CONFLICT",
        "ASSIGNMENT_REVISION_CONFLICT",
        "ASSIGNMENT_LOCKED",
    } else 422
    detail = {"code": error.code, "message": str(error)}
    if hasattr(error, "current_revision"):
        detail.update({
            "current_revision": error.current_revision,
            "current_values": error.current_values,
            "diff_summary": error.diff_summary,
        })
    return HTTPException(status_code=status_code, detail=detail)


@router.get("/api/internal/portal/tasks")
def internal_portal_tasks(
    request: Request,
    cursor: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    search: str | None = Query(default=None, max_length=128),
    status: str | None = Query(default=None, max_length=32),
    assignment_state: str | None = Query(default=None, max_length=32),
    sort: str = Query(default="created_at", pattern="^(created_at|due_at|status|assignment_state)$"),
    direction: str = Query(default="desc", pattern="^(asc|desc)$"),
    db: Session = Depends(get_db),
):
    principal = _service_principal(request, scope="assignment:read", allow_wildcard=True)
    query = db.query(AnnotationAssignment).join(
        GenericAnnotationTask,
        GenericAnnotationTask.id == AnnotationAssignment.task_id,
    ).join(
        ProjectAnnotatorGrant,
        and_(
            ProjectAnnotatorGrant.project_id == GenericAnnotationTask.project_id,
            ProjectAnnotatorGrant.subject_id == principal.annotator_subject_id,
            ProjectAnnotatorGrant.status == "active",
        ),
    ).filter(
        AnnotationAssignment.annotator_subject_id == principal.annotator_subject_id,
        AnnotationAssignment.state != "revoked",
        GenericAnnotationTask.archived_at.is_(None),
    )
    normalized_search = search.strip().lower() if search else ""
    if normalized_search:
        task_id_text = func.lower(func.replace(cast(GenericAnnotationTask.id, String), "-", ""))
        search_text = normalized_search.removeprefix("annotation task").strip().replace("-", "")
        name_match = func.lower(GenericAnnotationTask.name).contains(normalized_search, autoescape=True)
        if search_text:
            query = query.filter(or_(task_id_text.contains(search_text, autoescape=True), name_match))
        else:
            query = query.filter(name_match)
    if status:
        query = query.filter(GenericAnnotationTask.status == status)
    if assignment_state:
        query = query.filter(AnnotationAssignment.state == assignment_state)
    total = query.count()
    marker = None
    if cursor:
        try:
            marker_id = uuid.UUID(str(cursor))
        except (TypeError, ValueError, AttributeError) as error:
            raise _portal_error("INVALID_CURSOR", status_code=422) from error
        marker = query.filter(AnnotationAssignment.id == marker_id).one_or_none()
        if marker is None:
            raise _portal_error("INVALID_CURSOR", status_code=422)
    sort_column = {
        "created_at": AnnotationAssignment.created_at,
        "due_at": AnnotationAssignment.due_at,
        "status": GenericAnnotationTask.status,
        "assignment_state": AnnotationAssignment.state,
    }[sort]
    if marker is not None:
        marker_task = db.get(GenericAnnotationTask, marker.task_id)
        marker_value = (
            getattr(marker_task, sort_column.key)
            if sort == "status"
            else getattr(marker, sort_column.key)
        )
        tie = AnnotationAssignment.id > marker.id if direction == "asc" else AnnotationAssignment.id < marker.id
        if marker_value is None:
            query = query.filter(and_(sort_column.is_(None), tie))
        else:
            after = sort_column > marker_value if direction == "asc" else sort_column < marker_value
            same = sort_column == marker_value
            query = query.filter(or_(after, and_(same, tie), sort_column.is_(None)))
    primary = sort_column.asc() if direction == "asc" else sort_column.desc()
    order_columns = (
        primary.nulls_last(),
        AnnotationAssignment.id.asc() if direction == "asc" else AnnotationAssignment.id.desc(),
    )
    assignments = query.order_by(*order_columns).limit(limit + 1).all()
    has_next = len(assignments) > limit
    assignments = assignments[:limit]
    items = []
    for assignment in assignments:
        task = db.get(GenericAnnotationTask, assignment.task_id)
        if task is None:
            continue
        items.append(_task_view(task, assignment, db))
    return {
        "items": items,
        "total": total,
        "next_cursor": str(assignments[-1].id) if has_next and assignments else None,
    }


@router.get("/api/internal/portal/tasks/{task_id}")
def internal_portal_task(task_id: uuid.UUID, request: Request, assignment_id: uuid.UUID | None = Query(default=None), db: Session = Depends(get_db)):
    task = db.get(GenericAnnotationTask, task_id)
    if task is None:
        raise _portal_error("ANNOTATION_TASK_NOT_FOUND", status_code=404)
    principal = _service_principal(request, scope="assignment:read", project_id=task.project_id, allow_wildcard=True)
    if not _assignment_granted(db, task, principal.annotator_subject_id):
        raise _portal_error("PROJECT_ACCESS_FORBIDDEN")
    _task, assignment = _assignment_for_subject(db, task_id, principal.annotator_subject_id, assignment_id)
    return _task_view(task, assignment, db)


@router.get("/api/internal/portal/tasks/{task_id}/samples")
def internal_portal_samples(
    task_id: uuid.UUID,
    request: Request,
    assignment_id: uuid.UUID | None = Query(default=None),
    cursor: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0, le=1_000_000_000),
    sample_search: str | None = Query(default=None, min_length=1, max_length=256),
    label_status: str | None = Query(default=None, pattern="^(complete|incomplete)$"),
    comment_status: str | None = Query(default=None, pattern="^(open|resolved|none)$"),
    modified_after: datetime | None = Query(default=None),
    authorized_field: str | None = Query(default=None, min_length=1, max_length=128),
    authorized_value: str | None = Query(default=None, max_length=256),
    db: Session = Depends(get_db),
):
    task = db.get(GenericAnnotationTask, task_id)
    if task is None:
        raise _portal_error("ANNOTATION_TASK_NOT_FOUND", status_code=404)
    principal = _service_principal(request, scope="assignment:read", project_id=task.project_id, allow_wildcard=True)
    if not _assignment_granted(db, task, principal.annotator_subject_id):
        raise _portal_error("PROJECT_ACCESS_FORBIDDEN")
    _task, assignment = _assignment_for_subject(db, task_id, principal.annotator_subject_id, assignment_id)
    snapshot = current_annotation_task_snapshot(db, task)
    visible_columns = set(snapshot.get("visible_columns") or [])
    if authorized_value is not None and authorized_field is None:
        raise _portal_error("AUTHORIZED_FIELD_REQUIRED", status_code=422)
    if authorized_field is not None and authorized_field not in visible_columns:
        raise _portal_error("AUTHORIZED_FIELD_INVALID", status_code=422)
    required_keys = [
        str(column.get("machine_key"))
        for column in (snapshot.get("label_schema", {}).get("columns") or [])
        if column.get("required") and column.get("machine_key")
    ]
    query = db.query(AnnotationAssignmentSample).join(
        DatasetSample,
        and_(
            DatasetSample.dataset_version_id == task.dataset_version_id,
            DatasetSample.sample_id == AnnotationAssignmentSample.sample_id,
        ),
    ).filter(
        AnnotationAssignmentSample.assignment_id == assignment.id,
    ).order_by(DatasetSample.row_index.asc(), AnnotationAssignmentSample.sample_id.asc())
    if sample_search:
        query = query.filter(AnnotationAssignmentSample.sample_id.contains(sample_search))
    if modified_after:
        platform_principal_id = _portal_platform_principal(db, principal.annotator_subject_id)
        modified_after_utc = (
            modified_after.astimezone(timezone.utc).replace(tzinfo=None)
            if modified_after.tzinfo is not None
            else modified_after
        )
        own_revision = db.query(AnnotationRevision.id).filter(
            AnnotationRevision.task_id == task.id,
            AnnotationRevision.sample_id == AnnotationAssignmentSample.sample_id,
            AnnotationRevision.author_id == platform_principal_id,
            AnnotationRevision.created_at >= modified_after_utc,
        ).exists()
        query = query.filter(own_revision)
    if authorized_field is not None:
        source_field = DatasetSample.values[authorized_field]
        source_match = db.query(DatasetSample.sample_id).filter(
            DatasetSample.dataset_version_id == task.dataset_version_id,
            DatasetSample.sample_id == AnnotationAssignmentSample.sample_id,
            source_field.is_not(None),
        ).correlate(AnnotationAssignmentSample)
        if authorized_value is not None:
            source_match = source_match.filter(
                source_field.as_string().contains(authorized_value),
            )
        query = query.filter(source_match.exists())
    if label_status:
        required = and_(*[AnnotationAssignmentSample.values[key].is_not(None) for key in required_keys]) if required_keys else True
        query = query.filter(required if label_status == "complete" else ~required)
    if comment_status:
        any_comment = db.query(AnnotationComment.id).filter(
            AnnotationComment.task_id == task.id,
            AnnotationComment.sample_id == AnnotationAssignmentSample.sample_id,
        ).exists()
        matching_comment = db.query(AnnotationComment.id).filter(
            AnnotationComment.task_id == task.id,
            AnnotationComment.sample_id == AnnotationAssignmentSample.sample_id,
            AnnotationComment.status == comment_status,
        ).exists()
        query = query.filter(matching_comment if comment_status != "none" else ~any_comment)
    filtered_total = query.order_by(None).count()
    if cursor:
        marker_index = db.query(DatasetSample.row_index).filter(
            DatasetSample.dataset_version_id == task.dataset_version_id,
            DatasetSample.sample_id == cursor,
        ).scalar()
        if marker_index is None:
            raise _portal_error("INVALID_CURSOR", status_code=422)
        query = query.filter(DatasetSample.row_index > marker_index)
    rows = query.offset(offset).limit(limit + 1).all()
    has_next = len(rows) > limit
    rows = rows[:limit]
    source_ids = [row.sample_id for row in rows]
    source_by_id = {
        row.sample_id: {
            key: value for key, value in (row.values or {}).items()
            if key in visible_columns
        }
        for row in db.query(DatasetSample).filter(
            DatasetSample.dataset_version_id == task.dataset_version_id,
            DatasetSample.sample_id.in_(source_ids),
        ).all()
    }
    return {
        "items": [
            {
                "sample_id": row.sample_id,
                "values": source_by_id.get(row.sample_id, {}),
                "labels": row.values or {},
                "revision": row.revision_no,
            }
            for row in rows
        ],
        "total": filtered_total,
        "next_cursor": rows[-1].sample_id if has_next and rows else None,
    }


@router.put("/api/internal/portal/tasks/{task_id}/samples/{sample_id}/labels")
def internal_portal_save_labels(
    task_id: uuid.UUID,
    sample_id: str,
    data: PortalLabelWrite,
    request: Request,
    assignment_id: uuid.UUID | None = Query(default=None),
    db: Session = Depends(get_db),
):
    task = db.get(GenericAnnotationTask, task_id)
    if task is None:
        raise _portal_error("ANNOTATION_TASK_NOT_FOUND", status_code=404)
    principal = _service_principal(request, scope="assignment:write", project_id=task.project_id, allow_wildcard=True)
    if not _assignment_granted(db, task, principal.annotator_subject_id):
        raise _portal_error("PROJECT_ACCESS_FORBIDDEN")
    _task, assignment = _assignment_for_subject(db, task_id, principal.annotator_subject_id, assignment_id)
    platform_principal_id = _portal_platform_principal(db, principal.annotator_subject_id)
    try:
        result = save_labels(
            db,
            assignment.id,
            sample_id,
            data.values,
            data.base_revision,
            actor=platform_principal_id,
            access_actor=assignment.created_by,
        )
    except AssignmentError as error:
        raise _assignment_error(error) from error
    if hasattr(result, "current_values"):
        raise HTTPException(
            status_code=409,
            detail={
                "code": "REVISION_CONFLICT",
                "current_revision": result.current_revision,
                "current_values": result.current_values,
                "diff_summary": result.diff_summary,
            },
        )
    return {
        "values": result.values,
        "revision": result.revision_no,
        "task_revision": assignment.task_revision,
    }


@router.post("/api/internal/portal/tasks/{task_id}/bulk-labels")
def internal_portal_bulk_labels(
    task_id: uuid.UUID,
    data: PortalBulkLabelWrite,
    request: Request,
    assignment_id: uuid.UUID | None = Query(default=None),
    db: Session = Depends(get_db),
):
    task = db.get(GenericAnnotationTask, task_id)
    if task is None:
        raise _portal_error("ANNOTATION_TASK_NOT_FOUND", status_code=404)
    principal = _service_principal(request, scope="assignment:write", project_id=task.project_id, allow_wildcard=True)
    if not _assignment_granted(db, task, principal.annotator_subject_id):
        raise _portal_error("PROJECT_ACCESS_FORBIDDEN")
    _task, assignment = _assignment_for_subject(db, task_id, principal.annotator_subject_id, assignment_id)
    platform_principal_id = _portal_platform_principal(db, principal.annotator_subject_id)
    results = []
    try:
        for item in data.items:
            result = save_labels(
                db,
                assignment.id,
                item.sample_id,
                item.values,
                item.base_revision,
                actor=platform_principal_id,
                access_actor=assignment.created_by,
                commit=False,
            )
            if hasattr(result, "current_values"):
                raise HTTPException(
                    status_code=409,
                    detail={
                        "code": "REVISION_CONFLICT",
                        "sample_id": item.sample_id,
                        "current_revision": result.current_revision,
                        "current_values": result.current_values,
                        "diff_summary": result.diff_summary,
                    },
                )
            results.append({"sample_id": item.sample_id, "values": result.values, "revision": result.revision_no})
        db.commit()
    except HTTPException:
        db.rollback()
        raise
    except AssignmentError as error:
        db.rollback()
        raise _assignment_error(error) from error
    return {"items": results}


@router.post("/api/internal/portal/tasks/{task_id}/confirm")
def internal_portal_confirm(
    task_id: uuid.UUID,
    data: PortalTaskConfirmation,
    request: Request,
    assignment_id: uuid.UUID | None = Query(default=None),
    db: Session = Depends(get_db),
):
    task = db.get(GenericAnnotationTask, task_id)
    if task is None:
        raise _portal_error("ANNOTATION_TASK_NOT_FOUND", status_code=404)
    principal = _service_principal(request, scope="assignment:write", project_id=task.project_id, allow_wildcard=True)
    if not _assignment_granted(db, task, principal.annotator_subject_id):
        raise _portal_error("PROJECT_ACCESS_FORBIDDEN")
    _task, assignment = _assignment_for_subject(db, task_id, principal.annotator_subject_id, assignment_id)
    platform_principal_id = _portal_platform_principal(db, principal.annotator_subject_id)
    try:
        result = confirm_assignment(
            db,
            assignment.id,
            data.task_revision,
            data.scope_hash,
            actor=platform_principal_id,
            access_actor=assignment.created_by,
        )
    except AssignmentError as error:
        raise _assignment_error(error) from error
    return {"assignment_id": str(result.assignment_id), "task_revision": result.task_revision, "scope_hash": result.scope_hash}


@router.post("/api/internal/portal/tasks/{task_id}/edit-for-return")
def internal_portal_edit_for_return(
    task_id: uuid.UUID,
    data: PortalTaskConfirmation,
    request: Request,
    assignment_id: uuid.UUID | None = Query(default=None),
    db: Session = Depends(get_db),
):
    task = db.get(GenericAnnotationTask, task_id)
    if task is None:
        raise _portal_error("ANNOTATION_TASK_NOT_FOUND", status_code=404)
    principal = _service_principal(request, scope="assignment:write", project_id=task.project_id, allow_wildcard=True)
    if not _assignment_granted(db, task, principal.annotator_subject_id):
        raise _portal_error("PROJECT_ACCESS_FORBIDDEN")
    _task, assignment = _assignment_for_subject(db, task_id, principal.annotator_subject_id, assignment_id)
    if assignment.scope_hash != data.scope_hash:
        raise _portal_error("ASSIGNMENT_REVISION_CONFLICT", status_code=409)
    try:
        result = edit_for_return(db, assignment.id, data.task_revision)
    except AssignmentError as error:
        raise _assignment_error(error) from error
    return {"assignment_id": str(result.id), "state": result.state, "task_revision": result.task_revision}


@router.post("/api/internal/portal/tasks/{task_id}/return", status_code=202)
def internal_portal_return(
    task_id: uuid.UUID,
    data: PortalTaskConfirmation,
    request: Request,
    assignment_id: uuid.UUID | None = Query(default=None),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    db: Session = Depends(get_db),
):
    if not idempotency_key:
        raise _portal_error("IDEMPOTENCY_KEY_REQUIRED", status_code=400)
    task = db.get(GenericAnnotationTask, task_id)
    if task is None:
        raise _portal_error("ANNOTATION_TASK_NOT_FOUND", status_code=404)
    principal = _service_principal(request, scope="assignment:return", project_id=task.project_id, allow_wildcard=True)
    if not _assignment_granted(db, task, principal.annotator_subject_id):
        raise _portal_error("PROJECT_ACCESS_FORBIDDEN")
    _task, assignment = _assignment_for_subject(db, task_id, principal.annotator_subject_id, assignment_id)
    try:
        result = return_assignment(db, assignment.id, data.task_revision, data.scope_hash, idempotency_key)
    except AssignmentError as error:
        raise _assignment_error(error) from error
    return {
        "return_batch_id": str(result.return_batch_id),
        "operation_id": str(result.operation_id) if result.operation_id else None,
        "state": result.state,
    }


@router.get("/api/internal/portal/comments")
def internal_portal_comments(
    request: Request,
    task_id: uuid.UUID | None = Query(default=None),
    assignment_id: uuid.UUID | None = Query(default=None),
    cursor: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    principal = _service_principal(request, scope="comment:read", allow_wildcard=True)
    assignments_query = db.query(AnnotationAssignment).join(
        GenericAnnotationTask, GenericAnnotationTask.id == AnnotationAssignment.task_id,
    ).join(
        ProjectAnnotatorGrant,
        and_(
            ProjectAnnotatorGrant.project_id == GenericAnnotationTask.project_id,
            ProjectAnnotatorGrant.subject_id == AnnotationAssignment.annotator_subject_id,
        ),
    ).filter(
        AnnotationAssignment.annotator_subject_id == principal.annotator_subject_id,
        AnnotationAssignment.state != "revoked",
        ProjectAnnotatorGrant.status == "active",
    )
    if principal.project_id is not None:
        assignments_query = assignments_query.filter(GenericAnnotationTask.project_id == principal.project_id)
    if assignment_id is not None:
        assignments_query = assignments_query.filter(AnnotationAssignment.id == assignment_id)
    if task_id is not None:
        assignments_query = assignments_query.filter(AnnotationAssignment.task_id == task_id)
        if assignments_query.first() is None:
            raise _portal_error("ASSIGNMENT_NOT_FOUND", status_code=404)
    allowed_tasks = assignments_query.with_entities(AnnotationAssignment.task_id)
    allowed_samples = assignments_query.join(
        AnnotationAssignmentSample,
        AnnotationAssignmentSample.assignment_id == AnnotationAssignment.id,
    ).filter(
        AnnotationAssignment.task_id == AnnotationComment.task_id,
        AnnotationAssignmentSample.sample_id == AnnotationComment.sample_id,
    ).exists()
    query = db.query(AnnotationComment).filter(
        AnnotationComment.task_id.in_(allowed_tasks),
        or_(AnnotationComment.sample_id.is_(None), allowed_samples),
    )
    timestamp = AnnotationComment.created_at
    if db.get_bind().dialect.name == "sqlite":
        # SQLite CURRENT_TIMESTAMP omits fractional seconds; DateTime binds do not.
        # Normalize both representations so the cursor cannot include itself.
        text_timestamp = cast(timestamp, String)
        timestamp = case(
            (func.length(text_timestamp) == 19, text_timestamp + ".000000"),
            else_=text_timestamp,
        )
    total = query.count()
    if cursor:
        try:
            marker_id = uuid.UUID(cursor)
        except (TypeError, ValueError, AttributeError) as error:
            raise _portal_error("INVALID_CURSOR", status_code=422) from error
        marker = query.filter(AnnotationComment.id == marker_id).first()
        if marker is None:
            raise _portal_error("INVALID_CURSOR", status_code=422)
        same_group = AnnotationComment.revision_id.is_(None) if marker.revision_id is None else AnnotationComment.revision_id.is_not(None)
        marker_timestamp = (
            marker.created_at.strftime("%Y-%m-%d %H:%M:%S.%f")
            if db.get_bind().dialect.name == "sqlite" else marker.created_at
        )
        within_group = and_(
            same_group,
            or_(
                timestamp < marker_timestamp,
                and_(timestamp == marker_timestamp, AnnotationComment.id < marker.id),
            ),
        )
        query = query.filter(
            within_group if marker.revision_id is None
            else or_(within_group, AnnotationComment.revision_id.is_(None))
        )
    # Keep revision-linked comments ahead of task-level notes so a paged
    # response preserves the label context needed by the annotator workspace.
    rows = query.order_by(
        AnnotationComment.revision_id.is_(None).asc(),
        timestamp.desc(),
        AnnotationComment.id.desc(),
    ).limit(limit + 1).all()
    has_next = len(rows) > limit
    rows = rows[:limit]
    return {
        "items": [
            {
                "id": str(row.id),
                "task_id": str(row.task_id),
                "sample_id": row.sample_id,
                "content": row.body,
                "related_revision": (
                    row.revision.revision_no if row.revision is not None else None
                ),
                "parent_id": str(row.parent_id) if row.parent_id else None,
                "status": row.status,
            }
            for row in rows
        ],
        "total": total,
        "next_cursor": str(rows[-1].id) if has_next and rows else None,
    }


@router.post("/api/internal/portal/comments", status_code=201)
def internal_portal_create_comment(
    data: PortalCommentCreate,
    request: Request,
    assignment_id: uuid.UUID | None = Query(default=None),
    db: Session = Depends(get_db),
):
    task = db.get(GenericAnnotationTask, data.task_id)
    if task is None:
        raise _portal_error("ANNOTATION_TASK_NOT_FOUND", status_code=404)
    principal = _service_principal(request, scope="comment:write", project_id=task.project_id, allow_wildcard=True)
    if not _assignment_granted(db, task, principal.annotator_subject_id):
        raise _portal_error("PROJECT_ACCESS_FORBIDDEN")
    _task, assignment = _assignment_for_subject(db, data.task_id, principal.annotator_subject_id, assignment_id)
    if data.sample_id is not None and not _assignment_contains_sample(db, assignment, data.sample_id):
        raise _portal_error("SAMPLE_SCOPE_FORBIDDEN", status_code=403)
    author_principal_id = _portal_platform_principal(db, principal.annotator_subject_id)
    revision_id = None
    if data.related_revision is not None:
        if data.sample_id is None:
            raise _portal_error("COMMENT_REVISION_SAMPLE_REQUIRED", status_code=422)
        revision = db.query(AnnotationRevision).filter(
            AnnotationRevision.task_id == data.task_id,
            AnnotationRevision.sample_id == data.sample_id,
            AnnotationRevision.revision_no == data.related_revision,
        ).one_or_none()
        if revision is None:
            raise _portal_error("ANNOTATION_REVISION_NOT_FOUND", status_code=404)
        if not _assignment_contains_sample(db, assignment, data.sample_id):
            raise _portal_error("SAMPLE_SCOPE_FORBIDDEN", status_code=403)
        revision_id = revision.id
    comment = AnnotationComment(
        task_id=data.task_id,
        sample_id=data.sample_id,
        revision_id=revision_id,
        author_id=author_principal_id,
        body=data.content.strip(),
        parent_id=data.parent_id,
    )
    db.add(comment)
    if data.parent_id is not None:
        parent = db.get(AnnotationComment, data.parent_id)
        if parent is None or parent.task_id != data.task_id:
            raise _portal_error("COMMENT_PARENT_NOT_FOUND", status_code=404)
        if parent.sample_id != data.sample_id:
            raise _portal_error("COMMENT_SCOPE_MISMATCH", status_code=422)
        db.flush()
        emit_annotation_comment_notification(
            db,
            project_id=task.project_id,
            actor_id=author_principal_id,
            recipient_user_id=parent.author_id,
            comment_id=comment.id,
            parent_comment_id=parent.id,
            event_type="annotation_comment.replied",
        )
    db.commit()
    db.refresh(comment)
    return {
        "id": str(comment.id),
        "task_id": str(comment.task_id),
        "sample_id": comment.sample_id,
        "content": comment.body,
        "related_revision": data.related_revision,
        "parent_id": str(comment.parent_id) if comment.parent_id else None,
        "status": comment.status,
    }


@router.patch("/api/annotation-comments/{comment_id}/status")
def update_comment_status(
    comment_id: uuid.UUID,
    data: CommentResolution,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail={"code": "ADMIN_REQUIRED"})
    comment = db.query(AnnotationComment).filter(AnnotationComment.id == comment_id).with_for_update().first()
    if comment is None:
        raise HTTPException(status_code=404, detail={"code": "COMMENT_NOT_FOUND"})
    task = db.get(GenericAnnotationTask, comment.task_id)
    if task is None:
        raise HTTPException(status_code=404, detail={"code": "ANNOTATION_TASK_NOT_FOUND"})
    previous = comment.status
    if previous == data.status:
        return {
            "id": str(comment.id),
            "status": comment.status,
            "resolved_by": str(comment.resolved_by) if comment.resolved_by else None,
            "resolved_at": comment.resolved_at.isoformat() if comment.resolved_at else None,
        }
    comment.status = data.status
    comment.resolved_by = current_user.id if data.status == "resolved" else None
    comment.resolved_at = datetime.now(timezone.utc) if data.status == "resolved" else None
    request_id = uuid.UUID(request.headers.get("X-Request-ID")) if request.headers.get("X-Request-ID") else uuid.uuid4()
    transition_id = uuid.uuid4()
    db.add(AuditEvent(
        id=transition_id,
        project_id=task.project_id,
        actor_id=current_user.id,
        actor_username=current_user.username,
        action="annotation.comment.status",
        result="success",
        resource_type="annotation_comment",
        resource_id=str(comment.id),
        request_id=request_id,
        source_ip=request.client.host if request.client else None,
        changes={"from": previous, "to": data.status, "task_id": str(task.id)},
    ))
    if comment.author_id != current_user.id:
        from app.services.notification_outbox import emit_annotation_comment_notification
        emit_annotation_comment_notification(
            db,
            project_id=task.project_id,
            actor_id=current_user.id,
            recipient_user_id=comment.author_id,
            comment_id=comment.id,
            status=data.status,
            transition_id=transition_id,
            event_type="annotation_comment.status_changed",
        )
    db.commit()
    return {
        "id": str(comment.id),
        "status": comment.status,
        "resolved_by": str(comment.resolved_by) if comment.resolved_by else None,
        "resolved_at": comment.resolved_at.isoformat() if comment.resolved_at else None,
    }


# --- Admin portal review ---------------------------------------------------
#
# Admins review their own (owner_id) tasks in the annotator portal after a
# return batch has been submitted (state="pending"). Identity flows from the
# portal gateway, which mints service tokens carrying an admin_user_id claim.


class AdminCommentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    sample_id: str = Field(min_length=1, max_length=256)
    content: str = Field(min_length=1, max_length=4000)
    parent_id: uuid.UUID | None = None


class AdminReturnRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: str = Field(min_length=1, max_length=2000)


def _admin_service_principal(request: Request, db: Session, *, scope: str) -> tuple[Any, User]:
    try:
        principal = verify_internal_service_token(
            request,
            required_scope=scope,
            project_id=None,
            allow_wildcard=True,
        )
    except PortalAuthError as error:
        status_code = 401 if error.code in {"SERVICE_TOKEN_REQUIRED", "SERVICE_TOKEN_INVALID"} else 403
        raise _portal_error(error.code, status_code=status_code) from error
    if principal.admin_user_id is None:
        raise _portal_error("SERVICE_ADMIN_REQUIRED")
    admin = db.get(User, principal.admin_user_id)
    if admin is None or admin.role != "admin":
        raise _portal_error("SERVICE_ADMIN_REQUIRED")
    return principal, admin


def _admin_task(db: Session, task_id: uuid.UUID, admin_id: uuid.UUID) -> GenericAnnotationTask:
    task = db.get(GenericAnnotationTask, task_id)
    if task is None or task.archived_at is not None or task.owner_id != admin_id:
        raise _portal_error("ANNOTATION_TASK_NOT_FOUND", status_code=404)
    return task


def _task_return_state(db: Session, task_id: uuid.UUID) -> tuple[AnnotationReturnBatch | None, AnnotationReturnBatch | None]:
    """Return (latest batch, latest pending batch) for a task, or (None, None)."""
    batches = db.query(AnnotationReturnBatch).join(
        AnnotationAssignment, AnnotationAssignment.id == AnnotationReturnBatch.assignment_id,
    ).filter(
        AnnotationAssignment.task_id == task_id,
    ).order_by(
        AnnotationReturnBatch.created_at.asc(),
        AnnotationReturnBatch.id.asc(),
    ).all()
    latest = batches[-1] if batches else None
    pending = next((batch for batch in reversed(batches) if batch.state == "pending"), None)
    return latest, pending


def _return_operation_metadata(db: Session, batch: AnnotationReturnBatch | None) -> dict[str, object]:
    """Expose only the durable validation status needed by the review portal.

    A return batch is created before its immutable snapshot is frozen by the
    worker.  The batch's ``pending`` state therefore does not by itself mean
    that review actions are safe to run.
    """
    operation = db.get(DurableOperation, batch.operation_id) if batch is not None and batch.operation_id else None
    summary = dict(operation.result_summary or {}) if operation is not None else {}
    return {
        "return_operation_state": operation.state if operation is not None else None,
        "return_operation_error_code": operation.error_code if operation is not None else None,
        "return_validated_row_count": summary.get("validated_row_count"),
    }


def _task_sample_count(db: Session, task: GenericAnnotationTask) -> int:
    scope = task.sample_scope or {}
    count = scope.get("sample_count")
    if isinstance(count, int) and count >= 0:
        return count
    ids = scope.get("sample_ids")
    if isinstance(ids, list) and ids:
        return len(ids)
    snapshot_ids = current_annotation_task_snapshot(db, task).get("sample_ids")
    if isinstance(snapshot_ids, list) and snapshot_ids:
        return len(snapshot_ids)
    return db.query(AnnotationTaskScopeSample.id).filter(
        AnnotationTaskScopeSample.task_id == task.id,
        AnnotationTaskScopeSample.task_revision == task.task_revision,
    ).count()


def _task_scope_sample_ids(db: Session, task: GenericAnnotationTask) -> set[str]:
    ids = {
        row.sample_id
        for row in db.query(AnnotationTaskScopeSample).filter(
            AnnotationTaskScopeSample.task_id == task.id,
            AnnotationTaskScopeSample.task_revision == task.task_revision,
        ).all()
    }
    if not ids:
        ids = {str(sample_id) for sample_id in (current_annotation_task_snapshot(db, task).get("sample_ids") or [])}
    if not ids:
        ids = {
            row.sample_id
            for row in db.query(DatasetSample.sample_id).filter(
                DatasetSample.dataset_version_id == task.dataset_version_id,
            ).all()
        }
    return ids


@router.get("/api/internal/portal/admin/tasks")
def internal_admin_tasks(
    request: Request,
    cursor: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    search: str | None = Query(default=None, max_length=128),
    db: Session = Depends(get_db),
):
    _principal, admin = _admin_service_principal(request, db, scope="admin_review:read")
    # Project deletion does not cascade to annotation tasks, so tasks of deleted
    # projects stay orphaned (their project_id points nowhere). The main
    # platform's task list joins accessible projects and never shows them; the
    # admin portal must use the same rule or reviewers see tasks that no
    # longer belong to any project.
    existing_project_ids = select(Project.id)
    query = db.query(GenericAnnotationTask).filter(
        GenericAnnotationTask.owner_id == admin.id,
        GenericAnnotationTask.archived_at.is_(None),
        GenericAnnotationTask.project_id.in_(existing_project_ids),
    )
    normalized_search = search.strip().lower() if search else ""
    if normalized_search:
        task_id_text = func.lower(func.replace(cast(GenericAnnotationTask.id, String), "-", ""))
        search_text = normalized_search.removeprefix("annotation task").strip().replace("-", "")
        name_match = func.lower(GenericAnnotationTask.name).contains(normalized_search, autoescape=True)
        if search_text:
            query = query.filter(or_(task_id_text.contains(search_text, autoescape=True), name_match))
        else:
            query = query.filter(name_match)
    total = query.count()
    if cursor:
        try:
            marker_id = uuid.UUID(str(cursor))
        except (TypeError, ValueError, AttributeError) as error:
            raise _portal_error("INVALID_CURSOR", status_code=422) from error
        marker = query.filter(GenericAnnotationTask.id == marker_id).one_or_none()
        if marker is None:
            raise _portal_error("INVALID_CURSOR", status_code=422)
        query = query.filter(GenericAnnotationTask.id < marker_id)
    rows = query.order_by(GenericAnnotationTask.id.desc()).limit(limit + 1).all()
    has_next = len(rows) > limit
    rows = rows[:limit]
    task_ids = [row.id for row in rows]
    assignments_by_task: dict[uuid.UUID, AnnotationAssignment] = {}
    task_of_assignment: dict[uuid.UUID, uuid.UUID] = {}
    if task_ids:
        for assignment in db.query(AnnotationAssignment).filter(
            AnnotationAssignment.task_id.in_(task_ids),
        ).order_by(AnnotationAssignment.created_at.asc(), AnnotationAssignment.id.asc()).all():
            assignments_by_task[assignment.task_id] = assignment
            task_of_assignment[assignment.id] = assignment.task_id
    subject_ids = list({assignment.annotator_subject_id for assignment in assignments_by_task.values()})
    annotator_names = {
        account.subject_id: account.username
        for account in db.query(AnnotatorAccount).filter(AnnotatorAccount.subject_id.in_(subject_ids)).all()
    } if subject_ids else {}
    latest_batch_by_task: dict[uuid.UUID, AnnotationReturnBatch] = {}
    pending_batch_by_task: dict[uuid.UUID, AnnotationReturnBatch] = {}
    assignment_ids = list(task_of_assignment)
    if assignment_ids:
        for batch in db.query(AnnotationReturnBatch).filter(
            AnnotationReturnBatch.assignment_id.in_(assignment_ids),
        ).order_by(AnnotationReturnBatch.created_at.asc(), AnnotationReturnBatch.id.asc()).all():
            batch_task = task_of_assignment.get(batch.assignment_id)
            if batch_task is None:
                continue
            latest_batch_by_task[batch_task] = batch
            if batch.state == "pending":
                pending_batch_by_task[batch_task] = batch
    # Completed-sample progress uses the exact same rule as the annotator
    # portal task list (values longer than "{}"), so progress stays in sync.
    completed_by_assignment: dict[uuid.UUID, int] = {}
    if assignments_by_task:
        for row_assignment_id, count in db.query(
            AnnotationAssignmentSample.assignment_id, func.count(AnnotationAssignmentSample.id),
        ).filter(
            AnnotationAssignmentSample.assignment_id.in_([a.id for a in assignments_by_task.values()]),
            func.length(cast(AnnotationAssignmentSample.values, String)) > 2,
        ).group_by(AnnotationAssignmentSample.assignment_id).all():
            completed_by_assignment[row_assignment_id] = count
    project_names = {
        project.id: project.name
        for project in db.query(Project).filter(Project.id.in_({t.project_id for t in rows})).all()
    } if rows else {}
    items = []
    for task in rows:
        assignment = assignments_by_task.get(task.id)
        latest_batch = latest_batch_by_task.get(task.id)
        items.append({
            "id": str(task.id),
            "title": task.name or f"Annotation task {str(task.id)[:8]}",
            "status": task.status,
            "mode": task.mode,
            "created_at": task.created_at.isoformat() if task.created_at else None,
            "task_revision": task.task_revision,
            "pending_return_batch_id": str(pending_batch_by_task[task.id].id) if task.id in pending_batch_by_task else None,
            "return_state": latest_batch_by_task[task.id].state if task.id in latest_batch_by_task else None,
            **_return_operation_metadata(db, latest_batch),
            "sample_count": _task_sample_count(db, task),
            "completed_samples": completed_by_assignment.get(assignment.id, 0) if assignment is not None else None,
            "annotator_name": annotator_names.get(assignment.annotator_subject_id) if assignment is not None else None,
            "project_name": project_names.get(task.project_id),
        })
    return {
        "items": items,
        "total": total,
        "next_cursor": str(rows[-1].id) if has_next and rows else None,
    }


@router.get("/api/internal/portal/admin/tasks/{task_id}")
def internal_admin_task(task_id: uuid.UUID, request: Request, db: Session = Depends(get_db)):
    _principal, admin = _admin_service_principal(request, db, scope="admin_review:read")
    task = _admin_task(db, task_id, admin.id)
    snapshot = current_annotation_task_snapshot(db, task)
    latest, pending = _task_return_state(db, task.id)
    scope = task.sample_scope or {}
    return {
        "id": str(task.id),
        "title": task.name or f"Annotation task {str(task.id)[:8]}",
        "status": task.status,
        "mode": task.mode,
        "created_at": task.created_at.isoformat() if task.created_at else None,
        "instructions": snapshot.get("instructions") or "",
        "visible_columns": list(snapshot.get("visible_columns") or []),
        "label_schema": snapshot.get("label_schema") or {"columns": []},
        "sample_scope": {
            "kind": scope.get("kind"),
            "sample_count": _task_sample_count(db, task),
            "scope_hash": scope.get("scope_hash"),
        },
        "pending_return_batch_id": str(pending.id) if pending is not None else None,
        "return_state": latest.state if latest is not None else None,
        **_return_operation_metadata(db, latest),
        "read_only": True,
        "task_revision": task.task_revision,
    }


@router.get("/api/internal/portal/admin/tasks/{task_id}/samples")
def internal_admin_samples(
    task_id: uuid.UUID,
    request: Request,
    cursor: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    sample_search: str | None = Query(default=None, min_length=1, max_length=256),
    db: Session = Depends(get_db),
):
    _principal, admin = _admin_service_principal(request, db, scope="admin_review:read")
    task = _admin_task(db, task_id, admin.id)
    snapshot = current_annotation_task_snapshot(db, task)
    visible_columns = set(snapshot.get("visible_columns") or [])
    scope_ids = _task_scope_sample_ids(db, task)
    if not scope_ids:
        return {"items": [], "total": 0, "next_cursor": None}
    query = db.query(DatasetSample).filter(
        DatasetSample.dataset_version_id == task.dataset_version_id,
        DatasetSample.sample_id.in_(scope_ids),
    )
    if sample_search:
        query = query.filter(DatasetSample.sample_id.contains(sample_search))
    total = query.order_by(None).count()
    if cursor:
        marker_index = db.query(DatasetSample.row_index).filter(
            DatasetSample.dataset_version_id == task.dataset_version_id,
            DatasetSample.sample_id == cursor,
        ).scalar()
        if marker_index is None:
            raise _portal_error("INVALID_CURSOR", status_code=422)
        query = query.filter(DatasetSample.row_index > marker_index)
    rows = query.order_by(DatasetSample.row_index.asc(), DatasetSample.id.asc()).limit(limit + 1).all()
    has_next = len(rows) > limit
    rows = rows[:limit]
    current_by_sample = {
        row.sample_id: row
        for row in db.query(AnnotationSampleCurrent).filter(
            AnnotationSampleCurrent.task_id == task.id,
            AnnotationSampleCurrent.sample_id.in_([row.sample_id for row in rows]),
        ).all()
    } if rows else {}
    items = []
    for row in rows:
        current = current_by_sample.get(row.sample_id)
        values = row.values or {}
        if visible_columns:
            values = {key: value for key, value in values.items() if key in visible_columns}
        items.append({
            "sample_id": row.sample_id,
            "values": values,
            "labels": dict(current.values or {}) if current is not None else {},
            "revision": current.revision_no if current is not None else None,
        })
    return {
        "items": items,
        "total": total,
        "next_cursor": rows[-1].sample_id if has_next and rows else None,
    }


@router.get("/api/internal/portal/admin/tasks/{task_id}/comments")
def internal_admin_comments(
    task_id: uuid.UUID,
    request: Request,
    sample_id: str | None = Query(default=None, min_length=1, max_length=256),
    limit: int = Query(default=200, ge=1, le=500),
    db: Session = Depends(get_db),
):
    _principal, admin = _admin_service_principal(request, db, scope="admin_review:read")
    task = _admin_task(db, task_id, admin.id)
    query = db.query(AnnotationComment).filter(AnnotationComment.task_id == task.id)
    if sample_id is not None:
        query = query.filter(AnnotationComment.sample_id == sample_id)
    total = query.count()
    rows = query.order_by(AnnotationComment.created_at.asc(), AnnotationComment.id.asc()).limit(limit).all()
    author_ids = {row.author_id for row in rows}
    authors = {
        user.id: user.username
        for user in db.query(User).filter(User.id.in_(author_ids)).all()
    } if author_ids else {}
    return {
        "items": [{
            "id": str(row.id),
            "sample_id": row.sample_id,
            "parent_id": str(row.parent_id) if row.parent_id else None,
            "author_name": authors.get(row.author_id),
            "content": row.body,
            "status": row.status,
            "created_at": row.created_at.isoformat() if row.created_at else None,
        } for row in rows],
        "total": total,
    }


@router.post("/api/internal/portal/admin/tasks/{task_id}/comments", status_code=201)
def internal_admin_create_comment(task_id: uuid.UUID, data: AdminCommentCreate, request: Request, db: Session = Depends(get_db)):
    _principal, admin = _admin_service_principal(request, db, scope="admin_review:write")
    task = _admin_task(db, task_id, admin.id)
    _latest, pending = _task_return_state(db, task.id)
    if pending is None:
        raise _portal_error("RETURN_BATCH_REQUIRED", status_code=409)
    if data.sample_id not in _task_scope_sample_ids(db, task):
        raise _portal_error("SAMPLE_SCOPE_FORBIDDEN", status_code=403)
    if data.parent_id is not None:
        parent = db.get(AnnotationComment, data.parent_id)
        if parent is None or parent.task_id != task.id:
            raise _portal_error("COMMENT_PARENT_NOT_FOUND", status_code=404)
        if parent.sample_id != data.sample_id:
            raise _portal_error("COMMENT_SCOPE_MISMATCH", status_code=422)
    comment = AnnotationComment(
        task_id=task.id,
        sample_id=data.sample_id,
        revision_id=None,
        author_id=admin.id,
        body=data.content.strip(),
        parent_id=data.parent_id,
    )
    db.add(comment)
    db.commit()
    db.refresh(comment)
    return {
        "id": str(comment.id),
        "task_id": str(comment.task_id),
        "sample_id": comment.sample_id,
        "parent_id": str(comment.parent_id) if comment.parent_id else None,
        "author_name": admin.username,
        "content": comment.body,
        "status": comment.status,
        "created_at": comment.created_at.isoformat() if comment.created_at else None,
    }


@router.post("/api/internal/portal/admin/tasks/{task_id}/accept")
def internal_admin_accept(task_id: uuid.UUID, request: Request, db: Session = Depends(get_db)):
    _principal, admin = _admin_service_principal(request, db, scope="admin_review:write")
    task = _admin_task(db, task_id, admin.id)
    _latest, pending = _task_return_state(db, task.id)
    if pending is None:
        raise _portal_error("RETURN_BATCH_REQUIRED", status_code=409)
    try:
        accepted = accept_return_batch(db, pending.id, task.task_revision, actor=admin)
    except AnnotationReturnError as error:
        raise _portal_error(error.code, status_code=409) from error
    db.refresh(task)
    return {
        "dataset_version_id": str(accepted.id),
        "status": task.status,
        "version": accepted.version,
    }


@router.post("/api/internal/portal/admin/tasks/{task_id}/return")
def internal_admin_return(task_id: uuid.UUID, data: AdminReturnRequest, request: Request, db: Session = Depends(get_db)):
    _principal, admin = _admin_service_principal(request, db, scope="admin_review:write")
    task = _admin_task(db, task_id, admin.id)
    _latest, pending = _task_return_state(db, task.id)
    if pending is None:
        raise _portal_error("RETURN_BATCH_REQUIRED", status_code=409)
    try:
        batch = reject_return_batch(db, pending.id, task.task_revision, data.reason, actor=admin)
    except AnnotationReturnError as error:
        raise _portal_error(error.code, status_code=409) from error
    return {"return_batch_id": str(batch.id), "state": batch.state}
