"""Annotation task management API."""
import uuid
from fastapi import APIRouter, Depends, HTTPException, Query, Header, Request
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.platform_models import AnnotationTask, AnnotationResult, Dataset
from app.models.user import User
from app.models.labeling import LabelSchema, LabelColumn, AnnotationSampleCurrent
from app.models.project import Project
from app.schemas.labeling import LabelRevisionWrite, LabelSchemaCreate
from app.services.label_schema import (LabelValueError, confirm_label_values, create_label_schema, get_current_label_set, require_task_schema_binding, write_label_revision)
from app.api.auth import get_current_user
from app.services.resource_access import ResourceAccessService
from app.schemas.annotator import AssignmentCreate, AssignmentEditRequest, AssignmentReturnRequest, LabelSaveRequest
from app.services.annotation_concurrency import AssignmentError, AssignmentLockedError, confirm_assignment, create_assignments, edit_for_return, return_assignment, save_labels

router = APIRouter(prefix="/api/annotations", tags=["annotations"])


@router.post("/assignments", status_code=201)
def create_annotation_assignments(task_id: str, data: AssignmentCreate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    try:
        assignments = create_assignments(db, task_id=uuid.UUID(task_id), annotator_ids=data.annotator_ids, sample_scope=data.sample_scope, due_at=data.due_at, actor=current_user.id)
    except (ValueError, AssignmentError) as error:
        raise HTTPException(status_code=422, detail={"code": getattr(error, "code", "ASSIGNMENT_INVALID"), "message": str(error)}) from error
    return {"items": [{"id": str(item.id), "task_id": str(item.task_id), "annotator_subject_id": str(item.annotator_subject_id), "sample_scope": item.sample_scope, "scope_hash": item.scope_hash, "state": item.state} for item in assignments]}


@router.put("/assignments/{assignment_id}/samples/{sample_id}")
def save_annotation_labels(assignment_id: str, sample_id: str, data: LabelSaveRequest, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    try:
        result = save_labels(db, uuid.UUID(assignment_id), sample_id, data.values, data.base_revision, actor=current_user.id)
    except AssignmentLockedError as error:
        raise HTTPException(status_code=409, detail={"code": error.code, "message": str(error)}) from error
    except AssignmentError as error:
        raise HTTPException(status_code=422, detail={"code": error.code, "message": str(error)}) from error
    if hasattr(result, "current_values"):
        raise HTTPException(status_code=409, detail={"code": "REVISION_CONFLICT", "current_revision": result.current_revision, "current_values": result.current_values, "diff_summary": result.diff_summary})
    return {"values": result.values, "revision_no": result.revision_no}


@router.post("/assignments/{assignment_id}/confirm")
def confirm_annotation_assignment(assignment_id: str, task_revision: int, scope_hash: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    try:
        result = confirm_assignment(db, uuid.UUID(assignment_id), task_revision, scope_hash)
    except AssignmentError as error:
        raise HTTPException(status_code=409, detail={"code": error.code, "message": str(error)}) from error
    return {"assignment_id": str(result.assignment_id), "task_revision": result.task_revision, "scope_hash": result.scope_hash}


@router.post("/assignments/{assignment_id}/edit-for-return")
def edit_annotation_assignment(assignment_id: str, data: AssignmentEditRequest, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    try:
        result = edit_for_return(db, uuid.UUID(assignment_id), data.task_revision)
    except AssignmentError as error:
        raise HTTPException(status_code=409, detail={"code": error.code, "message": str(error)}) from error
    return {"assignment_id": str(result.id), "state": result.state, "task_revision": result.task_revision}


@router.post("/assignments/{assignment_id}/return", status_code=202)
def return_annotation_assignment(assignment_id: str, data: AssignmentReturnRequest, request: Request, db: Session = Depends(get_db), current_user: User = Depends(get_current_user), idempotency_key: str | None = Header(default=None, alias="Idempotency-Key")):
    if not idempotency_key:
        raise HTTPException(status_code=400, detail={"code": "IDEMPOTENCY_KEY_REQUIRED"})
    try:
        result = return_assignment(db, uuid.UUID(assignment_id), data.task_revision, data.scope_hash, idempotency_key)
    except AssignmentLockedError as error:
        raise HTTPException(status_code=409, detail={"code": error.code, "message": str(error)}) from error
    except AssignmentError as error:
        raise HTTPException(status_code=409, detail={"code": error.code, "message": str(error)}) from error
    return {
        "return_batch_id": str(result.return_batch_id),
        "operation_id": str(result.operation_id) if result.operation_id else None,
        "state": result.state,
    }


def _owned_task(db, task_id: str, user_id):
    return ResourceAccessService().require_owned(
        db,
        AnnotationTask,
        task_id,
        user_id,
    )


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
    dataset = ResourceAccessService().require_owned(
        db,
        Dataset,
        data["dataset_id"],
        current_user.id,
    )
    task = AnnotationTask(
        name=data["name"],
        dataset_id=dataset.id,
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
    t = _owned_task(db, task_id, current_user.id)
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
    t = _owned_task(db, task_id, current_user.id)
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
    t = _owned_task(db, task_id, current_user.id)
    db.delete(t)
    db.commit()
    return {"status": "deleted"}


@router.get("/tasks/{task_id}/samples")
def list_samples(task_id: str, status: str = Query(None), db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    task = _owned_task(db, task_id, current_user.id)
    q = db.query(AnnotationResult).filter(AnnotationResult.task_id == task.id)
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
    s, task = ResourceAccessService().require_annotation_sample(
        db,
        sample_id,
        current_user.id,
    )
    if "annotations" in data:
        s.annotations = data["annotations"]
    if "status" in data:
        s.status = data["status"]
    s.labeled_by = current_user.id
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
    task = _owned_task(db, task_id, current_user.id)

    unlabeled = db.query(AnnotationResult).filter(
        AnnotationResult.task_id == task.id,
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


def _owned_schema(db: Session, schema_id: str, user_id):
    try:
        parsed_schema_id = uuid.UUID(schema_id)
    except ValueError as error:
        raise HTTPException(status_code=404, detail={"code": "LABEL_SCHEMA_NOT_FOUND"}) from error
    schema = db.get(LabelSchema, parsed_schema_id)
    if schema is None:
        raise HTTPException(status_code=404, detail={"code": "LABEL_SCHEMA_NOT_FOUND"})
    ResourceAccessService().require_owned(db, Project, schema.project_id, user_id)
    return schema


def _bound_task_schema(db: Session, task_id: str, schema_id: str):
    try:
        parsed_task_id = uuid.UUID(task_id)
        parsed_schema_id = uuid.UUID(schema_id)
    except ValueError as error:
        raise HTTPException(status_code=422, detail={"code": "INVALID_UUID"}) from error
    try:
        require_task_schema_binding(db, task_id=parsed_task_id, schema_id=parsed_schema_id)
    except LabelValueError as error:
        raise HTTPException(status_code=409, detail={"code": error.code, "message": str(error)}) from error
    return parsed_task_id


@router.post("/label-schemas", status_code=201)
def create_schema(data: LabelSchemaCreate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    ResourceAccessService().require_owned(db, Project, data.project_id, current_user.id)
    schema = create_label_schema(
        db,
        project_id=data.project_id,
        name=data.name,
        purpose=data.purpose,
        columns=data.columns,
    )
    return {
        "id": str(schema.id),
        "project_id": str(schema.project_id),
        "name": schema.name,
        "version": schema.version,
        "purpose": schema.purpose,
    }


@router.get("/label-schemas/{schema_id}")
def get_label_schema(schema_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    schema = _owned_schema(db, schema_id, current_user.id)
    return {
        "id": str(schema.id), "project_id": str(schema.project_id), "name": schema.name,
        "version": schema.version, "status": schema.status, "purpose": schema.purpose,
        "columns": [
            {"machine_key": item.machine_key, "display_name": item.display_name, "ordinal": item.ordinal,
             "value_type": item.value_type, "required": item.required, "enum_values": item.enum_values or [],
             "min_value": item.min_value, "max_value": item.max_value, "max_length": item.max_length,
             "instruction": item.instruction}
            for item in sorted(schema.columns, key=lambda value: value.ordinal)
        ],
    }


@router.get("/label-schemas/{schema_id}/samples/{sample_id}")
def get_sample_labels(schema_id: str, sample_id: str, task_id: str = Query(...), db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    _owned_schema(db, schema_id, current_user.id)
    parsed_task_id = _bound_task_schema(db, task_id, schema_id)
    try:
        current = get_current_label_set(db, parsed_task_id, sample_id)
    except LabelValueError as error:
        raise HTTPException(status_code=404, detail={"code": error.code}) from error
    if str(db.query(AnnotationSampleCurrent.schema_id).filter_by(task_id=uuid.UUID(task_id), sample_id=sample_id).scalar()) != schema_id:
        raise HTTPException(status_code=409, detail={"code": "LABEL_SCHEMA_MISMATCH"})
    return {"sample_id": sample_id, "values": current.values, "revision_no": current.revision_no}


@router.put("/label-schemas/{schema_id}/samples/{sample_id}")
def update_sample_labels(schema_id: str, sample_id: str, data: LabelRevisionWrite, task_id: str = Query(...), db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    _owned_schema(db, schema_id, current_user.id)
    parsed_task_id = _bound_task_schema(db, task_id, schema_id)
    try:
        current = get_current_label_set(db, parsed_task_id, sample_id)
        if str(db.query(AnnotationSampleCurrent.schema_id).filter_by(task_id=uuid.UUID(task_id), sample_id=sample_id).scalar()) != schema_id:
            raise LabelValueError("schema mismatch", "LABEL_SCHEMA_MISMATCH")
        result = write_label_revision(
            db, parsed_task_id, sample_id, data.values, current_user.id, data.base_revision,
        )
    except LabelValueError as error:
        code = 409 if error.code == "LABEL_REVISION_CONFLICT" else 422
        raise HTTPException(status_code=code, detail={"code": error.code, "message": str(error)}) from error
    return {"sample_id": sample_id, "values": result.values, "revision_no": result.revision_no}


@router.post("/label-schemas/{schema_id}/samples/{sample_id}/confirm")
def confirm_sample_labels(schema_id: str, sample_id: str, task_id: str = Query(...), db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    _owned_schema(db, schema_id, current_user.id)
    parsed_task_id = _bound_task_schema(db, task_id, schema_id)
    try:
        confirmation = confirm_label_values(db, parsed_task_id, sample_id, current_user.id)
    except LabelValueError as error:
        raise HTTPException(status_code=422, detail={"code": error.code, "message": str(error)}) from error
    return {"id": str(confirmation.id), "action": confirmation.action}
