"""Week 16 cluster-governance API: routing policies, storage bindings, quota
policies, reservation read-only list, usage snapshots and routing preview."""


import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session, sessionmaker

from app.api.auth import get_current_user
from app.config import settings
from app.database import get_db
from app.models.cloud_resources import KubernetesCluster, KubernetesCredentialRef
from app.models.resource_governance import (
    ClusterRoutingPolicy,
    ResourceQuotaPolicy,
    ResourceReservation,
    ResourceUsageSnapshot,
    StorageBinding,
)
from app.models.user import User
from app.services import resource_governance
from app.services.audit import AuditIntent, AuditService
from app.services.cluster_scheduler import redact_reservation, route, validate_quota_json
from app.services.kubernetes_client import KubernetesClientError
from app.services.kubernetes_executor import KubeJobError
from app.services.project_access import ProjectAccessError, ProjectAccessService
from app.services.storage_mounts import validate_binding

router = APIRouter(prefix="/api/cluster-governance", tags=["cluster-governance"])


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
            resource_type="cluster_governance",
            resource_id=str(resource_id),
            changes=changes,
        ),
        allowed_changes=allowed,
    )


def _require_project(db: Session, project_id, user, permission: str):
    try:
        return ProjectAccessService().require(db, project_id, user.id, permission)
    except ProjectAccessError as error:
        raise HTTPException(404 if error.hidden else 403, {"code": error.code, "message": str(error)})


def _http_kube(error: KubeJobError):
    raise HTTPException(error.status, {"code": error.code, "message": error.message})


# ---- routing policies ----

class RoutingPolicyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: uuid.UUID
    priority: int = Field(ge=1, le=100)
    policy_json: dict = Field(default_factory=dict)


@router.get("/routing-policies")
def list_routing_policies(
    request: Request,
    response: Response,
    project_id: uuid.UUID = Query(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _require_project(db, project_id, current_user, "project.read")
    _echo(request, response)
    rows = (
        db.query(ClusterRoutingPolicy)
        .filter(ClusterRoutingPolicy.project_id == project_id)
        .order_by(ClusterRoutingPolicy.priority)
        .all()
    )
    return {
        "items": [
            {
                "id": str(row.id),
                "project_id": str(row.project_id),
                "priority": row.priority,
                "policy_json": row.policy_json,
                "revision": row.revision,
            }
            for row in rows
        ],
        "total": len(rows),
    }


@router.post("/routing-policies", status_code=201)
def create_routing_policy(
    data: RoutingPolicyRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _require_project(db, data.project_id, current_user, "resource.create")
    exists = (
        db.query(ClusterRoutingPolicy.id)
        .filter(ClusterRoutingPolicy.project_id == data.project_id, ClusterRoutingPolicy.priority == data.priority)
        .first()
    )
    if exists is not None:
        raise HTTPException(409, {"code": "ROUTING_POLICY_PRIORITY_EXISTS"})
    policy = ClusterRoutingPolicy(
        project_id=data.project_id,
        priority=data.priority,
        policy_json=data.policy_json,
        revision=1,
    )
    db.add(policy)
    db.commit()
    db.refresh(policy)
    with _audit(db, request, current_user, data.project_id, "resource.create", "governance.routing.create", policy.id, {"priority": policy.priority}, set()):
        pass
    _echo(request, response)
    return {"id": str(policy.id), "priority": policy.priority, "policy_json": policy.policy_json, "revision": policy.revision}


@router.delete("/routing-policies/{policy_id}")
def delete_routing_policy(
    policy_id: uuid.UUID,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    policy = db.query(ClusterRoutingPolicy).filter(ClusterRoutingPolicy.id == policy_id).first()
    if policy is None or policy.project_id is None:
        raise HTTPException(404, {"code": "ROUTING_POLICY_NOT_FOUND"})
    _require_project(db, policy.project_id, current_user, "resource.delete")
    db.delete(policy)
    db.commit()
    with _audit(db, request, current_user, policy.project_id, "resource.delete", "governance.routing.delete", policy_id, {"priority": policy.priority}, set()):
        pass
    _echo(request, response)
    return {"status": "deleted"}


@router.get("/routing/preview")
def routing_preview(
    request: Request,
    response: Response,
    project_id: uuid.UUID = Query(...),
    cpu_cores: float = Query(default=1, ge=0.1),
    gpu_count: int = Query(default=0, ge=0),
    region: str | None = Query(default=None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _require_project(db, project_id, current_user, "project.read")
    try:
        decision = route(
            db,
            project_id,
            cpu_cores=cpu_cores,
            gpu_count=gpu_count,
            region=region,
            preview=True,
        )
    except KubeJobError as error:
        if error.code == "NO_ELIGIBLE_CLUSTER":
            _echo(request, response)
            return {"selected_cluster_id": None, "reason": "no_eligible_cluster", "candidates": []}
        raise
    _echo(request, response)
    return {
        "selected_cluster_id": str(decision.selected_cluster_id) if decision.selected_cluster_id else None,
        "reason": decision.reason,
        "policy_revision": decision.policy_revision,
        "candidates": decision.candidates,
    }


# ---- storage bindings ----

class StorageBindingRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: uuid.UUID
    cluster_id: uuid.UUID
    mode: str = Field(pattern="^(pvc|object_prefix)$")
    pvc_name: str | None = Field(default=None, max_length=255)
    object_prefix: str | None = Field(default=None, max_length=255)
    access: str = Field(default="read_only", pattern="^(read_only|read_write)$")


@router.get("/storage-bindings")
def list_storage_bindings(
    request: Request,
    response: Response,
    project_id: uuid.UUID = Query(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _require_project(db, project_id, current_user, "project.read")
    rows = (
        db.query(StorageBinding)
        .filter(StorageBinding.project_id == project_id)
        .order_by(StorageBinding.created_at.desc())
        .all()
    )
    _echo(request, response)
    return {
        "items": [
            {
                "id": str(row.id),
                "cluster_id": str(row.cluster_id),
                "mode": row.mode,
                "pvc_name": row.pvc_name,
                "object_prefix": row.object_prefix,
                "access": row.access,
                "status": row.status,
            }
            for row in rows
        ],
        "total": len(rows),
    }


@router.post("/storage-bindings", status_code=201)
def create_storage_binding(
    data: StorageBindingRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _require_project(db, data.project_id, current_user, "resource.create")
    cluster = db.query(KubernetesCluster).filter(KubernetesCluster.id == data.cluster_id).first()
    if cluster is None or cluster.project_id != data.project_id:
        raise HTTPException(404, {"code": "KUBERNETES_NOT_FOUND"})
    try:
        binding = validate_binding(
            project_id=data.project_id,
            mode=data.mode,
            pvc_name=data.pvc_name,
            object_prefix=data.object_prefix,
            access=data.access,
        )
    except KubeJobError as error:
        _http_kube(error)
    row = StorageBinding(
        project_id=data.project_id,
        cluster_id=data.cluster_id,
        mode=binding["mode"],
        pvc_name=binding.get("pvc_name"),
        object_prefix=binding.get("object_prefix"),
        access=binding["access"],
        status="active",
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    with _audit(db, request, current_user, data.project_id, "resource.create", "governance.binding.create", row.id, {"mode": row.mode, "access": row.access}, set()):
        pass
    _echo(request, response)
    return {"id": str(row.id), "mode": row.mode, "access": row.access, "status": row.status}


# ---- quota policies ----

class QuotaPolicyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scope: str = Field(pattern="^(project|resource_group)$")
    scope_id: uuid.UUID
    quota_json: dict


class QuotaPolicyUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    quota_json: dict


@router.get("/quota-policies")
def list_quota_policies(
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    rows = db.query(ResourceQuotaPolicy).order_by(ResourceQuotaPolicy.created_at.desc()).all()
    accessible = [
        row
        for row in rows
        if row.scope == "project"
        and ProjectAccessService().resolve(db, row.scope_id, current_user.id) is not None
    ]
    _echo(request, response)
    return {
        "items": [
            {
                "id": str(row.id),
                "scope": row.scope,
                "scope_id": str(row.scope_id),
                "quota_json": row.quota_json,
                "revision": row.revision,
            }
            for row in accessible
        ],
        "total": len(accessible),
    }


@router.post("/quota-policies", status_code=201)
def create_quota_policy(
    data: QuotaPolicyRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if data.scope == "project":
        _require_project(db, data.scope_id, current_user, "resource.create")
    try:
        cleaned = validate_quota_json(data.quota_json)
    except KubeJobError as error:
        _http_kube(error)
    exists = (
        db.query(ResourceQuotaPolicy.id)
        .filter(ResourceQuotaPolicy.scope == data.scope, ResourceQuotaPolicy.scope_id == data.scope_id)
        .first()
    )
    if exists is not None:
        raise HTTPException(409, {"code": "QUOTA_POLICY_EXISTS"})
    row = ResourceQuotaPolicy(scope=data.scope, scope_id=data.scope_id, quota_json=cleaned, revision=1)
    db.add(row)
    db.commit()
    db.refresh(row)
    with _audit(db, request, current_user, data.scope_id if data.scope == "project" else _project_of(db, row), "resource.create", "governance.quota.create", row.id, {"quota_json": cleaned}, set()):
        pass
    _echo(request, response)
    return {"id": str(row.id), "scope": row.scope, "quota_json": row.quota_json, "revision": row.revision}


def _project_of(db: Session, row: ResourceQuotaPolicy):
    from app.models.resource_group import KubernetesResourceGroup

    if row.scope == "resource_group":
        group = db.query(KubernetesResourceGroup).filter(KubernetesResourceGroup.id == row.scope_id).first()
        return group.project_id if group else _any_project(db)
    return _any_project(db)


def _any_project(db: Session):
    from app.models.project import Project

    return db.query(Project.id).order_by(Project.created_at).first()[0]


@router.patch("/quota-policies/{quota_id}")
def update_quota_policy(
    quota_id: uuid.UUID,
    data: QuotaPolicyUpdate,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    row = db.query(ResourceQuotaPolicy).filter(ResourceQuotaPolicy.id == quota_id).first()
    if row is None:
        raise HTTPException(404, {"code": "QUOTA_POLICY_NOT_FOUND"})
    project_id = row.scope_id if row.scope == "project" else _project_of(db, row)
    _require_project(db, project_id, current_user, "resource.update")
    try:
        cleaned = validate_quota_json(data.quota_json)
    except KubeJobError as error:
        _http_kube(error)
    row.quota_json = cleaned
    row.revision = (row.revision or 0) + 1
    db.commit()
    with _audit(db, request, current_user, project_id, "resource.update", "governance.quota.update", row.id, {"quota_json": cleaned, "revision": row.revision}, set()):
        pass
    _echo(request, response)
    return {"id": str(row.id), "quota_json": row.quota_json, "revision": row.revision}


# ---- reservations (read-only) ----

@router.get("/reservations")
def list_reservations(
    request: Request,
    response: Response,
    project_id: uuid.UUID = Query(...),
    state: str | None = Query(default=None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _require_project(db, project_id, current_user, "project.read")
    query = db.query(ResourceReservation).filter(ResourceReservation.project_id == project_id)
    if state:
        query = query.filter(ResourceReservation.state == state)
    rows = query.order_by(ResourceReservation.created_at.desc()).limit(200).all()
    _echo(request, response)
    return {"items": [redact_reservation(row) for row in rows], "total": len(rows)}


# ---- usage ----

@router.get("/usage")
def usage_snapshots(
    request: Request,
    response: Response,
    project_id: uuid.UUID = Query(...),
    cluster_id: uuid.UUID | None = Query(default=None),
    scope: str | None = Query(default=None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _require_project(db, project_id, current_user, "project.read")
    query = (
        db.query(ResourceUsageSnapshot)
        .join(KubernetesCluster, KubernetesCluster.id == ResourceUsageSnapshot.cluster_id)
        .filter(KubernetesCluster.project_id == project_id)
    )
    if cluster_id is not None:
        query = query.filter(ResourceUsageSnapshot.cluster_id == cluster_id)
    if scope:
        query = query.filter(ResourceUsageSnapshot.scope == scope)
    rows = query.order_by(ResourceUsageSnapshot.collected_at.desc()).limit(300).all()
    stale_flags = {
        str(row.id): resource_governance.usage_is_stale(db, row, settings)
        for row in db.query(KubernetesCluster).filter(KubernetesCluster.project_id == project_id).all()
    }
    _echo(request, response)
    return {
        "items": [
            {
                "id": str(row.id),
                "cluster_id": str(row.cluster_id),
                "scope": row.scope,
                "subject": row.subject,
                "metrics_json": row.metrics_json,
                "truncated": row.truncated,
                "collected_at": row.collected_at.isoformat() if row.collected_at else None,
            }
            for row in rows
        ],
        "stale_by_cluster": stale_flags,
        "total": len(rows),
    }


@router.post("/usage/collect")
def collect_usage_now(
    request: Request,
    response: Response,
    project_id: uuid.UUID = Query(...),
    cluster_id: uuid.UUID = Query(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _require_project(db, project_id, current_user, "project.read")
    cluster = db.query(KubernetesCluster).filter(KubernetesCluster.id == cluster_id).first()
    if cluster is None or cluster.project_id != project_id:
        raise HTTPException(404, {"code": "KUBERNETES_NOT_FOUND"})
    ref = db.query(KubernetesCredentialRef).filter(KubernetesCredentialRef.cluster_id == cluster.id).first()
    try:
        result = resource_governance.collect_usage(db, cluster, ref, settings)
    except KubernetesClientError as error:
        raise HTTPException(502, {"code": error.code, "message": error.message})
    if result["status"] == "stale":
        raise HTTPException(502, {"code": "GOVERNANCE_COLLECT_FAILED", "message": "cluster unreachable; snapshots marked stale"})
    _echo(request, response)
    return result
