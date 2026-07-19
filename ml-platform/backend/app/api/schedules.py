"""Project-owned pipeline scheduling API."""

from datetime import datetime, timezone
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session

from app.api.auth import get_current_user
from app.database import get_db
from app.models.project import Project
from app.models.schedule import PipelineSchedule, PipelineScheduleRun
from app.models.user import User
from app.models.workflow import Workflow
from app.schemas.schedule import (
    BackfillRequest,
    ScheduleCreate,
    ScheduleList,
    ScheduleResponse,
    ScheduleRunList,
    ScheduleUpdate,
)
from app.services.pipeline_scheduler import PipelineScheduler, ScheduleError, next_occurrence
from app.api.project_security import audit_service, require_project_access, resolve_project_access
from app.services.audit import AuditIntent


router = APIRouter(tags=["schedules"])
PROJECT_WRITE_ACTIONS = {
    "POST /api/projects/{project_id}/schedules": "schedule.create",
    "PATCH /api/schedules/{schedule_id}": "schedule.update",
    "POST /api/schedules/{schedule_id}/pause": "schedule.pause",
    "POST /api/schedules/{schedule_id}/resume": "schedule.resume",
    "POST /api/schedules/{schedule_id}/backfill": "schedule.backfill",
}


def _error(code: str, message: str) -> dict:
    return {"code": code, "message": message}


def _schedule_access(db, schedule_id, user_id):
    schedule = db.query(PipelineSchedule).filter(PipelineSchedule.id == schedule_id).first()
    if schedule is None:
        raise HTTPException(404, _error("SCHEDULE_NOT_FOUND", "Schedule not found"))
    access = resolve_project_access(db, schedule.project_id, user_id)
    if access is None:
        raise HTTPException(404, _error("SCHEDULE_NOT_FOUND", "Schedule not found"))
    return schedule, access


def _scheduler() -> PipelineScheduler:
    from app.api.runs import get_task_dispatcher

    dispatcher = get_task_dispatcher()
    return PipelineScheduler(enqueue=dispatcher.enqueue_workflow)


def _validate_calendar(expression: str, timezone_name: str, base: datetime) -> datetime:
    try:
        return next_occurrence(expression, timezone_name, base)
    except ScheduleError as error:
        raise HTTPException(422, _error(error.code, str(error))) from error


@router.post(
    "/api/projects/{project_id}/schedules",
    response_model=ScheduleResponse,
    status_code=201,
)
def create_schedule(
    project_id: uuid.UUID,
    data: ScheduleCreate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    access = resolve_project_access(db, project_id, current_user.id)
    project = access.project if access is not None else None
    workflow = db.query(Workflow).filter(
        Workflow.id == data.workflow_id,
        Workflow.project_id == project_id,
    ).first()
    if workflow is None:
        raise HTTPException(404, _error("WORKFLOW_NOT_FOUND", "Workflow not found"))
    duplicate = db.query(PipelineSchedule).filter(
        PipelineSchedule.project_id == project_id,
        PipelineSchedule.name == data.name,
    ).first()
    if duplicate is not None:
        raise HTTPException(409, _error("SCHEDULE_NAME_CONFLICT", "Schedule name already exists"))
    now = datetime.now(timezone.utc)
    schedule = PipelineSchedule(
        project_id=project_id,
        workflow_id=workflow.id,
        created_by=current_user.id,
        name=data.name,
        cron_expression=data.cron_expression,
        timezone=data.timezone,
        max_concurrency=data.max_concurrency,
        dependencies=[str(value) for value in data.dependencies],
        retry_policy=data.retry_policy.model_dump(),
        timeout_seconds=data.timeout_seconds,
        workflow_version=data.workflow_version,
        next_run_at=_validate_calendar(data.cron_expression, data.timezone, now).replace(tzinfo=None),
    )
    with audit_service(db).project_action(
        db,
        request=request,
        actor=current_user,
        access=access,
        permission="schedule.manage",
        intent=AuditIntent(
            project_id=project_id,
            action="schedule.create",
            resource_type="schedule",
            changes=data.model_dump(mode="json"),
        ),
        allowed_changes={
            "name", "workflow_id", "cron_expression", "timezone",
            "max_concurrency", "dependencies", "retry_policy", "timeout_seconds",
        },
    ):
        db.add(schedule)
    db.refresh(schedule)
    return schedule


@router.get("/api/projects/{project_id}/schedules", response_model=ScheduleList)
def list_schedules(
    project_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    project = require_project_access(
        db, project_id, current_user.id, "project.read",
    ).project
    items = db.query(PipelineSchedule).filter(
        PipelineSchedule.project_id == project.id,
    ).order_by(PipelineSchedule.created_at.desc(), PipelineSchedule.id).all()
    return {"items": items, "total": len(items)}


@router.get("/api/schedules/{schedule_id}", response_model=ScheduleResponse)
def get_schedule(
    schedule_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    schedule, _ = _schedule_access(db, schedule_id, current_user.id)
    return schedule


@router.patch("/api/schedules/{schedule_id}", response_model=ScheduleResponse)
def update_schedule(
    schedule_id: uuid.UUID,
    data: ScheduleUpdate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    schedule, access = _schedule_access(db, schedule_id, current_user.id)
    values = data.model_dump(exclude_unset=True)
    if "dependencies" in values:
        values["dependencies"] = [str(value) for value in values["dependencies"]]
    if "retry_policy" in values and values["retry_policy"] is not None:
        values["retry_policy"] = values["retry_policy"].model_dump()
    expression = values.get("cron_expression", schedule.cron_expression)
    timezone_name = values.get("timezone", schedule.timezone)
    if "cron_expression" in values or "timezone" in values:
        values["next_run_at"] = _validate_calendar(
            expression,
            timezone_name,
            datetime.now(timezone.utc),
        ).replace(tzinfo=None)
    with audit_service(db).project_action(
        db,
        request=request,
        actor=current_user,
        access=access,
        permission="schedule.manage",
        intent=AuditIntent(
            project_id=schedule.project_id,
            action="schedule.update",
            resource_type="schedule",
            resource_id=str(schedule.id),
            changes=data.model_dump(exclude_unset=True, mode="json"),
        ),
        allowed_changes={
            "name", "cron_expression", "timezone", "max_concurrency",
            "dependencies", "retry_policy", "timeout_seconds",
        },
    ):
        for key, value in values.items():
            setattr(schedule, key, value)
    db.refresh(schedule)
    return schedule


@router.post("/api/schedules/{schedule_id}/pause", response_model=ScheduleResponse)
def pause_schedule(
    schedule_id: uuid.UUID,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    schedule, access = _schedule_access(db, schedule_id, current_user.id)
    try:
        with audit_service(db).project_action(
            db, request=request, actor=current_user, access=access,
            permission="schedule.operate",
            intent=AuditIntent(
                project_id=schedule.project_id, action="schedule.pause",
                resource_type="schedule", resource_id=str(schedule.id),
            ),
            allowed_changes=set(),
        ):
            result = _scheduler().pause(db, schedule, commit=False)
        return result
    except ScheduleError as error:
        raise HTTPException(409, _error(error.code, str(error))) from error


@router.post("/api/schedules/{schedule_id}/resume", response_model=ScheduleResponse)
def resume_schedule(
    schedule_id: uuid.UUID,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    schedule, access = _schedule_access(db, schedule_id, current_user.id)
    try:
        with audit_service(db).project_action(
            db, request=request, actor=current_user, access=access,
            permission="schedule.operate",
            intent=AuditIntent(
                project_id=schedule.project_id, action="schedule.resume",
                resource_type="schedule", resource_id=str(schedule.id),
            ),
            allowed_changes=set(),
        ):
            result = _scheduler().resume(db, schedule, commit=False)
        return result
    except ScheduleError as error:
        raise HTTPException(409, _error(error.code, str(error))) from error


@router.post("/api/schedules/{schedule_id}/backfill")
def backfill_schedule(
    schedule_id: uuid.UUID,
    data: BackfillRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    schedule, access = _schedule_access(db, schedule_id, current_user.id)
    with audit_service(db).project_action(
        db, request=request, actor=current_user, access=access,
        permission="schedule.operate",
        intent=AuditIntent(
            project_id=schedule.project_id, action="schedule.backfill",
            resource_type="schedule", resource_id=str(schedule.id),
            changes={"occurrence_count": len(data.occurrences)},
        ),
        allowed_changes={"occurrence_count"},
    ):
        pass
    return {"items": _scheduler().backfill(db, schedule, data.occurrences)}


@router.get("/api/schedules/{schedule_id}/runs", response_model=ScheduleRunList)
def list_schedule_runs(
    schedule_id: uuid.UUID,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    schedule, _ = _schedule_access(db, schedule_id, current_user.id)
    query = db.query(PipelineScheduleRun).filter(PipelineScheduleRun.schedule_id == schedule.id)
    total = query.count()
    items = query.order_by(PipelineScheduleRun.scheduled_for.desc()).offset(offset).limit(limit).all()
    return {"items": items, "total": total, "offset": offset, "limit": limit}
