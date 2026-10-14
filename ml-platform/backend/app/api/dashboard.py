"""Dashboard / Data Cockpit API - aggregated platform stats."""
from fastapi import APIRouter, Depends
from sqlalchemy import or_
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


@router.get("/stats")
def get_dashboard_stats(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get statistics limited to the signed-in user's permitted resources."""
    from collections import Counter

    from app.engine.registry import OperatorRegistry

    operators = OperatorRegistry.list_all()
    access_service = ProjectAccessService()
    is_platform_admin = access_service.is_platform_admin(db, current_user.id)
    accessible_projects = (
        db.query(Project).all()
        if is_platform_admin
        else access_service.accessible_project_query(db, current_user.id).all()
    )
    accessible_project_ids = [project.id for project in accessible_projects]

    # Same semantics as the dataset management list: archived (deleted) and
    # internal normalized artifacts are not user-visible datasets.
    datasets_query = db.query(Artifact).filter(
        Artifact.type == "dataset",
        Artifact.archived_at.is_(None),
    )
    if not is_platform_admin:
        datasets_query = datasets_query.filter(
            Artifact.project_id.in_(accessible_project_ids),
        )
    datasets = [
        artifact
        for artifact in datasets_query.all()
        if (artifact.metadata_ or {}).get("source") != "normalized"
    ]

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
    total_datasets = len(datasets)
    total_apis = apis_query.count()
    total_projects = len(accessible_projects)
    total_users = db.query(User).count() if is_platform_admin else 1
    total_training_jobs = training_jobs_query.count()

    # Dataset sample total
    total_samples = sum(
        int((artifact.metadata_ or {}).get("row_count") or 0)
        for artifact in datasets
    )

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

    algorithm_categories = Counter(
        getattr(operator, "category", "utility") or "utility"
        for operator in operators
    )

    return {
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
