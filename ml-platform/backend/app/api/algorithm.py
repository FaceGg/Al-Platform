"""Algorithm catalog API."""
import uuid
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.algorithm import Algorithm
from app.models.user import User
from app.api.auth import get_current_user

router = APIRouter(prefix="/api/algorithms", tags=["algorithms"])


@router.get("")
def list_algorithms(
    category: str = Query(None),
    status: str = Query(None),
    db: Session = Depends(get_db),
):
    q = db.query(Algorithm)
    if category:
        q = q.filter(Algorithm.category == category)
    if status == "active":
        q = q.filter(Algorithm.is_active == True)
    algorithms = q.order_by(Algorithm.category, Algorithm.benchmark_mAP.desc()).all()
    return {
        "items": [
            {
                "id": str(a.id),
                "name": a.name,
                "display_name": a.display_name or a.name,
                "category": a.category,
                "sub_category": a.sub_category,
                "description": a.description,
                "framework": a.framework,
                "backbone": a.backbone,
                "benchmark_mAP": a.benchmark_mAP,
                "benchmark_speed": a.benchmark_speed,
                "tags": a.tags or [],
                "version": a.version,
                "is_active": a.is_active,
            }
            for a in algorithms
        ],
        "total": len(algorithms),
        "categories": [
            {"key": "computer_vision", "label": "计算机视觉", "count": 0},
            {"key": "ocr", "label": "文本识别", "count": 0},
            {"key": "speech", "label": "语音类", "count": 0},
            {"key": "ml", "label": "机器学习", "count": 0},
            {"key": "composite", "label": "复合算法", "count": 0},
        ],
    }


@router.get("/categories")
def list_categories(db: Session = Depends(get_db)):
    cats = db.query(Algorithm.category).distinct().all()
    return {"categories": [c[0] for c in cats]}


@router.get("/{algo_id}")
def get_algorithm(algo_id: str, db: Session = Depends(get_db)):
    algo = db.query(Algorithm).filter(Algorithm.id == uuid.UUID(algo_id)).first()
    if not algo:
        raise HTTPException(404, "Algorithm not found")
    return {
        "id": str(algo.id),
        "name": algo.name,
        "display_name": algo.display_name or algo.name,
        "category": algo.category,
        "description": algo.description,
        "benchmark_mAP": algo.benchmark_mAP,
        "is_active": algo.is_active,
        "created_at": algo.created_at.isoformat() if algo.created_at else None,
    }


@router.post("")
def create_algorithm(data: dict, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    algo = Algorithm(
        name=data["name"],
        display_name=data.get("display_name", data["name"]),
        category=data.get("category", "ml"),
        sub_category=data.get("sub_category", ""),
        description=data.get("description", ""),
        framework=data.get("framework", ""),
        backbone=data.get("backbone", ""),
        params_config=data.get("params_config", {}),
        default_params=data.get("default_params", {}),
        benchmark_mAP=data.get("benchmark_mAP", 0),
        benchmark_speed=data.get("benchmark_speed", 0),
        tags=data.get("tags", []),
    )
    db.add(algo)
    db.commit()
    db.refresh(algo)
    return {"id": str(algo.id), "name": algo.name}


@router.put("/{algo_id}")
def update_algorithm(algo_id: str, data: dict, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    algo = db.query(Algorithm).filter(Algorithm.id == uuid.UUID(algo_id)).first()
    if not algo:
        raise HTTPException(404, "Algorithm not found")
    for key in ["name", "display_name", "category", "sub_category", "description", "framework", "backbone", "is_active"]:
        if key in data:
            setattr(algo, key, data[key])
    db.commit()
    return {"status": "ok"}


@router.delete("/{algo_id}")
def delete_algorithm(algo_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    algo = db.query(Algorithm).filter(Algorithm.id == uuid.UUID(algo_id)).first()
    if not algo:
        raise HTTPException(404, "Algorithm not found")
    db.delete(algo)
    db.commit()
    return {"status": "deleted"}
