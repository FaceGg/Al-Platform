"""Project-authorized experiment and tracked Run API."""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from mlflow.tracking import MlflowClient
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.api.auth import get_current_user
from app.database import get_db
from app.models.experiment import Experiment
from app.models.project import Project
from app.models.user import User
from app.schemas.experiment import (
    ExperimentCreate,
    ExperimentList,
    ExperimentResponse,
    RunCompareRequest,
    RunComparison,
    RunList,
)
from app.services.experiment_tracking import (
    MlflowExperimentTracking,
    TrackingNotFound,
    TrackingUnavailable,
)
from app.api.project_security import audit_service, require_project_access, resolve_project_access
from app.services.audit import AuditIntent


router = APIRouter(prefix="/api/experiments", tags=["experiments"])


def get_experiment_tracking(request: Request):
    configured = getattr(request.app.state, "experiment_tracking", None)
    if configured is not None:
        return configured
    app_settings = getattr(request.app.state, "settings", None)
    if app_settings is None:
        from app.config import settings as app_settings
    if not app_settings.mlflow_tracking_uri or not app_settings.mlflow_artifact_root:
        raise HTTPException(503, _error(
            "TRACKING_UNAVAILABLE",
            "Experiment tracking is not configured",
        ))
    configured = MlflowExperimentTracking(
        client=MlflowClient(tracking_uri=app_settings.mlflow_tracking_uri),
        artifact_root=app_settings.mlflow_artifact_root,
    )
    request.app.state.experiment_tracking = configured
    return configured


@router.post("", response_model=ExperimentResponse, status_code=201)
def create_experiment(
    data: ExperimentCreate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    access = resolve_project_access(db, data.project_id, current_user.id)

    experiment = Experiment(
        id=uuid.uuid4(),
        project_id=data.project_id,
        created_by=current_user.id,
        name=data.name,
        description=data.description,
        mlflow_experiment_id="pending",
    )
    try:
        with audit_service(db).project_action(
            db, request=request, actor=current_user, access=access,
            permission="resource.create",
            intent=AuditIntent(
                project_id=data.project_id, action="experiment.create",
                resource_type="experiment", resource_id=str(experiment.id),
                changes={"name": data.name, "description": data.description},
            ),
            allowed_changes={"name", "description"},
        ):
            duplicate = db.query(Experiment).filter(
                Experiment.project_id == data.project_id,
                Experiment.name == data.name,
            ).first()
            if duplicate is not None:
                raise HTTPException(409, _error(
                    "EXPERIMENT_NAME_CONFLICT",
                    "Experiment name already exists in project",
                ))
            tracking = get_experiment_tracking(request)
            namespace = f"project/{data.project_id}/{experiment.id}"
            try:
                experiment.mlflow_experiment_id = tracking.ensure_experiment(namespace)
            except (TrackingUnavailable, TrackingNotFound) as error:
                raise _tracking_error(error) from error
            db.add(experiment)
        db.refresh(experiment)
    except IntegrityError as error:
        raise HTTPException(409, _error(
            "EXPERIMENT_PERSISTENCE_FAILED",
            "Experiment tracking state exists but platform persistence failed",
        )) from error
    except SQLAlchemyError as error:
        raise HTTPException(500, _error(
            "EXPERIMENT_PERSISTENCE_FAILED",
            "Experiment tracking state exists but platform persistence failed",
        )) from error
    return experiment


@router.get("", response_model=ExperimentList)
def list_experiments(
    project_id: uuid.UUID = Query(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    project = require_project_access(
        db, project_id, current_user.id, "project.read",
    ).project
    items = db.query(Experiment).filter(
        Experiment.project_id == project.id,
    ).order_by(Experiment.created_at.desc(), Experiment.id).all()
    return {"items": items, "total": len(items)}


@router.get("/{experiment_id}", response_model=ExperimentResponse)
def get_experiment(
    experiment_id: uuid.UUID,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    experiment = _visible_experiment(db, experiment_id, current_user.id)
    if experiment is None:
        raise HTTPException(404, _error("EXPERIMENT_NOT_FOUND", "Experiment not found"))
    tracking = get_experiment_tracking(request)
    try:
        run_count = len(tracking.search_runs([experiment.mlflow_experiment_id]))
    except (TrackingUnavailable, TrackingNotFound) as error:
        raise _tracking_error(error) from error
    return _experiment_payload(experiment, run_count=run_count)


@router.get("/{experiment_id}/runs", response_model=RunList)
def list_experiment_runs(
    experiment_id: uuid.UUID,
    request: Request,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    experiment = _visible_experiment(db, experiment_id, current_user.id)
    if experiment is None:
        raise HTTPException(404, _error("EXPERIMENT_NOT_FOUND", "Experiment not found"))
    tracking = get_experiment_tracking(request)
    try:
        runs = tracking.search_runs([experiment.mlflow_experiment_id])
    except (TrackingUnavailable, TrackingNotFound) as error:
        raise _tracking_error(error) from error
    return {
        "items": [_run_payload(run) for run in runs[offset:offset + limit]],
        "total": len(runs),
        "offset": offset,
        "limit": limit,
    }


@router.post("/{experiment_id}/compare", response_model=RunComparison)
def compare_experiment_runs(
    experiment_id: uuid.UUID,
    data: RunCompareRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    experiment = _visible_experiment(db, experiment_id, current_user.id)
    if experiment is None:
        raise HTTPException(404, _error("EXPERIMENT_NOT_FOUND", "Experiment not found"))
    tracking = get_experiment_tracking(request)
    try:
        runs = tracking.compare_runs(data.run_ids)
    except (TrackingUnavailable, TrackingNotFound, KeyError) as error:
        if isinstance(error, TrackingUnavailable):
            raise _tracking_error(error) from error
        raise HTTPException(404, _error("RUN_NOT_FOUND", "Run not found")) from error
    if len(runs) != len(data.run_ids) or any(
        run.experiment_id != experiment.mlflow_experiment_id for run in runs
    ):
        raise HTTPException(404, _error("RUN_NOT_FOUND", "Run not found"))

    param_names = sorted({key for run in runs for key in run.params})
    metric_names = sorted({key for run in runs for key in run.metrics})
    rows = []
    for run in runs:
        try:
            histories = {
                name: [
                    {
                        "key": metric.key,
                        "value": metric.value,
                        "timestamp": metric.timestamp,
                        "step": metric.step,
                    }
                    for metric in tracking.get_metric_history(run.run_id, name)
                ]
                for name in metric_names
            }
        except (TrackingUnavailable, TrackingNotFound) as error:
            raise _tracking_error(error) from error
        rows.append({
            **_run_payload(run),
            "params": {name: run.params.get(name) for name in param_names},
            "metrics": {name: run.metrics.get(name) for name in metric_names},
            "metric_history": histories,
            "missing": {
                "params": [name for name in param_names if name not in run.params],
                "metrics": [name for name in metric_names if name not in run.metrics],
            },
        })
    return {
        "run_ids": list(data.run_ids),
        "param_names": param_names,
        "metric_names": metric_names,
        "runs": rows,
    }


def _visible_experiment(db: Session, experiment_id, user_id):
    experiment = db.query(Experiment).filter(Experiment.id == experiment_id).first()
    if experiment is None:
        return None
    if resolve_project_access(db, experiment.project_id, user_id) is None:
        return None
    return experiment


def _experiment_payload(experiment: Experiment, *, run_count: int = 0) -> dict:
    return {
        "id": experiment.id,
        "project_id": experiment.project_id,
        "created_by": experiment.created_by,
        "name": experiment.name,
        "description": experiment.description or "",
        "mlflow_experiment_id": experiment.mlflow_experiment_id,
        "created_at": experiment.created_at,
        "updated_at": experiment.updated_at,
        "run_count": run_count,
    }


def _run_payload(run) -> dict:
    return {
        "run_id": run.run_id,
        "experiment_id": run.experiment_id,
        "run_name": run.run_name,
        "status": run.status,
        "start_time": run.start_time,
        "end_time": run.end_time,
        "artifact_uri": run.artifact_uri,
        "params": dict(run.params),
        "metrics": dict(run.metrics),
        "tags": dict(run.tags),
        "parent_run_id": run.parent_run_id,
    }


def _tracking_error(error: Exception) -> HTTPException:
    if isinstance(error, TrackingNotFound):
        return HTTPException(404, _error("TRACKING_NOT_FOUND", "Tracking resource not found"))
    return HTTPException(503, _error("TRACKING_UNAVAILABLE", "Experiment tracking is unavailable"))


def _error(code: str, message: str) -> dict[str, str]:
    return {"code": code, "message": message}
