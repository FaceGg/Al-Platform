"""Week 15 Notebook session API: idempotent start, status, HMAC access proxy,
idempotent stop/delete. Cluster credentials never appear in any response."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response
from sqlalchemy.orm import Session, sessionmaker

from app.api.auth import get_current_user
from app.config import settings
from app.database import get_db
from app.models.cloud_resources import KubernetesCluster, KubernetesCredentialRef, KubernetesNamespace
from app.models.developer_resources import NotebookSession
from app.models.user import User
from app.schemas.developer_resources import NotebookResponse, NotebookStartRequest
from app.services import kubernetes_executor
from app.services import notebook_service
from app.services.audit import AuditIntent, AuditService
from app.services.kubernetes_client import KubernetesClientError
from app.services.project_access import ProjectAccessError, ProjectAccessService

router = APIRouter(prefix="/api/notebooks", tags=["notebooks"])


def _http_access(error: ProjectAccessError):
    raise HTTPException(404 if error.hidden else 403, {"code": error.code, "message": str(error)})


def _load_session(db: Session, session_id: uuid.UUID, user, permission: str) -> NotebookSession:
    session = db.query(NotebookSession).filter(NotebookSession.id == session_id).first()
    if session is None:
        raise HTTPException(404, {"code": "NOTEBOOK_NOT_FOUND"})
    try:
        ProjectAccessService().require(db, session.project_id, user.id, permission)
    except ProjectAccessError as error:
        _http_access(error)
    return session


def _cluster_and_ref(db: Session, session: NotebookSession):
    cluster = db.query(KubernetesCluster).filter(KubernetesCluster.id == session.cluster_id).first()
    ref = (
        db.query(KubernetesCredentialRef)
        .filter(KubernetesCredentialRef.cluster_id == session.cluster_id)
        .first()
    )
    if cluster is None or ref is None:
        raise HTTPException(404, {"code": "KUBERNETES_NOT_FOUND"})
    return cluster, ref


def _echo(request: Request, response: Response) -> None:
    request_id = request.headers.get("X-Request-ID")
    if request_id:
        response.headers["X-Request-ID"] = request_id


def _audit(db: Session, request: Request, actor, project_id, permission: str, action: str, resource_id, changes: dict, allowed: set[str]):
    access = ProjectAccessService().require(db, project_id, actor.id, permission)
    return AuditService(sessionmaker(bind=db.get_bind())).project_action(
        db,
        request=request,
        actor=actor,
        access=access,
        permission=permission,
        intent=AuditIntent(
            project_id=project_id,
            action=action,
            resource_type="notebook_session",
            resource_id=str(resource_id),
            changes=changes,
        ),
        allowed_changes=allowed,
    )


@router.post("", response_model=NotebookResponse, status_code=201, responses={200: {"model": NotebookResponse}})
def start_notebook(
    data: NotebookStartRequest,
    request: Request,
    response: Response,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _echo(request, response)
    if not idempotency_key:
        raise HTTPException(422, {"code": "NOTEBOOK_IDEMPOTENCY_REQUIRED", "message": "Idempotency-Key header is required"})
    cluster = db.query(KubernetesCluster).filter(KubernetesCluster.id == data.cluster_id).first()
    if cluster is None:
        raise HTTPException(404, {"code": "KUBERNETES_NOT_FOUND"})
    try:
        ProjectAccessService().require(db, cluster.project_id, current_user.id, "execution.operate")
    except ProjectAccessError as error:
        _http_access(error)
    if cluster.archived_at is not None or cluster.status != "active":
        raise HTTPException(409, {"code": "KUBERNETES_CLUSTER_NOT_ACTIVE"})
    ref = db.query(KubernetesCredentialRef).filter(KubernetesCredentialRef.cluster_id == cluster.id).first()
    if ref is None:
        raise HTTPException(404, {"code": "KUBERNETES_NOT_FOUND"})
    if data.namespace is not None:
        registered = (
            db.query(KubernetesNamespace.id)
            .filter(
                KubernetesNamespace.cluster_id == cluster.id,
                KubernetesNamespace.name == data.namespace,
            )
            .first()
        )
        if registered is None:
            raise HTTPException(422, {"code": "KUBERNETES_NAMESPACE_INVALID"})

    try:
        with _audit(
            db, request, current_user, cluster.project_id, "execution.operate", "notebook.start", "pending",
            {"image_ref": data.image_ref, "idle_timeout_seconds": data.idle_timeout_seconds},
            {"image_ref", "idle_timeout_seconds"},
        ):
            session_row, replayed = notebook_service.start_session(
                db,
                project_id=cluster.project_id,
                user_id=current_user.id,
                cluster=cluster,
                credential_ref=ref,
                run_settings=settings,
                image_ref=data.image_ref,
                resources=data.resources,
                gpu_class_name=data.gpu_class,
                gpu_count=data.gpu_count,
                idle_timeout_seconds=data.idle_timeout_seconds,
                idempotency_key=idempotency_key,
                namespace=data.namespace,
            )
    except notebook_service.NotebookError as error:
        raise HTTPException(error.status, {"code": error.code, "message": error.message})
    except KubernetesClientError as error:
        raise HTTPException(502, {"code": error.code, "message": error.message})
    body = NotebookResponse.model_validate(session_row).model_dump(mode="json")
    body["replayed"] = replayed
    response.status_code = 200 if replayed else 201
    return body


@router.get("")
def list_notebooks(
    request: Request,
    response: Response,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    project_ids = [row.id for row in ProjectAccessService().accessible_project_query(db, current_user.id).all()]
    query = db.query(NotebookSession).filter(NotebookSession.project_id.in_(project_ids or [uuid.uuid4()]))
    total = query.count()
    items = query.order_by(NotebookSession.created_at.desc()).offset(offset).limit(limit).all()
    _echo(request, response)
    return {
        "items": [NotebookResponse.model_validate(row).model_dump(mode="json") for row in items],
        "total": total,
        "offset": offset,
        "limit": limit,
    }


@router.get("/{session_id}", response_model=NotebookResponse)
def get_notebook(
    session_id: uuid.UUID,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    session_row = _load_session(db, session_id, current_user, "project.read")
    _echo(request, response)
    return NotebookResponse.model_validate(session_row)


@router.post("/{session_id}/access")
def notebook_access(
    session_id: uuid.UUID,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    session_row = _load_session(db, session_id, current_user, "project.read")
    if session_row.status != "running":
        raise HTTPException(409, {"code": "NOTEBOOK_NOT_RUNNING", "message": f"session is {session_row.status}"})
    token = notebook_service.mint_access_token(settings, session_id, current_user.id)
    _echo(request, response)
    return {
        "token": token,
        "url": f"/api/notebooks/{session_id}/proxy/",
        "expires_in_seconds": settings.notebook_access_token_ttl_seconds,
    }


@router.get("/{session_id}/proxy/{subpath:path}")
@router.api_route("/{session_id}/proxy", methods=["GET", "POST"], include_in_schema=False)
def notebook_proxy(
    session_id: uuid.UUID,
    request: Request,
    subpath: str = "",
    token: str = Query(default=""),
    db: Session = Depends(get_db),
):
    """Browser-facing proxy: the short-lived HMAC token is the credential
    (browser navigation cannot carry a JWT header); session deletion revokes
    it immediately and project.read is re-checked per request."""
    user_id = notebook_service.verify_access_token(settings, token, session_id)
    if user_id is None:
        raise HTTPException(401, {"code": "NOTEBOOK_ACCESS_TOKEN_INVALID"})
    session_row = (
        db.query(NotebookSession).filter(NotebookSession.id == session_id).first()
    )
    if session_row is None:
        raise HTTPException(404, {"code": "NOTEBOOK_NOT_FOUND"})
    try:
        ProjectAccessService().require(db, session_row.project_id, user_id, "project.read")
    except ProjectAccessError as error:
        _http_access(error)
    if session_row.status != "running":
        raise HTTPException(404, {"code": "NOTEBOOK_NOT_FOUND"})
    cluster, ref = _cluster_and_ref(db, session_row)
    body = request.scope.get("_body") or b""
    try:
        result = notebook_service._client_for(cluster, ref, settings).proxy_service_request(
            namespace=session_row.namespace,
            service=session_row.job_name,
            port=settings.notebook_container_port,
            subpath=subpath,
            method=request.method,
            headers={
                key: value
                for key, value in request.headers.items()
                if key.lower() in ("accept", "content-type", "authorization-xsrf")
            },
            body=body,
        )
    except KubernetesClientError as error:
        raise HTTPException(502, {"code": error.code, "message": error.message})
    notebook_service.touch_activity(db, session_row)
    from fastapi import Response as FastResponse

    proxy_response = FastResponse(content=result["body"], status_code=result["status"])
    for key, value in (result.get("headers") or {}).items():
        if key.lower() not in ("content-length", "transfer-encoding", "connection"):
            proxy_response.headers[key] = value
    return proxy_response


@router.post("/{session_id}/reconcile", response_model=NotebookResponse)
def reconcile_notebook(
    session_id: uuid.UUID,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    session_row = _load_session(db, session_id, current_user, "execution.operate")
    cluster, ref = _cluster_and_ref(db, session_row)
    try:
        session_row = notebook_service.reconcile_session(db, session_row, ref, settings)
    except KubernetesClientError as error:
        raise HTTPException(502, {"code": error.code, "message": error.message})
    _echo(request, response)
    return NotebookResponse.model_validate(session_row)


@router.post("/{session_id}/stop", response_model=NotebookResponse)
def stop_notebook(
    session_id: uuid.UUID,
    request: Request,
    response: Response,
    reason: str = Query(default=""),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    session_row = _load_session(db, session_id, current_user, "execution.operate")
    cluster, ref = _cluster_and_ref(db, session_row)
    try:
        with _audit(
            db, request, current_user, session_row.project_id, "execution.operate", "notebook.stop", session_row.id,
            {"reason": reason}, {"reason"},
        ):
            session_row = notebook_service.stop_session(db, session_row, ref, settings, reason=reason)
    except KubernetesClientError as error:
        raise HTTPException(502, {"code": error.code, "message": error.message})
    _echo(request, response)
    return NotebookResponse.model_validate(session_row)


@router.delete("/{session_id}")
def delete_notebook(
    session_id: uuid.UUID,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    session_row = _load_session(db, session_id, current_user, "execution.operate")
    cluster, ref = _cluster_and_ref(db, session_row)
    try:
        with _audit(
            db, request, current_user, session_row.project_id, "execution.operate", "notebook.delete", session_row.id,
            {}, set(),
        ):
            notebook_service.stop_session(db, session_row, ref, settings, reason="deleted", terminal_status="terminated")
    except KubernetesClientError as error:
        raise HTTPException(502, {"code": error.code, "message": error.message})
    _echo(request, response)
    return {"status": "terminated", "id": str(session_id)}
