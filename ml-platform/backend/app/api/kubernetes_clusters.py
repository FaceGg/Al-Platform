"""Week 13 Kubernetes foundation API: project-scoped cluster registry.

All reads require project.read; management writes reuse the existing
resource.create/update/delete permission strings. Cross-project access is a
hidden 404. Credential material never appears in requests or responses — only
``env:``/``file:`` references.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from sqlalchemy.orm import Session, sessionmaker

from app.api.auth import get_current_user
from app.database import get_db
from app.config import settings
from app.models.cloud_resources import (
    KubernetesCluster,
    KubernetesCredentialRef,
    KubernetesNamespace,
    KubernetesResourceGroup,
)
from app.models.user import User
from app.schemas.cloud_resources import (
    ClusterCreate,
    ClusterResponse,
    ClusterUpdate,
    ConnectivityCheckResponse,
    NamespaceEnsureRequest,
    NamespaceResponse,
    ResourceGroupCreate,
    ResourceGroupResponse,
    ResourceGroupUpdate,
)
from app.services import kubernetes_cluster as cluster_service
from app.services.audit import AuditIntent, AuditService
from app.services.kubernetes_client import KubernetesClientError
from app.services.project_access import ProjectAccessError, ProjectAccessService

router = APIRouter(prefix="/api/kubernetes", tags=["kubernetes"])

AUDIT_ALLOWED_CLUSTER = {"name", "display_name", "api_server_url", "insecure_tls", "provider", "default_namespace", "secret_ref"}


def _http_access(error: ProjectAccessError):
    status = 404 if error.hidden else 403
    raise HTTPException(status, {"code": error.code, "message": str(error)})


def _require(db: Session, project_id, user, permission: str):
    try:
        return ProjectAccessService().require(db, project_id, user.id, permission)
    except ProjectAccessError as error:
        _http_access(error)


def _load_cluster(db: Session, cluster_id: uuid.UUID, user, permission: str) -> KubernetesCluster:
    """Resolve a cluster for the user or raise the hidden 404."""
    cluster = (
        db.query(KubernetesCluster)
        .filter(KubernetesCluster.id == cluster_id, KubernetesCluster.archived_at.is_(None))
        .first()
    )
    if cluster is None:
        raise HTTPException(404, {"code": "KUBERNETES_NOT_FOUND"})
    try:
        ProjectAccessService().require(db, cluster.project_id, user.id, permission)
    except ProjectAccessError as error:
        _http_access(error)
    return cluster


def _credential(db: Session, cluster_id) -> KubernetesCredentialRef:
    ref = db.query(KubernetesCredentialRef).filter(KubernetesCredentialRef.cluster_id == cluster_id).first()
    if ref is None:  # pragma: no cover - always created with the cluster
        raise HTTPException(404, {"code": "KUBERNETES_NOT_FOUND"})
    return ref


def _audit(
    db: Session,
    request: Request,
    actor,
    access,
    permission: str,
    action: str,
    resource_type: str,
    resource_id,
    changes: dict,
    allowed: set[str],
):
    return AuditService(sessionmaker(bind=db.get_bind())).project_action(
        db,
        request=request,
        actor=actor,
        access=access,
        permission=permission,
        intent=AuditIntent(
            project_id=access.project.id,
            action=action,
            resource_type=resource_type,
            resource_id=str(resource_id),
            changes=changes,
        ),
        allowed_changes=allowed,
    )


def _echo_request_id(request: Request, response: Response) -> None:
    request_id = request.headers.get("X-Request-ID")
    if request_id:
        response.headers["X-Request-ID"] = request_id


@router.post("/clusters", status_code=201, response_model=ClusterResponse)
def create_cluster(
    data: ClusterCreate,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    access = _require(db, data.project_id, current_user, "resource.create")
    try:
        name, normalized_url, secret_ref = cluster_service.validate_registration(
            name=data.name,
            api_server_url=data.api_server_url,
            secret_ref=data.secret_ref,
            insecure_tls=data.insecure_tls,
            settings=settings,
        )
    except KubernetesClientError as error:
        raise HTTPException(422, {"code": error.code, "message": error.message})
    existing = (
        db.query(KubernetesCluster)
        .filter(
            KubernetesCluster.project_id == data.project_id,
            KubernetesCluster.name == name,
            KubernetesCluster.archived_at.is_(None),
        )
        .first()
    )
    if existing is not None:
        raise HTTPException(409, {"code": "CLUSTER_NAME_EXISTS"})
    changes = {
        "name": name,
        "display_name": data.display_name,
        "api_server_url": normalized_url,
        "insecure_tls": data.insecure_tls,
        "provider": data.provider,
        "default_namespace": data.default_namespace,
        "secret_ref": secret_ref,
    }
    intent = AuditIntent(
        project_id=data.project_id,
        action="kubernetes.cluster.create",
        resource_type="kubernetes_cluster",
        changes=changes,
    )
    with AuditService(sessionmaker(bind=db.get_bind())).project_action(
        db,
        request=request,
        actor=current_user,
        access=access,
        permission="resource.create",
        intent=intent,
        allowed_changes=AUDIT_ALLOWED_CLUSTER,
    ):
        cluster = KubernetesCluster(
            project_id=data.project_id,
            name=name,
            display_name=data.display_name or name,
            api_server_url=normalized_url,
            insecure_tls=data.insecure_tls,
            provider=data.provider,
            default_namespace=data.default_namespace,
            status="pending",
            created_by=current_user.id,
        )
        db.add(cluster)
        db.flush()
        db.add(
            KubernetesCredentialRef(
                cluster_id=cluster.id,
                secret_ref=secret_ref,
                allowed_use="connectivity",
            )
        )
    _echo_request_id(request, response)
    return _cluster_response(cluster, db)


def _cluster_response(cluster: KubernetesCluster, db: Session) -> dict:
    ref = db.query(KubernetesCredentialRef).filter(KubernetesCredentialRef.cluster_id == cluster.id).first()
    data = ClusterResponse.model_validate(cluster).model_dump(mode="json")
    data["stale"] = cluster_service.is_stale(cluster, settings)
    data["secret_ref"] = ref.secret_ref if ref else None
    return data


@router.get("/clusters", response_model=None)
def list_clusters(
    request: Request,
    response: Response,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    project_ids = [
        row.id
        for row in ProjectAccessService().accessible_project_query(db, current_user.id).all()
    ]
    query = (
        db.query(KubernetesCluster)
        .filter(KubernetesCluster.project_id.in_(project_ids or [uuid.uuid4()]), KubernetesCluster.archived_at.is_(None))
        .order_by(KubernetesCluster.created_at.desc())
    )
    total = query.count()
    items = query.offset(offset).limit(limit).all()
    _echo_request_id(request, response)
    return {"items": [_cluster_response(cluster, db) for cluster in items], "total": total, "offset": offset, "limit": limit}


@router.get("/clusters/{cluster_id}", response_model=None)
def get_cluster(
    cluster_id: uuid.UUID,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    cluster = _load_cluster(db, cluster_id, current_user, "project.read")
    _echo_request_id(request, response)
    return _cluster_response(cluster, db)


@router.patch("/clusters/{cluster_id}", response_model=None)
def update_cluster(
    cluster_id: uuid.UUID,
    data: ClusterUpdate,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    cluster = _load_cluster(db, cluster_id, current_user, "resource.update")
    ref = _credential(db, cluster.id)
    access = ProjectAccessService().require(db, cluster.project_id, current_user.id, "resource.update")
    changes = {k: v for k, v in data.model_dump(exclude_none=True).items()}
    if "api_server_url" in changes or "insecure_tls" in changes:
        try:
            cluster_service.validate_registration(
                name=cluster.name,
                api_server_url=changes.get("api_server_url", cluster.api_server_url),
                secret_ref=changes.get("secret_ref", ref.secret_ref),
                insecure_tls=bool(changes.get("insecure_tls", cluster.insecure_tls)),
                settings=settings,
            )
        except KubernetesClientError as error:
            raise HTTPException(422, {"code": error.code, "message": error.message})
    if "secret_ref" in changes and "api_server_url" not in changes:
        from app.services.kubernetes_client import parse_secret_ref

        try:
            parse_secret_ref(changes["secret_ref"])
        except KubernetesClientError as error:
            raise HTTPException(422, {"code": error.code, "message": error.message})
    with _audit(db, request, current_user, access, "resource.update", "kubernetes.cluster.update", "kubernetes_cluster", cluster.id, changes, AUDIT_ALLOWED_CLUSTER):
        for key, value in changes.items():
            if key == "secret_ref":
                ref.secret_ref = value
            elif key == "api_server_url":
                cluster.api_server_url = value
            elif key == "insecure_tls":
                cluster.insecure_tls = value
            elif key == "default_namespace":
                cluster.default_namespace = value
            elif key == "display_name":
                cluster.display_name = value
        cluster.updated_at = datetime.now(timezone.utc)
    _echo_request_id(request, response)
    return _cluster_response(cluster, db)


@router.delete("/clusters/{cluster_id}", status_code=204)
def delete_cluster(
    cluster_id: uuid.UUID,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    cluster = _load_cluster(db, cluster_id, current_user, "resource.delete")
    access = ProjectAccessService().require(db, cluster.project_id, current_user.id, "resource.delete")
    with _audit(db, request, current_user, access, "resource.delete", "kubernetes.cluster.delete", "kubernetes_cluster", cluster.id, {}, set()):
        cluster.status = "disabled"
        cluster.archived_at = datetime.now(timezone.utc)
        db.commit()
    response.status_code = 204
    _echo_request_id(request, response)
    return Response(status_code=204)


@router.post("/clusters/{cluster_id}/connectivity-check", response_model=ConnectivityCheckResponse)
def connectivity_check(
    cluster_id: uuid.UUID,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    cluster = _load_cluster(db, cluster_id, current_user, "resource.update")
    access = ProjectAccessService().require(db, cluster.project_id, current_user.id, "resource.update")
    ref = _credential(db, cluster.id)
    try:
        result = cluster_service.run_connectivity_check(cluster, ref, settings)
    except KubernetesClientError as error:
        # Environment-level failure (e.g. missing dependency): report 503, do not
        # record it as a cluster connectivity result.
        raise HTTPException(503, {"code": error.code, "message": error.message})
    db.commit()
    with _audit(
        db,
        request,
        current_user,
        access,
        "resource.update",
        "kubernetes.cluster.connectivity_check",
        "kubernetes_cluster",
        cluster.id,
        {
            "action": "kubernetes.cluster.connectivity_check",
            "result": result["check_status"],
            "error_code": result.get("error_code"),
            "latency_ms": result["latency_ms"],
        },
        {"action", "result", "error_code", "latency_ms"},
    ):
        pass
    _echo_request_id(request, response)
    return ConnectivityCheckResponse(
        check_status=result["check_status"],
        error_code=result.get("error_code"),
        latency_ms=result["latency_ms"],
        checked_at=result.get("checked_at"),
        kubernetes_version=result.get("kubernetes_version"),
    )


@router.get("/clusters/{cluster_id}/nodes")
def list_nodes(
    cluster_id: uuid.UUID,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    cluster = _load_cluster(db, cluster_id, current_user, "project.read")
    ref = _credential(db, cluster.id)
    try:
        client = cluster_service.get_client_for_cluster(cluster, ref, settings)
        nodes = client.list_nodes()
    except KubernetesClientError as error:
        status = 503 if error.code == "KUBERNETES_CLIENT_UNAVAILABLE" else 502
        raise HTTPException(status, {"code": error.code, "message": error.message})
    _echo_request_id(request, response)
    return {"items": nodes[:100], "total": min(len(nodes), 100)}


@router.get("/clusters/{cluster_id}/namespaces")
def list_cluster_namespaces(
    cluster_id: uuid.UUID,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    cluster = _load_cluster(db, cluster_id, current_user, "project.read")
    ref = _credential(db, cluster.id)
    try:
        client = cluster_service.get_client_for_cluster(cluster, ref, settings)
        names = client.list_namespaces()
    except KubernetesClientError as error:
        status = 503 if error.code == "KUBERNETES_CLIENT_UNAVAILABLE" else 502
        raise HTTPException(status, {"code": error.code, "message": error.message})
    _echo_request_id(request, response)
    return {"items": names, "total": len(names)}


@router.put("/clusters/{cluster_id}/namespaces/{name}", response_model=NamespaceResponse)
def ensure_namespace(
    cluster_id: uuid.UUID,
    name: str,
    data: NamespaceEnsureRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    cluster = _load_cluster(db, cluster_id, current_user, "resource.create")
    access = ProjectAccessService().require(db, cluster.project_id, current_user.id, "resource.create")
    ref = _credential(db, cluster.id)
    try:
        clean_name, clean_quota, _result = cluster_service.ensure_namespace(
            cluster, ref, settings, name=name, quota_json=data.quota_json
        )
    except KubernetesClientError as error:
        raise HTTPException(422, {"code": error.code, "message": error.message})
    row = cluster_service.upsert_namespace_row(db, cluster, clean_name, clean_quota)
    db.commit()
    with _audit(
        db,
        request,
        current_user,
        access,
        "resource.create",
        "kubernetes.namespace.apply",
        "kubernetes_namespace",
        cluster.id,
        {"action": "kubernetes.namespace.apply", "namespace": clean_name, "quota": clean_quota or {}},
        {"action", "namespace", "quota"},
    ):
        pass
    _echo_request_id(request, response)
    return NamespaceResponse.model_validate(row)


def _load_resource_group(db: Session, group_id: uuid.UUID, user, permission: str) -> KubernetesResourceGroup:
    group = db.query(KubernetesResourceGroup).filter(KubernetesResourceGroup.id == group_id).first()
    if group is None:
        raise HTTPException(404, {"code": "KUBERNETES_NOT_FOUND"})
    try:
        ProjectAccessService().require(db, group.project_id, user.id, permission)
    except ProjectAccessError as error:
        _http_access(error)
    return group


@router.post("/resource-groups", status_code=201, response_model=ResourceGroupResponse)
def create_resource_group(
    data: ResourceGroupCreate,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    cluster = _load_cluster(db, data.cluster_id, current_user, "resource.create")
    access = ProjectAccessService().require(db, cluster.project_id, current_user.id, "resource.create")
    if not data.name or len(data.name) > 64:
        raise HTTPException(422, {"code": "KUBERNETES_QUOTA_INVALID", "message": "resource group name is invalid"})
    policy = dict(data.scheduling_policy_json or {})
    if "policy_type" not in policy:
        policy["policy_type"] = "default"
    if policy["policy_type"] != "default":
        raise HTTPException(422, {"code": "KUBERNETES_QUOTA_INVALID", "message": "only policy_type=default is supported in week 13"})
    quota = cluster_service.validate_quota_json(data.quota_json or {}) or {}
    duplicate = (
        db.query(KubernetesResourceGroup)
        .filter(
            KubernetesResourceGroup.cluster_id == cluster.id,
            KubernetesResourceGroup.project_id == cluster.project_id,
            KubernetesResourceGroup.name == data.name,
        )
        .first()
    )
    if duplicate is not None:
        raise HTTPException(409, {"code": "RESOURCE_GROUP_EXISTS"})
    with _audit(
        db,
        request,
        current_user,
        access,
        "resource.create",
        "kubernetes.resource_group.create",
        "kubernetes_resource_group",
        cluster.id,
        {"action": "kubernetes.resource_group.create", "name": data.name},
        {"action", "name"},
    ):
        group = KubernetesResourceGroup(
            cluster_id=cluster.id,
            project_id=cluster.project_id,
            name=data.name,
            description=data.description,
            scheduling_policy_json=policy,
            quota_json=quota,
            created_by=current_user.id,
        )
        db.add(group)
        db.commit()
        db.refresh(group)
    _echo_request_id(request, response)
    return ResourceGroupResponse.model_validate(group)


@router.get("/resource-groups")
def list_resource_groups(
    request: Request,
    response: Response,
    cluster_id: uuid.UUID | None = Query(default=None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    project_ids = [
        row.id
        for row in ProjectAccessService().accessible_project_query(db, current_user.id).all()
    ]
    query = db.query(KubernetesResourceGroup).filter(KubernetesResourceGroup.project_id.in_(project_ids or [uuid.uuid4()]))
    if cluster_id is not None:
        query = query.filter(KubernetesResourceGroup.cluster_id == cluster_id)
    items = query.order_by(KubernetesResourceGroup.created_at.desc()).all()
    _echo_request_id(request, response)
    return {"items": [ResourceGroupResponse.model_validate(group).model_dump(mode="json") for group in items], "total": len(items)}


@router.patch("/resource-groups/{group_id}", response_model=ResourceGroupResponse)
def update_resource_group(
    group_id: uuid.UUID,
    data: ResourceGroupUpdate,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    group = _load_resource_group(db, group_id, current_user, "resource.update")
    changes = {k: v for k, v in data.model_dump(exclude_none=True).items()}
    if "quota_json" in changes:
        changes["quota_json"] = cluster_service.validate_quota_json(changes["quota_json"]) or {}
    with _audit(
        db,
        request,
        current_user,
        ProjectAccessService().require(db, group.project_id, current_user.id, "resource.update"),
        "resource.update",
        "kubernetes.resource_group.update",
        "kubernetes_resource_group",
        group.id,
        {"action": "kubernetes.resource_group.update", **{k: v for k, v in changes.items() if k != "quota_json"}},
        {"action", "description", "status"},
    ):
        for key, value in changes.items():
            setattr(group, key, value)
        db.commit()
        db.refresh(group)
    _echo_request_id(request, response)
    return ResourceGroupResponse.model_validate(group)
