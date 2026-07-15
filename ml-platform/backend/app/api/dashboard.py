"""Dashboard / Data Cockpit API - aggregated platform stats."""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.model_library import ModelLibrary
from app.models.algorithm import Algorithm
from app.models.api_model import PlatformAPI
from app.models.platform_models import Dataset
from app.models.training import TrainingJob
from app.models.project import Project
from app.models.user import User

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


@router.get("/stats")
def get_dashboard_stats(db: Session = Depends(get_db)):
    """Get platform-wide statistics for the data cockpit."""
    total_algorithms = db.query(Algorithm).count()
    total_datasets = db.query(Dataset).count()
    total_models = db.query(ModelLibrary).count()
    total_apis = db.query(PlatformAPI).count()
    total_projects = db.query(Project).count()
    total_users = db.query(User).count()
    total_training_jobs = db.query(TrainingJob).count()

    # Dataset sample total
    sample_total = db.query(Dataset).with_entities(Dataset.sample_count).all()
    total_samples = sum(s[0] or 0 for s in sample_total)

    # API call stats
    api_calls = db.query(PlatformAPI).with_entities(
        PlatformAPI.total_calls, PlatformAPI.success_calls
    ).all()
    total_api_calls = sum(c[0] or 0 for c in api_calls)
    total_success_calls = sum(c[1] or 0 for c in api_calls)

    # Model by status
    model_training = db.query(ModelLibrary).filter(ModelLibrary.status == "training").count()
    model_completed = db.query(ModelLibrary).filter(ModelLibrary.status == "completed").count()
    model_published = db.query(ModelLibrary).filter(ModelLibrary.status == "published").count()

    # Algorithm by category
    from sqlalchemy import func
    algo_categories = db.query(Algorithm.category, func.count()).group_by(Algorithm.category).all()

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
            {"category": cat, "count": cnt}
            for cat, cnt in algo_categories
        ],
    }


@router.get("/top-models")
def get_top_models(db: Session = Depends(get_db)):
    """Get top 10 models by performance."""
    from sqlalchemy import func
    models = db.query(ModelLibrary).filter(
        ModelLibrary.metrics.isnot(None),
        ModelLibrary.status.in_(["completed", "published"])
    ).order_by(ModelLibrary.metrics.desc()).limit(10).all()

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
    recent_datasets = db.query(Dataset).order_by(
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
