"""Quality domain CRUD API: scenes / stations / spec-limits (B1-10).

技术方案 §2.2：
- 读走 project.read；写动词全走 quality.manage（owner/editor 有、
  operator/viewer 无），写动作经 AuditService.project_action 落审计。
- 校验：code 唯一性、field_roles 角色键合法性（契约层）、绑定部署时
  condition_column 一致性、规格 statistic 枚举（DB CHECK + 契约双层）。
- 限界（D6）：EdgeDevice 是 owner 级资源，工位绑定校验「设备属于当前用户」。
"""

import uuid
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.api.auth import get_current_user
from app.api.project_security import require_project_access
from app.database import get_db
from app.models.compute import EdgeDevice
from app.models.model_registry import InferenceDeployment
from app.models.quality_domain import QualityScene, QualitySpecLimit, QualityStation
from app.models.user import User
from app.schemas.quality_domain import (
    QualitySceneCreate,
    QualitySceneFieldRoles,
    QualitySceneUpdate,
    QualitySpecLimitCreate,
    QualitySpecLimitUpdate,
    QualityStationCreate,
    QualityStationUpdate,
)
from app.services.audit import AuditIntent, AuditService
from app.services.project_access import ProjectAccess

router = APIRouter(tags=["quality-domain"])


def _audit_service(db: Session) -> AuditService:
    return AuditService(sessionmaker(bind=db.get_bind()))


def _uuid_or_404(value, code: str) -> uuid.UUID:
    try:
        return value if isinstance(value, UUID) else uuid.UUID(str(value))
    except (TypeError, ValueError, AttributeError):
        raise HTTPException(404, {"code": code})


def _scene_out(item: QualityScene) -> dict:
    return {
        "id": str(item.id),
        "project_id": str(item.project_id),
        "code": item.code,
        "name": item.name,
        "description": item.description,
        "deployment_id": str(item.deployment_id) if item.deployment_id else None,
        "condition_column": item.condition_column,
        "field_roles": item.field_roles or {},
        "waveform_column": item.waveform_column,
        "created_by": str(item.created_by_id) if item.created_by_id else None,
        "created_at": item.created_at.isoformat() if item.created_at else None,
        "updated_at": item.updated_at.isoformat() if item.updated_at else None,
    }


def _station_out(item: QualityStation) -> dict:
    return {
        "id": str(item.id),
        "scene_id": str(item.scene_id),
        "code": item.code,
        "name": item.name,
        "description": item.description,
        "factory": item.factory,
        "workshop": item.workshop,
        "production_line": item.production_line,
        "edge_device_id": str(item.edge_device_id) if item.edge_device_id else None,
        "responsible_user_id": (
            str(item.responsible_user_id) if item.responsible_user_id else None
        ),
        "enabled": bool(item.enabled),
        "created_by": str(item.created_by_id) if item.created_by_id else None,
        "created_at": item.created_at.isoformat() if item.created_at else None,
        "updated_at": item.updated_at.isoformat() if item.updated_at else None,
    }


def _spec_out(item: QualitySpecLimit) -> dict:
    return {
        "id": str(item.id),
        "scene_id": str(item.scene_id),
        "field": item.field,
        "statistic": item.statistic,
        "usl": item.usl,
        "lsl": item.lsl,
        "target": item.target,
        "unit": item.unit,
        "created_at": item.created_at.isoformat() if item.created_at else None,
        "updated_at": item.updated_at.isoformat() if item.updated_at else None,
    }


def _get_scene(db: Session, project_id: UUID, scene_id, ) -> QualityScene:
    scene = db.query(QualityScene).filter(
        QualityScene.id == _uuid_or_404(scene_id, "QUALITY_SCENE_NOT_FOUND"),
        QualityScene.project_id == project_id,
    ).first()
    if scene is None:
        raise HTTPException(404, {"code": "QUALITY_SCENE_NOT_FOUND"})
    return scene


def _get_station(db: Session, project_id: UUID, station_id) -> QualityStation:
    station = db.query(QualityStation).join(
        QualityScene, QualityScene.id == QualityStation.scene_id,
    ).filter(
        QualityStation.id == _uuid_or_404(station_id, "QUALITY_STATION_NOT_FOUND"),
        QualityScene.project_id == project_id,
    ).first()
    if station is None:
        raise HTTPException(404, {"code": "QUALITY_STATION_NOT_FOUND"})
    return station


def _validate_deployment_binding(
    db: Session,
    project_id: UUID,
    deployment_id,
    condition_column: str | None,
) -> None:
    """绑定部署须同项目，且工况列与场景声明一致（方案 §2.1）。"""
    if deployment_id is None:
        return
    deployment = db.query(InferenceDeployment).filter(
        InferenceDeployment.id == _uuid_or_404(deployment_id, "QUALITY_SCENE_DEPLOYMENT_NOT_FOUND"),
    ).first()
    if deployment is None or deployment.project_id != project_id:
        raise HTTPException(404, {"code": "QUALITY_SCENE_DEPLOYMENT_NOT_FOUND"})
    if (
        deployment.condition_column
        and condition_column
        and deployment.condition_column != condition_column
    ):
        raise HTTPException(422, {"code": "QUALITY_SCENE_CONDITION_MISMATCH"})


def _validate_device_binding(
    db: Session,
    edge_device_id,
    current_user: User,
) -> None:
    """工位绑定校验「设备属于当前用户」（D6 限界；跨成员共享随 S1 收敛）。"""
    if edge_device_id is None:
        return
    device = db.query(EdgeDevice).filter(
        EdgeDevice.id == _uuid_or_404(edge_device_id, "QUALITY_STATION_DEVICE_NOT_FOUND"),
    ).first()
    if device is None:
        raise HTTPException(404, {"code": "QUALITY_STATION_DEVICE_NOT_FOUND"})
    if device.owner_id != current_user.id:
        raise HTTPException(422, {"code": "QUALITY_STATION_DEVICE_NOT_OWNED"})


# ---------------------------------------------------------------- scenes


@router.get("/api/projects/{project_id}/quality-scenes")
def list_scenes(
    project_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    require_project_access(db, project_id, current_user.id, "project.read")
    items = (
        db.query(QualityScene)
        .filter(QualityScene.project_id == project_id)
        .order_by(QualityScene.created_at.asc(), QualityScene.id.asc())
        .all()
    )
    return {"items": [_scene_out(item) for item in items], "total": len(items)}


@router.post("/api/projects/{project_id}/quality-scenes", status_code=201)
def create_scene(
    project_id: UUID,
    request: Request,
    data: QualitySceneCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    access: ProjectAccess = require_project_access(
        db, project_id, current_user.id, "quality.manage",
    )
    _validate_deployment_binding(db, project_id, data.deployment_id, data.condition_column)
    scene_id = uuid.uuid4()
    try:
        with _audit_service(db).project_action(
            db,
            request=request,
            actor=current_user,
            access=access,
            permission="quality.manage",
            intent=AuditIntent(
                project_id=project_id,
                action="quality.scene.create",
                resource_type="quality_scene",
                resource_id=str(scene_id),
                changes={"code": data.code, "name": data.name},
            ),
            allowed_changes={"code", "name", "description", "deployment_id",
                             "condition_column", "field_roles", "waveform_column"},
        ):
            scene = QualityScene(
                id=scene_id,
                project_id=project_id,
                code=data.code.strip(),
                name=data.name.strip(),
                description=data.description,
                deployment_id=_uuid_or_404(data.deployment_id, "QUALITY_SCENE_DEPLOYMENT_NOT_FOUND") if data.deployment_id else None,
                condition_column=data.condition_column,
                field_roles=dict(data.field_roles),
                waveform_column=data.waveform_column,
                created_by_id=current_user.id,
            )
            db.add(scene)
            db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, {"code": "QUALITY_SCENE_CODE_CONFLICT"}) from None
    db.refresh(scene)
    return _scene_out(scene)


@router.get("/api/projects/{project_id}/quality-scenes/{scene_id}")
def get_scene(
    project_id: UUID,
    scene_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    require_project_access(db, project_id, current_user.id, "project.read")
    return _scene_out(_get_scene(db, project_id, scene_id))


@router.put("/api/projects/{project_id}/quality-scenes/{scene_id}")
def update_scene(
    project_id: UUID,
    scene_id: str,
    request: Request,
    data: QualitySceneUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    access: ProjectAccess = require_project_access(
        db, project_id, current_user.id, "quality.manage",
    )
    scene = _get_scene(db, project_id, scene_id)
    target_deployment = data.deployment_id if data.deployment_id is not None else (
        str(scene.deployment_id) if scene.deployment_id else None
    )
    target_condition = data.condition_column if data.condition_column is not None else scene.condition_column
    _validate_deployment_binding(db, project_id, target_deployment, target_condition)
    with _audit_service(db).project_action(
        db,
        request=request,
        actor=current_user,
        access=access,
        permission="quality.manage",
        intent=AuditIntent(
            project_id=project_id,
            action="quality.scene.update",
            resource_type="quality_scene",
            resource_id=str(scene.id),
            changes=data.model_dump(exclude_none=True),
        ),
        allowed_changes={"name", "description", "deployment_id",
                         "condition_column", "waveform_column"},
    ):
        if data.name is not None:
            scene.name = data.name.strip()
        if data.description is not None:
            scene.description = data.description
        if data.deployment_id is not None:
            scene.deployment_id = _uuid_or_404(
                data.deployment_id, "QUALITY_SCENE_DEPLOYMENT_NOT_FOUND",
            )
        if data.condition_column is not None:
            scene.condition_column = data.condition_column
        if data.waveform_column is not None:
            scene.waveform_column = data.waveform_column
        db.flush()
    db.refresh(scene)
    return _scene_out(scene)


@router.put("/api/projects/{project_id}/quality-scenes/{scene_id}/field-roles")
def replace_field_roles(
    project_id: UUID,
    scene_id: str,
    request: Request,
    data: QualitySceneFieldRoles,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    access: ProjectAccess = require_project_access(
        db, project_id, current_user.id, "quality.manage",
    )
    scene = _get_scene(db, project_id, scene_id)
    with _audit_service(db).project_action(
        db,
        request=request,
        actor=current_user,
        access=access,
        permission="quality.manage",
        intent=AuditIntent(
            project_id=project_id,
            action="quality.scene.field_roles.replace",
            resource_type="quality_scene",
            resource_id=str(scene.id),
            changes={"field_roles": dict(data.field_roles)},
        ),
        allowed_changes={"field_roles"},
    ):
        scene.field_roles = dict(data.field_roles)
        db.flush()
    db.refresh(scene)
    return {"scene_id": str(scene.id), "field_roles": scene.field_roles or {}}


@router.delete("/api/projects/{project_id}/quality-scenes/{scene_id}", status_code=204)
def delete_scene(
    project_id: UUID,
    scene_id: str,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    access: ProjectAccess = require_project_access(
        db, project_id, current_user.id, "quality.manage",
    )
    scene = _get_scene(db, project_id, scene_id)
    with _audit_service(db).project_action(
        db,
        request=request,
        actor=current_user,
        access=access,
        permission="quality.manage",
        intent=AuditIntent(
            project_id=project_id,
            action="quality.scene.delete",
            resource_type="quality_scene",
            resource_id=str(scene.id),
            changes={"code": scene.code},
        ),
        allowed_changes={"code"},
    ):
        db.delete(scene)
        db.flush()
    return None


# -------------------------------------------------------------- stations


@router.get("/api/projects/{project_id}/quality-stations")
def list_stations(
    project_id: UUID,
    scene_id: str | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    require_project_access(db, project_id, current_user.id, "project.read")
    query = (
        db.query(QualityStation)
        .join(QualityScene, QualityScene.id == QualityStation.scene_id)
        .filter(QualityScene.project_id == project_id)
    )
    if scene_id is not None:
        query = query.filter(QualityStation.scene_id == _uuid_or_404(scene_id, "QUALITY_SCENE_NOT_FOUND"))
    items = query.order_by(QualityStation.created_at.asc(), QualityStation.code.asc()).all()
    return {"items": [_station_out(item) for item in items], "total": len(items)}


@router.post("/api/projects/{project_id}/quality-stations", status_code=201)
def create_station(
    project_id: UUID,
    request: Request,
    data: QualityStationCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    access: ProjectAccess = require_project_access(
        db, project_id, current_user.id, "quality.manage",
    )
    scene = _get_scene(db, project_id, data.scene_id)
    _validate_device_binding(db, data.edge_device_id, current_user)
    station_id = uuid.uuid4()
    try:
        with _audit_service(db).project_action(
            db,
            request=request,
            actor=current_user,
            access=access,
            permission="quality.manage",
            intent=AuditIntent(
                project_id=project_id,
                action="quality.station.create",
                resource_type="quality_station",
                resource_id=str(station_id),
                changes={"code": data.code, "name": data.name, "scene_id": data.scene_id},
            ),
            allowed_changes={"code", "name", "description", "scene_id", "factory",
                             "workshop", "production_line", "edge_device_id",
                             "responsible_user_id", "enabled"},
        ):
            station = QualityStation(
                id=station_id,
                scene_id=scene.id,
                code=data.code.strip(),
                name=data.name.strip(),
                description=data.description,
                factory=data.factory,
                workshop=data.workshop,
                production_line=data.production_line,
                edge_device_id=_uuid_or_404(data.edge_device_id, "QUALITY_STATION_DEVICE_NOT_FOUND") if data.edge_device_id else None,
                responsible_user_id=_uuid_or_404(data.responsible_user_id, "QUALITY_STATION_USER_NOT_FOUND") if data.responsible_user_id else None,
                enabled=data.enabled,
                created_by_id=current_user.id,
            )
            db.add(station)
            db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, {"code": "QUALITY_STATION_CODE_CONFLICT"}) from None
    db.refresh(station)
    return _station_out(station)


@router.get("/api/projects/{project_id}/quality-stations/{station_id}")
def get_station(
    project_id: UUID,
    station_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    require_project_access(db, project_id, current_user.id, "project.read")
    return _station_out(_get_station(db, project_id, station_id))


@router.put("/api/projects/{project_id}/quality-stations/{station_id}")
def update_station(
    project_id: UUID,
    station_id: str,
    request: Request,
    data: QualityStationUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    access: ProjectAccess = require_project_access(
        db, project_id, current_user.id, "quality.manage",
    )
    station = _get_station(db, project_id, station_id)
    if data.scene_id is not None and data.scene_id != str(station.scene_id):
        _get_scene(db, project_id, data.scene_id)
    if data.edge_device_id is not None and data.edge_device_id != (
        str(station.edge_device_id) if station.edge_device_id else None
    ):
        _validate_device_binding(db, data.edge_device_id, current_user)
    with _audit_service(db).project_action(
        db,
        request=request,
        actor=current_user,
        access=access,
        permission="quality.manage",
        intent=AuditIntent(
            project_id=project_id,
            action="quality.station.update",
            resource_type="quality_station",
            resource_id=str(station.id),
            changes=data.model_dump(exclude_none=True),
        ),
        allowed_changes={"name", "description", "scene_id", "factory",
                         "workshop", "production_line", "edge_device_id",
                         "responsible_user_id", "enabled"},
    ):
        if data.name is not None:
            station.name = data.name.strip()
        if data.description is not None:
            station.description = data.description
        if data.scene_id is not None:
            station.scene_id = _uuid_or_404(data.scene_id, "QUALITY_SCENE_NOT_FOUND")
        if data.factory is not None:
            station.factory = data.factory
        if data.workshop is not None:
            station.workshop = data.workshop
        if data.production_line is not None:
            station.production_line = data.production_line
        if data.edge_device_id is not None:
            station.edge_device_id = _uuid_or_404(
                data.edge_device_id, "QUALITY_STATION_DEVICE_NOT_FOUND",
            )
        if data.responsible_user_id is not None:
            station.responsible_user_id = _uuid_or_404(
                data.responsible_user_id, "QUALITY_STATION_USER_NOT_FOUND",
            )
        if data.enabled is not None:
            station.enabled = data.enabled
        db.flush()
    db.refresh(station)
    return _station_out(station)


@router.delete("/api/projects/{project_id}/quality-stations/{station_id}", status_code=204)
def delete_station(
    project_id: UUID,
    station_id: str,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    access: ProjectAccess = require_project_access(
        db, project_id, current_user.id, "quality.manage",
    )
    station = _get_station(db, project_id, station_id)
    with _audit_service(db).project_action(
        db,
        request=request,
        actor=current_user,
        access=access,
        permission="quality.manage",
        intent=AuditIntent(
            project_id=project_id,
            action="quality.station.delete",
            resource_type="quality_station",
            resource_id=str(station.id),
            changes={"code": station.code},
        ),
        allowed_changes={"code"},
    ):
        db.delete(station)
        db.flush()
    return None


# ------------------------------------------------------------ spec limits


@router.get("/api/projects/{project_id}/quality-scenes/{scene_id}/spec-limits")
def list_spec_limits(
    project_id: UUID,
    scene_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    require_project_access(db, project_id, current_user.id, "project.read")
    scene = _get_scene(db, project_id, scene_id)
    items = (
        db.query(QualitySpecLimit)
        .filter(QualitySpecLimit.scene_id == scene.id)
        .order_by(QualitySpecLimit.field.asc(), QualitySpecLimit.statistic.asc())
        .all()
    )
    return {"items": [_spec_out(item) for item in items], "total": len(items)}


@router.post(
    "/api/projects/{project_id}/quality-scenes/{scene_id}/spec-limits",
    status_code=201,
)
def create_spec_limit(
    project_id: UUID,
    scene_id: str,
    request: Request,
    data: QualitySpecLimitCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    access: ProjectAccess = require_project_access(
        db, project_id, current_user.id, "quality.manage",
    )
    scene = _get_scene(db, project_id, scene_id)
    spec_id = uuid.uuid4()
    try:
        with _audit_service(db).project_action(
            db,
            request=request,
            actor=current_user,
            access=access,
            permission="quality.manage",
            intent=AuditIntent(
                project_id=project_id,
                action="quality.spec_limit.create",
                resource_type="quality_spec_limit",
                resource_id=str(spec_id),
                changes={"field": data.field, "statistic": data.statistic},
            ),
            allowed_changes={"field", "statistic", "usl", "lsl", "target", "unit"},
        ):
            spec = QualitySpecLimit(
                id=spec_id,
                scene_id=scene.id,
                field=data.field.strip(),
                statistic=data.statistic,
                usl=data.usl,
                lsl=data.lsl,
                target=data.target,
                unit=data.unit,
                created_by_id=current_user.id,
            )
            db.add(spec)
            db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, {"code": "QUALITY_SPEC_LIMIT_CONFLICT"}) from None
    db.refresh(spec)
    return _spec_out(spec)


@router.put(
    "/api/projects/{project_id}/quality-scenes/{scene_id}/spec-limits/{spec_id}",
)
def update_spec_limit(
    project_id: UUID,
    scene_id: str,
    spec_id: str,
    request: Request,
    data: QualitySpecLimitUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    access: ProjectAccess = require_project_access(
        db, project_id, current_user.id, "quality.manage",
    )
    scene = _get_scene(db, project_id, scene_id)
    spec = db.query(QualitySpecLimit).filter(
        QualitySpecLimit.id == _uuid_or_404(spec_id, "QUALITY_SPEC_LIMIT_NOT_FOUND"),
        QualitySpecLimit.scene_id == scene.id,
    ).first()
    if spec is None:
        raise HTTPException(404, {"code": "QUALITY_SPEC_LIMIT_NOT_FOUND"})
    try:
        with _audit_service(db).project_action(
            db,
            request=request,
            actor=current_user,
            access=access,
            permission="quality.manage",
            intent=AuditIntent(
                project_id=project_id,
                action="quality.spec_limit.update",
                resource_type="quality_spec_limit",
                resource_id=str(spec.id),
                changes=data.model_dump(exclude_none=True),
            ),
            allowed_changes={"statistic", "usl", "lsl", "target", "unit"},
        ):
            if data.statistic is not None:
                spec.statistic = data.statistic
            if data.usl is not None:
                spec.usl = data.usl
            if data.lsl is not None:
                spec.lsl = data.lsl
            if data.target is not None:
                spec.target = data.target
            if data.unit is not None:
                spec.unit = data.unit
            db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, {"code": "QUALITY_SPEC_LIMIT_CONFLICT"}) from None
    db.refresh(spec)
    return _spec_out(spec)


@router.delete(
    "/api/projects/{project_id}/quality-scenes/{scene_id}/spec-limits/{spec_id}",
    status_code=204,
)
def delete_spec_limit(
    project_id: UUID,
    scene_id: str,
    spec_id: str,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    access: ProjectAccess = require_project_access(
        db, project_id, current_user.id, "quality.manage",
    )
    scene = _get_scene(db, project_id, scene_id)
    spec = db.query(QualitySpecLimit).filter(
        QualitySpecLimit.id == _uuid_or_404(spec_id, "QUALITY_SPEC_LIMIT_NOT_FOUND"),
        QualitySpecLimit.scene_id == scene.id,
    ).first()
    if spec is None:
        raise HTTPException(404, {"code": "QUALITY_SPEC_LIMIT_NOT_FOUND"})
    with _audit_service(db).project_action(
        db,
        request=request,
        actor=current_user,
        access=access,
        permission="quality.manage",
        intent=AuditIntent(
            project_id=project_id,
            action="quality.spec_limit.delete",
            resource_type="quality_spec_limit",
            resource_id=str(spec.id),
            changes={"field": spec.field, "statistic": spec.statistic},
        ),
        allowed_changes={"field", "statistic"},
    ):
        db.delete(spec)
        db.flush()
    return None
