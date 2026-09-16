"""Portal authentication and controlled internal identity endpoints."""

import uuid
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import String, and_, cast, func
from sqlalchemy.orm import Session

from app.api.auth import get_current_user
from app.database import get_db
from app.models.data_version import DatasetSample
from app.models.labeling import (
    AnnotationAssignment,
    AnnotationAssignmentSample,
    AnnotationComment,
    AnnotationRevision,
)
from app.models.platform_models import GenericAnnotationTask
from app.models.user import User
from app.models.annotator import AnnotatorSubjectMapping, ProjectAnnotatorGrant
from app.services.annotator_identity import (
    PortalAuthError, authenticate_annotator, map_annotator_subject, register_annotator,
    require_portal_session, disable_annotator, reset_annotator_password,
    grant_annotator_project, revoke_annotator_project, PORTAL_COOKIE_NAME,
    verify_internal_service_token,
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
from app.services.security import PASSWORD_RESET_LIMIT, enforce_rate_limit

router = APIRouter(tags=["annotator-auth"])

class AnnotatorRegisterRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=8, max_length=128)
    email: str | None = Field(default=None, max_length=320)

def _error(error: PortalAuthError):
    status = 422 if error.code in {"PASSWORD_POLICY", "USERNAME_POLICY"} else 401 if error.code in {"INVALID_CREDENTIALS", "ACCOUNT_NOT_ACTIVE", "PORTAL_SESSION_REQUIRED", "ANNOTATOR_SESSION_REVOKED", "ANNOTATOR_SESSION_EXPIRED"} else 409
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
    try:
        session = authenticate_annotator(db, form.username, form.password)
    except PortalAuthError as error:
        raise _error(error) from error
    response.set_cookie(session.cookie_name, session.token, httponly=True, secure=True, samesite="lax", max_age=1800, path="/")
    return {"subject_id": str(session.subject_id), "expires_at": session.expires_at.isoformat()}

@router.post("/portal/auth/logout", status_code=204)
def portal_logout(response: Response):
    response.delete_cookie(PORTAL_COOKIE_NAME, path="/")

@router.get("/portal/auth/me")
def portal_me(request: Request, db: Session = Depends(get_db)):
    try:
        principal = require_portal_session(request, db)
    except PortalAuthError as error:
        raise _error(error) from error
    return {"subject_id": str(principal.subject_id), "username": principal.username}

@router.post("/api/internal/annotators/{subject_id}/disable", status_code=204)
def internal_disable(subject_id: uuid.UUID, db: Session = Depends(get_db), admin: User = Depends(get_current_user)):
    if admin.role != "admin":
        raise HTTPException(403, {"code": "ADMIN_REQUIRED"})
    try:
        disable_annotator(db, subject_id)
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
    try:
        grant = grant_annotator_project(db, project_id, subject_id, admin)
    except PortalAuthError as error:
        raise _error(error) from error
    return {"id": str(grant.id), "project_id": str(grant.project_id), "subject_id": str(grant.subject_id), "status": grant.status}

@router.delete("/api/internal/projects/{project_id}/annotators/{subject_id}/grant", status_code=204)
def internal_revoke(project_id: uuid.UUID, subject_id: uuid.UUID, db: Session = Depends(get_db), admin: User = Depends(get_current_user)):
    try:
        revoke_annotator_project(db, project_id, subject_id, admin)
    except PortalAuthError as error:
        raise _error(error) from error

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


def _assignment_for_subject(db: Session, task_id: uuid.UUID, subject_id: uuid.UUID) -> tuple[GenericAnnotationTask, AnnotationAssignment]:
    task = db.get(GenericAnnotationTask, task_id)
    if task is None:
        raise _portal_error("ANNOTATION_TASK_NOT_FOUND", status_code=404)
    assignment = db.query(AnnotationAssignment).filter(
        AnnotationAssignment.task_id == task.id,
        AnnotationAssignment.annotator_subject_id == subject_id,
        AnnotationAssignment.state != "revoked",
    ).order_by(AnnotationAssignment.created_at.desc()).first()
    if assignment is None:
        raise _portal_error("ASSIGNMENT_NOT_FOUND", status_code=404)
    return task, assignment


def _task_view(task: GenericAnnotationTask, assignment: AnnotationAssignment, db: Session) -> dict[str, Any]:
    sample_query = db.query(AnnotationAssignmentSample).filter_by(assignment_id=assignment.id)
    total_samples = sample_query.count()
    completed_samples = sample_query.filter(
        func.length(cast(AnnotationAssignmentSample.values, String)) > 2,
    ).count()
    snapshot = current_annotation_task_snapshot(db, task)
    return {
        "id": str(task.id),
        "title": f"Annotation task {str(task.id)[:8]}",
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
    mapping = db.query(AnnotatorSubjectMapping).filter(
        AnnotatorSubjectMapping.subject_id == subject_id,
    ).one_or_none()
    if mapping is None or mapping.platform_principal_id is None:
        raise _portal_error("ANNOTATOR_SUBJECT_UNMAPPED")
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
    )
    total = query.count()
    if cursor:
        try:
            marker_id = uuid.UUID(str(cursor))
        except (TypeError, ValueError, AttributeError) as error:
            raise _portal_error("INVALID_CURSOR", status_code=422) from error
        marker = query.filter(AnnotationAssignment.id == marker_id).one_or_none()
        if marker is None:
            raise _portal_error("INVALID_CURSOR", status_code=422)
        query = query.filter(AnnotationAssignment.id < marker.id)
    assignments = query.order_by(
        AnnotationAssignment.id.desc(),
    ).limit(limit + 1).all()
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
def internal_portal_task(task_id: uuid.UUID, request: Request, db: Session = Depends(get_db)):
    task = db.get(GenericAnnotationTask, task_id)
    if task is None:
        raise _portal_error("ANNOTATION_TASK_NOT_FOUND", status_code=404)
    principal = _service_principal(request, scope="assignment:read", project_id=task.project_id, allow_wildcard=True)
    if not _assignment_granted(db, task, principal.annotator_subject_id):
        raise _portal_error("PROJECT_ACCESS_FORBIDDEN")
    _task, assignment = _assignment_for_subject(db, task_id, principal.annotator_subject_id)
    return _task_view(task, assignment, db)


@router.get("/api/internal/portal/tasks/{task_id}/samples")
def internal_portal_samples(
    task_id: uuid.UUID,
    request: Request,
    cursor: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    task = db.get(GenericAnnotationTask, task_id)
    if task is None:
        raise _portal_error("ANNOTATION_TASK_NOT_FOUND", status_code=404)
    principal = _service_principal(request, scope="assignment:read", project_id=task.project_id, allow_wildcard=True)
    if not _assignment_granted(db, task, principal.annotator_subject_id):
        raise _portal_error("PROJECT_ACCESS_FORBIDDEN")
    _task, assignment = _assignment_for_subject(db, task_id, principal.annotator_subject_id)
    snapshot = current_annotation_task_snapshot(db, task)
    query = db.query(AnnotationAssignmentSample).filter(
        AnnotationAssignmentSample.assignment_id == assignment.id,
    ).order_by(AnnotationAssignmentSample.sample_id.asc())
    if cursor:
        marker = query.filter(AnnotationAssignmentSample.sample_id == cursor).one_or_none()
        if marker is None:
            raise _portal_error("INVALID_CURSOR", status_code=422)
        query = query.filter(AnnotationAssignmentSample.sample_id > marker.sample_id)
    rows = query.limit(limit + 1).all()
    has_next = len(rows) > limit
    rows = rows[:limit]
    source_ids = [row.sample_id for row in rows]
    visible_columns = set(snapshot.get("visible_columns") or [])
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
        "total": db.query(AnnotationAssignmentSample).filter_by(assignment_id=assignment.id).count(),
        "next_cursor": rows[-1].sample_id if has_next and rows else None,
    }


@router.put("/api/internal/portal/tasks/{task_id}/samples/{sample_id}/labels")
def internal_portal_save_labels(
    task_id: uuid.UUID,
    sample_id: str,
    data: PortalLabelWrite,
    request: Request,
    db: Session = Depends(get_db),
):
    task = db.get(GenericAnnotationTask, task_id)
    if task is None:
        raise _portal_error("ANNOTATION_TASK_NOT_FOUND", status_code=404)
    principal = _service_principal(request, scope="assignment:write", project_id=task.project_id, allow_wildcard=True)
    if not _assignment_granted(db, task, principal.annotator_subject_id):
        raise _portal_error("PROJECT_ACCESS_FORBIDDEN")
    _task, assignment = _assignment_for_subject(db, task_id, principal.annotator_subject_id)
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
    db: Session = Depends(get_db),
):
    task = db.get(GenericAnnotationTask, task_id)
    if task is None:
        raise _portal_error("ANNOTATION_TASK_NOT_FOUND", status_code=404)
    principal = _service_principal(request, scope="assignment:write", project_id=task.project_id, allow_wildcard=True)
    if not _assignment_granted(db, task, principal.annotator_subject_id):
        raise _portal_error("PROJECT_ACCESS_FORBIDDEN")
    _task, assignment = _assignment_for_subject(db, task_id, principal.annotator_subject_id)
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
    db: Session = Depends(get_db),
):
    task = db.get(GenericAnnotationTask, task_id)
    if task is None:
        raise _portal_error("ANNOTATION_TASK_NOT_FOUND", status_code=404)
    principal = _service_principal(request, scope="assignment:write", project_id=task.project_id, allow_wildcard=True)
    if not _assignment_granted(db, task, principal.annotator_subject_id):
        raise _portal_error("PROJECT_ACCESS_FORBIDDEN")
    _task, assignment = _assignment_for_subject(db, task_id, principal.annotator_subject_id)
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
    db: Session = Depends(get_db),
):
    task = db.get(GenericAnnotationTask, task_id)
    if task is None:
        raise _portal_error("ANNOTATION_TASK_NOT_FOUND", status_code=404)
    principal = _service_principal(request, scope="assignment:write", project_id=task.project_id, allow_wildcard=True)
    if not _assignment_granted(db, task, principal.annotator_subject_id):
        raise _portal_error("PROJECT_ACCESS_FORBIDDEN")
    _task, assignment = _assignment_for_subject(db, task_id, principal.annotator_subject_id)
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
    _task, assignment = _assignment_for_subject(db, task_id, principal.annotator_subject_id)
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
    cursor: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    principal = _service_principal(request, scope="comment:read", allow_wildcard=True)
    assignments_query = db.query(AnnotationAssignment).filter(
        AnnotationAssignment.annotator_subject_id == principal.annotator_subject_id,
        AnnotationAssignment.state != "revoked",
    )
    assignment_task_ids = [row.task_id for row in assignments_query.all()]
    if task_id is not None:
        if task_id not in assignment_task_ids:
            raise _portal_error("ASSIGNMENT_NOT_FOUND", status_code=404)
        assignment_task_ids = [task_id]
    query = db.query(AnnotationComment).filter(AnnotationComment.task_id.in_(assignment_task_ids))
    total = query.count()
    if cursor:
        try:
            marker_id = uuid.UUID(cursor)
        except (TypeError, ValueError, AttributeError) as error:
            raise _portal_error("INVALID_CURSOR", status_code=422) from error
        marker = db.get(AnnotationComment, marker_id)
        if marker is None:
            raise _portal_error("INVALID_CURSOR", status_code=422)
        if marker.task_id not in assignment_task_ids:
            raise _portal_error("INVALID_CURSOR", status_code=422)
        query = query.filter(AnnotationComment.id < marker.id)
    # Keep revision-linked comments ahead of task-level notes so a paged
    # response preserves the label context needed by the annotator workspace.
    rows = query.order_by(
        AnnotationComment.revision_id.is_(None).asc(),
        AnnotationComment.created_at.desc(),
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
    db: Session = Depends(get_db),
):
    task = db.get(GenericAnnotationTask, data.task_id)
    if task is None:
        raise _portal_error("ANNOTATION_TASK_NOT_FOUND", status_code=404)
    principal = _service_principal(request, scope="comment:write", project_id=task.project_id, allow_wildcard=True)
    if not _assignment_granted(db, task, principal.annotator_subject_id):
        raise _portal_error("PROJECT_ACCESS_FORBIDDEN")
    _task, assignment = _assignment_for_subject(db, data.task_id, principal.annotator_subject_id)
    if data.sample_id is not None and not _assignment_contains_sample(db, assignment, data.sample_id):
        raise _portal_error("SAMPLE_SCOPE_FORBIDDEN", status_code=403)
    mapping = db.query(AnnotatorSubjectMapping).filter(
        AnnotatorSubjectMapping.subject_id == principal.annotator_subject_id,
    ).one_or_none()
    if mapping is None or mapping.platform_principal_id is None:
        raise _portal_error("ANNOTATOR_SUBJECT_UNMAPPED")
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
        author_id=mapping.platform_principal_id,
        body=data.content.strip(),
    )
    db.add(comment)
    db.commit()
    db.refresh(comment)
    return {
        "id": str(comment.id),
        "task_id": str(comment.task_id),
        "sample_id": comment.sample_id,
        "content": comment.body,
        "related_revision": data.related_revision,
    }
