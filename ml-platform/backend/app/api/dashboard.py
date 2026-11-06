"""Dashboard / Data Cockpit API - aggregated platform stats."""
import time

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, or_
from sqlalchemy.orm import Session
from app.api.auth import get_current_user
from app.database import get_db
from app.models.model_library import ModelLibrary
from app.models.model_registry import InferenceDeployment, ModelVersion, RegisteredModel
from app.models.api_model import PlatformAPI
from app.models.artifact import Artifact
from app.models.platform_models import Dataset
from app.models.training import TrainingJob
from app.models.project import Project
from app.models.user import User
from app.services.project_access import ProjectAccessService

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])

# 短 TTL 缓存：统计改为 SQL 聚合后仍避免每次轮询都打满聚合查询；
# 按用户分键保持权限口径，TTL 内允许看板数字短暂滞后。
_STATS_CACHE_TTL_SECONDS = 5.0
_stats_cache: dict[str, tuple[float, dict]] = {}


def _visible_dataset_filters() -> list:
    # Same semantics as the dataset management list: archived (deleted) and
    # internal normalized artifacts are not user-visible datasets. JSON 抽取
    # 下推到 SQL（SQLite JSON_EXTRACT / PG ->>），缺 source 键返回 NULL 视为可见。
    source = Artifact.metadata_["source"].as_string()
    return [
        Artifact.type == "dataset",
        Artifact.archived_at.is_(None),
        or_(source.is_(None), source != "normalized"),
    ]


def _access_scope(db: Session, user: User) -> tuple[bool, list]:
    """(是否平台管理员, 可访问项目)——统计与列表共用同一权限口径。"""
    access_service = ProjectAccessService()
    is_platform_admin = access_service.is_platform_admin(db, user.id)
    projects = (
        db.query(Project).all()
        if is_platform_admin
        else access_service.accessible_project_query(db, user.id).all()
    )
    return is_platform_admin, projects


@router.get("/stats")
def get_dashboard_stats(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get statistics limited to the signed-in user's permitted resources."""
    from collections import Counter

    from app.engine.registry import OperatorRegistry

    cache_key = f"user:{current_user.id}"
    now = time.monotonic()
    cached = _stats_cache.get(cache_key)
    if cached is not None and cached[0] > now:
        return cached[1]

    operators = OperatorRegistry.list_all()
    is_platform_admin, accessible_projects = _access_scope(db, current_user)
    accessible_project_ids = [project.id for project in accessible_projects]

    dataset_filters = _visible_dataset_filters()
    if not is_platform_admin:
        dataset_filters.append(Artifact.project_id.in_(accessible_project_ids))
    total_datasets = (
        db.query(func.count(Artifact.id)).filter(*dataset_filters).scalar() or 0
    )
    row_count_value = Artifact.metadata_["row_count"].as_integer()
    total_samples = int(
        db.query(func.coalesce(func.sum(row_count_value), 0))
        .filter(*dataset_filters)
        .scalar()
    )

    apis_query = db.query(PlatformAPI)
    training_jobs_query = db.query(TrainingJob)
    if not is_platform_admin:
        apis_query = apis_query.filter(or_(
            PlatformAPI.owner_id == current_user.id,
            PlatformAPI.is_public.is_(True),
        ))
        training_jobs_query = training_jobs_query.filter(
            TrainingJob.project_id.in_(accessible_project_ids),
        )

    total_algorithms = len(operators)
    total_apis = apis_query.count()
    total_projects = len(accessible_projects)
    total_users = db.query(User).count() if is_platform_admin else 1
    total_training_jobs = training_jobs_query.count()

    # API call stats
    api_calls = apis_query.with_entities(
        PlatformAPI.total_calls, PlatformAPI.success_calls
    ).all()
    total_api_calls = sum(c[0] or 0 for c in api_calls)
    total_success_calls = sum(c[1] or 0 for c in api_calls)

    # Model stats align with 模型库 (registered models scoped to accessible
    # projects): total = model versions; published = versions on running
    # deployments; completed = the rest; training = jobs in flight.
    active_training_statuses = ("pending", "queued", "running", "cancel_requested")
    model_training = training_jobs_query.filter(
        TrainingJob.status.in_(active_training_statuses),
    ).count()
    registry_query = db.query(ModelVersion)
    if not is_platform_admin:
        registry_query = registry_query.join(
            RegisteredModel, ModelVersion.registered_model_id == RegisteredModel.id,
        ).filter(RegisteredModel.project_id.in_(accessible_project_ids))
    total_models = registry_query.count()
    deployed_version_ids = {
        row[0] for row in db.query(InferenceDeployment.model_version_id)
        .filter(InferenceDeployment.observed_state == "running").all()
    }
    model_published = len(deployed_version_ids)
    model_completed = max(0, total_models - model_published)

    # 算法覆盖（工作台）：模型库各算法被多少个模型版本采用，口径同 total_models。
    # 版本未记录算法时（如直接上传的 ONNX）退回框架名，仍为空记 unknown。
    model_algorithms = Counter()
    for algorithm, framework, count in registry_query.with_entities(
        ModelVersion.algorithm, ModelVersion.framework, func.count(ModelVersion.id),
    ).group_by(ModelVersion.algorithm, ModelVersion.framework).all():
        model_algorithms[(algorithm or framework or "").strip() or "unknown"] += count

    # 旧仪表板的「算子分布」：内置算子按类别计数，与模型无关
    algorithm_categories = Counter(
        getattr(operator, "category", "utility") or "utility"
        for operator in operators
    )

    payload = {
        "core_assets": {
            "total_algorithms": total_algorithms,
            "total_datasets": total_datasets,
            "total_models": total_models,
            "total_apis": total_apis,
            "total_samples": total_samples,
        },
        "business_stats": {
            "total_projects": total_projects,
            "total_users": total_users,
            "total_training_jobs": total_training_jobs,
            "total_api_calls": total_api_calls,
            "successful_api_calls": total_success_calls,
        },
        "model_status": {
            "training": model_training,
            "completed": model_completed,
            "published": model_published,
        },
        "algorithm_coverage": [
            {"category": category, "count": count}
            for category, count in sorted(algorithm_categories.items())
        ],
        "model_algorithm_coverage": [
            {"name": name, "count": count}
            for name, count in sorted(model_algorithms.items(), key=lambda item: (-item[1], item[0]))
        ],
    }
    _stats_cache[cache_key] = (now + _STATS_CACHE_TTL_SECONDS, payload)
    return payload


@router.get("/recent-model-versions")
def get_recent_model_versions(
    limit: int = Query(default=6, ge=1, le=20),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """最近注册的模型版本，按注册时间倒序；数据源与权限口径同「模型版本」统计。

    不走统计缓存：工作台轮询要立即看到注册/删除。
    """
    is_platform_admin, accessible_projects = _access_scope(db, current_user)
    query = db.query(ModelVersion, RegisteredModel).join(
        RegisteredModel, ModelVersion.registered_model_id == RegisteredModel.id,
    )
    if not is_platform_admin:
        query = query.filter(RegisteredModel.project_id.in_([project.id for project in accessible_projects]))
    rows = query.order_by(
        ModelVersion.created_at.desc(), ModelVersion.version_number.desc(),
    ).limit(limit).all()
    version_ids = [version.id for version, _ in rows]
    published_ids = {
        row[0] for row in db.query(InferenceDeployment.model_version_id).filter(
            InferenceDeployment.model_version_id.in_(version_ids),
            InferenceDeployment.observed_state == "running",
        ).all()
    } if version_ids else set()
    return {
        "items": [
            {
                "id": str(version.id),
                "registered_model_id": str(model.id),
                "project_id": str(model.project_id),
                "model_name": model.name,
                "version_number": version.version_number,
                "algorithm": version.algorithm or version.framework or "",
                "metrics": version.metrics or {},
                "approval_status": version.approval_status,
                "lifecycle_state": version.lifecycle_state,
                "published": version.id in published_ids,
                "created_at": version.created_at.isoformat() if version.created_at else None,
            }
            for version, model in rows
        ]
    }


@router.get("/top-models")
def get_top_models(db: Session = Depends(get_db)):
    """Get top 10 models by performance."""
    # JSON 列排序双方言不兼容（PG 报错），Python 侧按 best_score 排序
    from app.api.model_library import top_models_by_score
    models = top_models_by_score(
        db.query(ModelLibrary).filter(
            ModelLibrary.metrics.isnot(None),
            ModelLibrary.status.in_(["completed", "published"]),
        ).all()
    )

    return {
        "items": [
            {
                "id": str(m.id),
                "name": m.name,
                "framework": m.framework,
                "backbone": m.backbone,
                "metrics": m.metrics or {},
                "status": m.status,
            }
            for m in models
        ]
    }


@router.get("/recent-activity")
def get_recent_activity(db: Session = Depends(get_db)):
    """Get recent platform activity."""
    recent_models = db.query(ModelLibrary).order_by(
        ModelLibrary.created_at.desc()
    ).limit(5).all()
    recent_datasets = db.query(Dataset).filter(
        # 项目删除时该表脱钩保留（project_id 置空），不作为平台活动展示
        Dataset.project_id.isnot(None),
    ).order_by(
        Dataset.created_at.desc()
    ).limit(5).all()

    return {
        "recent_models": [
            {"id": str(m.id), "name": m.name, "status": m.status,
             "created_at": m.created_at.isoformat() if m.created_at else None}
            for m in recent_models
        ],
        "recent_datasets": [
            {"id": str(d.id), "name": d.name, "status": d.status,
             "created_at": d.created_at.isoformat() if d.created_at else None}
            for d in recent_datasets
        ],
    }
