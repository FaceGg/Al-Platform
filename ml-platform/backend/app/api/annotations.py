"""Annotation task management API."""
import uuid
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.platform_models import AnnotationTask, AnnotationResult, Dataset
from app.models.user import User
from app.api.auth import get_current_user

router = APIRouter(prefix="/api/annotations", tags=["annotations"])


@router.get("/tasks")
def list_tasks(
    status: str = Query(None),
    dataset_id: str = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    q = db.query(AnnotationTask).filter(AnnotationTask.owner_id == current_user.id)
    if status:
        q = q.filter(AnnotationTask.status == status)
    if dataset_id:
        q = q.filter(AnnotationTask.dataset_id == uuid.UUID(dataset_id))
    tasks = q.order_by(AnnotationTask.created_at.desc()).all()
    return {
        "items": [
            {
                "id": str(t.id),
                "name": t.name,
                "dataset_id": str(t.dataset_id),
                "annotation_type": t.annotation_type,
                "status": t.status,
                "total_samples": t.total_samples,
                "labeled_samples": t.labeled_samples,
                "reviewed_samples": t.reviewed_samples,
                "created_at": t.created_at.isoformat() if t.created_at else None,
            }
            for t in tasks
        ],
        "total": len(tasks),
    }


@router.post("/tasks")
def create_task(data: dict, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    task = AnnotationTask(
        name=data["name"],
        dataset_id=uuid.UUID(data["dataset_id"]),
        owner_id=current_user.id,
        annotation_type=data.get("annotation_type", "rectangle"),
        description=data.get("description", ""),
        guidelines=data.get("guidelines", ""),
        auto_label_config=data.get("auto_label_config", {}),
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    return {"id": str(task.id), "name": task.name}


@router.get("/tasks/{task_id}")
def get_task(task_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    t = db.query(AnnotationTask).filter(AnnotationTask.id == uuid.UUID(task_id)).first()
    if not t:
        raise HTTPException(404)
    return {
        "id": str(t.id),
        "name": t.name,
        "dataset_id": str(t.dataset_id),
        "annotation_type": t.annotation_type,
        "status": t.status,
        "description": t.description,
        "guidelines": t.guidelines,
        "total_samples": t.total_samples,
        "labeled_samples": t.labeled_samples,
        "reviewed_samples": t.reviewed_samples,
        "auto_label_config": t.auto_label_config or {},
        "created_at": t.created_at.isoformat() if t.created_at else None,
    }


@router.put("/tasks/{task_id}")
def update_task(task_id: str, data: dict, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    t = db.query(AnnotationTask).filter(AnnotationTask.id == uuid.UUID(task_id)).first()
    if not t:
        raise HTTPException(404)
    for key in ["name", "status", "annotation_type", "description", "guidelines"]:
        if key in data:
            setattr(t, key, data[key])
    if "total_samples" in data:
        t.total_samples = data["total_samples"]
    if "labeled_samples" in data:
        t.labeled_samples = data["labeled_samples"]
    db.commit()
    return {"status": "ok"}


@router.delete("/tasks/{task_id}")
def delete_task(task_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    t = db.query(AnnotationTask).filter(AnnotationTask.id == uuid.UUID(task_id)).first()
    if not t:
        raise HTTPException(404)
    db.delete(t)
    db.commit()
    return {"status": "deleted"}


@router.get("/tasks/{task_id}/samples")
def list_samples(task_id: str, status: str = Query(None), db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    q = db.query(AnnotationResult).filter(AnnotationResult.task_id == uuid.UUID(task_id))
    if status:
        q = q.filter(AnnotationResult.status == status)
    samples = q.order_by(AnnotationResult.sample_index).all()
    return {
        "items": [
            {
                "id": str(s.id),
                "sample_index": s.sample_index,
                "sample_path": s.sample_path,
                "annotations": s.annotations or [],
                "status": s.status,
                "is_auto_labeled": s.is_auto_labeled,
                "labeled_by": str(s.labeled_by) if s.labeled_by else None,
            }
            for s in samples
        ],
        "total": len(samples),
    }


@router.put("/samples/{sample_id}")
def update_sample(sample_id: str, data: dict, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    s = db.query(AnnotationResult).filter(AnnotationResult.id == uuid.UUID(sample_id)).first()
    if not s:
        raise HTTPException(404)
    if "annotations" in data:
        s.annotations = data["annotations"]
    if "status" in data:
        s.status = data["status"]
    s.labeled_by = current_user.id
    db.commit()

    # Update task progress
    task = db.query(AnnotationTask).filter(AnnotationTask.id == s.task_id).first()
    if task:
        task.labeled_samples = db.query(AnnotationResult).filter(
            AnnotationResult.task_id == task.id,
            AnnotationResult.status.in_(["labeled", "reviewed"])
        ).count()
        task.reviewed_samples = db.query(AnnotationResult).filter(
            AnnotationResult.task_id == task.id,
            AnnotationResult.status == "reviewed"
        ).count()
        db.commit()

    return {"status": "ok"}


@router.post("/tasks/{task_id}/auto-label")
def auto_label(task_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Trigger auto-labeling for pending samples."""
    task = db.query(AnnotationTask).filter(AnnotationTask.id == uuid.UUID(task_id)).first()
    if not task:
        raise HTTPException(404)

    unlabeled = db.query(AnnotationResult).filter(
        AnnotationResult.task_id == uuid.UUID(task_id),
        AnnotationResult.status == "unlabeled"
    ).all()

    count = 0
    for s in unlabeled:
        s.annotations = []  # Placeholder - real auto-label would call ML model
        s.status = "labeled"
        s.is_auto_labeled = True
        count += 1
    db.commit()

    # Update task progress
    task.labeled_samples = db.query(AnnotationResult).filter(
        AnnotationResult.task_id == task.id,
        AnnotationResult.status.in_(["labeled", "reviewed"])
    ).count()
    db.commit()

    return {"auto_labeled": count}
