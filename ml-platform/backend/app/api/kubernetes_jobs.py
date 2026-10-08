"""Week 14 Kubernetes job API: idempotent submit, status, logs, cancel, reconcile."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response
from sqlalchemy.orm import Session, sessionmaker

from app.api.auth import get_current_user
from app.config import settings
from app.database import get_db
from app.models.cloud_resources import (
    KubernetesCluster,
    KubernetesCredentialRef,
    KubernetesNamespace,
)
from app.models.kubernetes_execution import KubernetesJobRun
from app.models.operation import DurableOperation
from app.models.user import User
from app.schemas.kubernetes_execution import JobRunResponse, JobSubmitRequest
from app.services import kubernetes_executor as executor
from app.services.audit import AuditIntent, AuditService
from app.services.kubernetes_client import KubernetesClientError
from app.services.project_access import ProjectAccessError, ProjectAccessService

router = APIRouter(prefix="/api/kubernetes", tags=["kubernetes-jobs"])


def _http_access(error: ProjectAccessError):
    status = 404 if error.hidden else 403
    raise HTTPException(status, {"code": error.code, "message": str(error)})


def _load_job(db: Session, job_id: uuid.UUID, user, permission: str) -> KubernetesJobRun:
    job = db.query(KubernetesJobRun).filter(KubernetesJobRun.id == job_id).first()
    if job is None:
        raise HTTPException(404, {"code": "KUBE_JOB_NOT_FOUND"})
    try:
        ProjectAccessService().require(db, job.project_id, user.id, permission)
    except ProjectAccessError as error:
        _http_access(error)
    return job


def _cluster_and_ref(db: Session, job: KubernetesJobRun):
    cluster = db.query(KubernetesCluster).filter(KubernetesCluster.id == job.cluster_id).first()
    ref = db.query(KubernetesCredentialRef).filter(KubernetesCredentialRef.cluster_id == job.cluster_id).first()
    if cluster is None or ref is None:
        raise HTTPException(404, {"code": "KUBERNETES_NOT_FOUND"})
    return cluster, ref


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
            resource_type="kubernetes_job",
            resource_id=str(resource_id),
            changes=changes,
        ),
        allowed_changes=allowed,
    )


def _echo(request: Request, response: Response) -> None:
    request_id = request.headers.get("X-Request-ID")
    if request_id:
        response.headers["X-Request-ID"] = request_id


def _job_payload(db: Session, job: KubernetesJobRun) -> JobRunResponse:
    """Response with the durable operation's stage/progress attached."""
    data = JobRunResponse.model_validate(job)
    operation = db.get(DurableOperation, job.operation_id)
    if operation is not None:
        data.operation_state = operation.state
        data.operation_progress = operation.progress
    return data


@router.post("/jobs", response_model=JobRunResponse, status_code=201, responses={200: {"model": JobRunResponse}})
def submit_job(
    data: JobSubmitRequest,
    request: Request,
    response: Response,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _echo(request, response)
    if not idempotency_key:
        raise HTTPException(422, {"code": "KUBE_JOB_IDEMPOTENCY_REQUIRED", "message": "Idempotency-Key header is required"})
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
            raise HTTPException(
                422,
                {"code": "KUBERNETES_NAMESPACE_INVALID", "message": "namespace is not registered for this cluster"},
            )

    try:
        with _audit(
            db,
            request,
            current_user,
            cluster.project_id,
            "execution.operate",
            "kubernetes.job.submit",
            "pending",
            {
                "image_ref": data.image_ref,
                "command": data.command,
                "timeout_seconds": data.timeout_seconds,
                "idempotency_key": idempotency_key,
            },
            {"image_ref", "command", "timeout_seconds", "idempotency_key"},
        ):
            job, replayed = executor.submit_job(
                db,
                project_id=cluster.project_id,
                cluster=cluster,
                credential_ref=ref,
                settings=settings,
                image_ref=data.image_ref,
                command=data.command,
                args=data.args,
                env=data.env,
                resources=data.resources,
                timeout_seconds=data.timeout_seconds,
                idempotency_key=idempotency_key,
                actor_id=current_user.id,
                task_id=data.task_id,
                namespace=data.namespace,
            )
    except executor.KubeJobError as error:
        raise HTTPException(error.status, {"code": error.code, "message": error.message})
    except KubernetesClientError as error:
        raise HTTPException(502, {"code": error.code, "message": error.message})

    body = _job_payload(db, job).model_dump(mode="json")
    body["replayed"] = replayed
    response.status_code = 200 if replayed else 201
    return body


@router.get("/jobs")
def list_jobs(
    request: Request,
    response: Response,
    cluster_id: uuid.UUID | None = Query(default=None),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    project_ids = [
        row.id for row in ProjectAccessService().accessible_project_query(db, current_user.id).all()
    ]
    query = db.query(KubernetesJobRun).filter(KubernetesJobRun.project_id.in_(project_ids or [uuid.uuid4()]))
    if cluster_id is not None:
        query = query.filter(KubernetesJobRun.cluster_id == cluster_id)
    total = query.count()
    items = query.order_by(KubernetesJobRun.created_at.desc()).offset(offset).limit(limit).all()
    _echo(request, response)
    return {
        "items": [_job_payload(db, job).model_dump(mode="json") for job in items],
        "total": total,
        "offset": offset,
        "limit": limit,
    }


@router.get("/jobs/{job_id}", response_model=JobRunResponse)
def get_job(
    job_id: uuid.UUID,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    job = _load_job(db, job_id, current_user, "project.read")
    _echo(request, response)
    return _job_payload(db, job)


@router.post("/jobs/{job_id}/cancel", response_model=JobRunResponse)
def cancel_job(
    job_id: uuid.UUID,
    request: Request,
    response: Response,
    reason: str = Query(default=""),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    job = _load_job(db, job_id, current_user, "execution.operate")
    cluster, ref = _cluster_and_ref(db, job)
    try:
        with _audit(
            db,
            request,
            current_user,
            job.project_id,
            "execution.operate",
            "kubernetes.job.cancel",
            job.id,
            {"reason": reason},
            {"reason"},
        ):
            job = executor.cancel_job(db, job, ref, settings, reason=reason)
    except executor.KubeJobError as error:
        raise HTTPException(error.status, {"code": error.code, "message": error.message})
    except KubernetesClientError as error:
        raise HTTPException(502, {"code": error.code, "message": error.message})
    _echo(request, response)
    return JobRunResponse.model_validate(job)


@router.post("/jobs/{job_id}/reconcile", response_model=JobRunResponse)
def reconcile_job(
    job_id: uuid.UUID,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    job = _load_job(db, job_id, current_user, "execution.operate")
    cluster, ref = _cluster_and_ref(db, job)
    try:
        with _audit(
            db,
            request,
            current_user,
            job.project_id,
            "execution.operate",
            "kubernetes.job.reconcile",
            job.id,
            {},
            set(),
        ):
            job = executor.reconcile_job(db, job, ref, settings)
    except KubernetesClientError as error:
        raise HTTPException(502, {"code": error.code, "message": error.message})
    _echo(request, response)
    return JobRunResponse.model_validate(job)


@router.get("/jobs/{job_id}/logs")
def job_logs(
    job_id: uuid.UUID,
    request: Request,
    response: Response,
    cursor: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    job = _load_job(db, job_id, current_user, "project.read")
    cluster, ref = _cluster_and_ref(db, job)
    try:
        result = executor.read_logs(cluster, ref, settings, job, cursor=cursor)
    except KubernetesClientError as error:
        status = 503 if error.code == "KUBERNETES_CLIENT_UNAVAILABLE" else 502
        raise HTTPException(status, {"code": error.code, "message": error.message})
    _echo(request, response)
    return result
