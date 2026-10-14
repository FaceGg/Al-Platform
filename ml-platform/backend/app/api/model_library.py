"""Model library API - CRUD for trained models."""
import uuid
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.model_library import ModelLibrary
from app.models.model_registry import (
    DeploymentRevision, DeploymentTarget, InferenceDeployment,
    ModelVersion, RegisteredModel,
)
from app.models.user import User
from app.api.auth import get_current_user
from app.api.project_security import audit_service, resolve_project_access
from app.services.audit import AuditIntent
from app.services.project_access import ProjectAccessService

router = APIRouter(prefix="/api/model-library", tags=["model_library"])
PROJECT_WRITE_ACTIONS = {
    "POST /api/model-library": "model_library.create",
    "PUT /api/model-library/{model_id}": "model_library.update",
    "DELETE /api/model-library/{model_id}": "model_library.delete",
    "POST /api/model-library/batch-delete": "model_library.batch_delete",
}


def top_models_by_score(rows, limit: int = 10):
    """按 AutoML best_score 降序取前 N。

    metrics 是 JSON 列，PostgreSQL 无法直接排序（sqlite 按文本排语义也不
    可靠），统一取回后在 Python 侧排序，保证双方言行为一致。
    """
    def score(row):
        metrics = row.metrics if isinstance(row.metrics, dict) else {}
        try:
            return float(metrics.get("best_score"))
        except (TypeError, ValueError):
            return float("-inf")

    return sorted(rows, key=score, reverse=True)[:limit]


@router.get("")
def list_models(
    status: str = Query(None),
    framework: str = Query(None),
    category: str = Query(None),
    project_id: str = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    q = db.query(ModelLibrary)
    if project_id:
        q = q.filter(ModelLibrary.project_id == uuid.UUID(project_id))
    if current_user.role != "admin":
        accessible = [
            project.id for project in ProjectAccessService()
            .accessible_project_query(db, current_user.id).all()
        ]
        q = q.filter(
            (ModelLibrary.owner_id == current_user.id)
            | (ModelLibrary.project_id.in_(accessible))
            | (ModelLibrary.is_public.is_(True))
        )
    if status:
        q = q.filter(ModelLibrary.status == status)
    if framework:
        q = q.filter(ModelLibrary.framework == framework)
    models = q.order_by(ModelLibrary.created_at.desc()).all()
    return {
        "items": [
            {
                "id": str(m.id),
                "name": m.name,
                "version": m.version,
                "status": m.status,
                "framework": m.framework,
                "backbone": m.backbone,
                "description": m.description,
                "metrics": m.metrics or {},
                "params": m.params or {},
                "model_path": m.model_path,
                "format": m.format,
                "file_size": m.file_size,
                "progress": m.progress,
                "tags": m.tags or [],
                "is_public": m.is_public,
                "created_at": m.created_at.isoformat() if m.created_at else None,
            }
            for m in models
        ],
        "total": len(models),
    }


@router.get("/{model_id}")
def get_model(model_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    m = db.query(ModelLibrary).filter(ModelLibrary.id == uuid.UUID(model_id)).first()
    if not m:
        raise HTTPException(404, "Model not found")
    if current_user.role != "admin":
        if m.project_id is not None:
            if resolve_project_access(db, m.project_id, current_user.id) is None:
                raise HTTPException(404, "Model not found")
        elif m.owner_id != current_user.id and not m.is_public:
            raise HTTPException(404, "Model not found")
    return {
        "id": str(m.id),
        "name": m.name,
        "algorithm_id": str(m.algorithm_id) if m.algorithm_id else None,
        "project_id": str(m.project_id) if m.project_id else None,
        "version": m.version,
        "status": m.status,
        "framework": m.framework,
        "backbone": m.backbone,
        "description": m.description,
        "metrics": m.metrics or {},
        "params": m.params or {},
        "model_path": m.model_path,
        "format": m.format,
        "file_size": m.file_size,
        "progress": m.progress,
        "tags": m.tags or [],
        "is_public": m.is_public,
        "created_at": m.created_at.isoformat() if m.created_at else None,
        "updated_at": m.updated_at.isoformat() if m.updated_at else None,
    }


@router.post("")
def create_model(
    data: dict,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    project_id = uuid.UUID(data["project_id"]) if data.get("project_id") else None
    model = ModelLibrary(
        id=uuid.uuid4(),
        name=data["name"],
        algorithm_id=uuid.UUID(data["algorithm_id"]) if data.get("algorithm_id") else None,
        project_id=project_id,
        owner_id=current_user.id,
        version=data.get("version", "v1"),
        framework=data.get("framework", ""),
        backbone=data.get("backbone", ""),
        description=data.get("description", ""),
        params=data.get("params", {}),
        tags=data.get("tags", []),
    )
    if project_id is None:
        db.add(model)
        db.commit()
    else:
        access = resolve_project_access(db, project_id, current_user.id)
        with audit_service(db).project_action(
            db, request=request, actor=current_user, access=access,
            permission="resource.create",
            intent=AuditIntent(
                project_id=project_id, action="model_library.create",
                resource_type="model_library", resource_id=str(model.id),
                changes={"name": model.name, "version": model.version},
            ),
            allowed_changes={"name", "version"},
        ):
            db.add(model)
    db.refresh(model)
    return {"id": str(model.id), "name": model.name}


@router.put("/{model_id}")
def update_model(
    model_id: str,
    data: dict,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    m = db.query(ModelLibrary).filter(ModelLibrary.id == uuid.UUID(model_id)).first()
    if not m:
        raise HTTPException(404)
    keys = {"name", "status", "description", "version", "metrics", "progress", "is_public", "tags"}
    if m.project_id is None:
        if m.owner_id != current_user.id:
            raise HTTPException(404)
        for key in keys:
            if key in data:
                setattr(m, key, data[key])
        db.commit()
    else:
        access = resolve_project_access(db, m.project_id, current_user.id)
        with audit_service(db).project_action(
            db, request=request, actor=current_user, access=access,
            permission="resource.update",
            intent=AuditIntent(
                project_id=m.project_id, action="model_library.update",
                resource_type="model_library", resource_id=str(m.id), changes=data,
            ),
            allowed_changes=keys,
        ):
            for key in keys:
                if key in data:
                    setattr(m, key, data[key])
    return {"status": "ok"}


def _cascade_delete_with_guard(db, model):
    """删除模型库条目，连带清理注册表对它的引用。

    model_versions.source_model_library_id 外键无 ondelete，PostgreSQL
    直接删已注册条目会在提交时报 IntegrityError（本地 sqlite 不强制外键，
    问题只在生产暴露）。版本被推理部署引用时必须先删部署（deployment_targets
    → model_versions 外键同理）——与注册表删除端点的 MODEL_DEPLOYMENT_EXISTS
    护栏同语义；删除版本后变空的注册模型一并清理。
    """
    versions = (
        db.query(ModelVersion)
        .filter(ModelVersion.source_model_library_id == model.id)
        .all()
    )
    if versions:
        version_ids = [v.id for v in versions]
        # 与注册表删除端点同口径：只拦"活"引用——部署主版本，或
        # stable/candidate/draft 修订上的发布目标。superseded/failed 修订的
        # 历史目标是自动换模残留，随模型删除一并清理。
        deployment_exists = (
            db.query(InferenceDeployment)
            .filter(
                InferenceDeployment.model_version_id.in_(version_ids)
                | InferenceDeployment.id.in_(
                    db.query(DeploymentRevision.deployment_id)
                    .join(
                        DeploymentTarget,
                        DeploymentTarget.revision_id == DeploymentRevision.id,
                    )
                    .filter(
                        DeploymentTarget.model_version_id.in_(version_ids),
                        DeploymentRevision.status.in_(("stable", "candidate", "draft")),
                    )
                )
            )
            .first()
        )
        if deployment_exists is not None:
            raise HTTPException(409, {
                "code": "MODEL_DEPLOYMENT_EXISTS",
                "message": deployment_exists.name,
            })
        stale_target_ids = [
            row.id for row in (
                db.query(DeploymentTarget.id)
                .join(
                    DeploymentRevision,
                    DeploymentTarget.revision_id == DeploymentRevision.id,
                )
                .filter(
                    DeploymentTarget.model_version_id.in_(version_ids),
                    DeploymentRevision.status.in_(("superseded", "failed")),
                )
                .all()
            )
        ]
        for target_id in stale_target_ids:
            stale_target = db.get(DeploymentTarget, target_id)
            if stale_target is not None:
                db.delete(stale_target)
        registered_ids = {version.registered_model_id for version in versions}
        for version in versions:
            db.delete(version)
        # SessionLocal 关闭了 autoflush：先刷出版本删除，剩余版本检查才准确
        db.flush()
        for registered_id in registered_ids:
            # 仍有其他版本（onnx_artifact 来源）的注册模型保留
            remaining = (
                db.query(ModelVersion.id)
                .filter(ModelVersion.registered_model_id == registered_id)
                .first()
            )
            if remaining is None:
                registered = db.get(RegisteredModel, registered_id)
                if registered is not None:
                    db.delete(registered)
    db.delete(model)


@router.delete("/{model_id}")
def delete_model(
    model_id: str,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    m = db.query(ModelLibrary).filter(ModelLibrary.id == uuid.UUID(model_id)).first()
    if not m:
        raise HTTPException(404)
    if m.project_id is None:
        if m.owner_id != current_user.id:
            raise HTTPException(404)
        _cascade_delete_with_guard(db, m)
        db.commit()
    else:
        access = resolve_project_access(db, m.project_id, current_user.id)
        with audit_service(db).project_action(
            db, request=request, actor=current_user, access=access,
            permission="resource.delete",
            intent=AuditIntent(
                project_id=m.project_id, action="model_library.delete",
                resource_type="model_library", resource_id=str(m.id),
            ),
            allowed_changes=set(),
        ):
            _cascade_delete_with_guard(db, m)
    return {"status": "deleted"}


@router.get("/stats/summary")
def model_stats(db: Session = Depends(get_db)):
    total = db.query(ModelLibrary).count()
    completed = db.query(ModelLibrary).filter(ModelLibrary.status == "completed").count()
    training = db.query(ModelLibrary).filter(ModelLibrary.status == "training").count()
    published = db.query(ModelLibrary).filter(ModelLibrary.status == "published").count()

    # Top models by best_score（JSON 列排序双方言不兼容，Python 侧排序）
    top = top_models_by_score(
        db.query(ModelLibrary).filter(ModelLibrary.metrics.isnot(None)).all()
    )

    return {
        "total_models": total,
        "completed": completed,
        "training": training,
        "published": published,
        "top_models": [
            {"id": str(m.id), "name": m.name, "metrics": m.metrics or {}}
            for m in top
        ],
    }


from pydantic import BaseModel
from typing import List

class BatchDeleteRequest(BaseModel):
    ids: List[str]

@router.post("/batch-delete", status_code=200)
def batch_delete_models(
    data: BatchDeleteRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    deleted = 0
    skipped = []
    for mid_str in data.ids:
        try:
            uid = uuid.UUID(mid_str)
        except ValueError:
            continue
        model = db.query(ModelLibrary).filter(ModelLibrary.id == uid).first()
        if not model:
            continue
        try:
            if model.project_id is None:
                if model.owner_id != current_user.id:
                    continue
                _cascade_delete_with_guard(db, model)
            else:
                access = resolve_project_access(db, model.project_id, current_user.id)
                with audit_service(db).project_action(
                    db, request=request, actor=current_user, access=access,
                    permission="resource.delete",
                    intent=AuditIntent(
                        project_id=model.project_id, action="model_library.batch_delete",
                        resource_type="model_library", resource_id=str(model.id),
                    ),
                    allowed_changes=set(),
                ):
                    _cascade_delete_with_guard(db, model)
            db.commit()
            deleted += 1
        except HTTPException as error:
            # 逐条提交：部署冲突的条目回滚跳过，不影响本批已删条目
            db.rollback()
            detail = error.detail if isinstance(error.detail, dict) else {}
            if detail.get("code") == "MODEL_DEPLOYMENT_EXISTS":
                skipped.append(mid_str)
            else:
                raise
    return {"deleted": deleted, "skipped": skipped}
