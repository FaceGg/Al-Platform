"""Platform API management (component marketplace)."""
import uuid
from datetime import datetime
from enum import Enum
from typing import Any, Optional

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import or_
from sqlalchemy.orm import Session
from app.database import get_db, SessionLocal
from app.models.api_model import PlatformAPI
from app.models.user import User
from app.api.auth import get_current_user
from app.services.resource_access import ResourceAccessService
from app.services.api_publication import (
    APIPublicationError,
    sync_deployment_publication,
    publish_chat_api,
    publish_deployment,
    publish_workflow_version,
    unpublish_chat_api,
    unpublish_deployment,
    unpublish_workflow_version,
)

router = APIRouter(prefix="/api/platform/apis", tags=["platform_apis"])


class APIType(str, Enum):
    model = "model"
    orchestration = "orchestration"
    custom = "custom"


class APIMethod(str, Enum):
    get = "GET"
    post = "POST"
    put = "PUT"
    patch = "PATCH"
    delete = "DELETE"


class PlatformAPICreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=256)
    api_type: APIType = APIType.model
    algorithm_type: str = Field(default="", max_length=64)
    endpoint: str = Field(min_length=1, max_length=512)
    method: APIMethod = APIMethod.post
    version: str = Field(default="v1", min_length=1, max_length=32)
    description: str = Field(default="", max_length=10000)
    request_schema: dict[str, Any] = Field(default_factory=dict)
    response_schema: dict[str, Any] = Field(default_factory=dict)
    source_kind: APIType = APIType.custom
    source_id: Optional[uuid.UUID] = None
    is_public: bool = False

    @field_validator("endpoint")
    @classmethod
    def validate_endpoint(cls, value: str) -> str:
        if not value.startswith("/api/"):
            raise ValueError("endpoint must be an internal /api/ path")
        return value


class PlatformAPIItem(BaseModel):
    id: str
    name: str
    api_type: str
    algorithm_type: str = ""
    endpoint: str
    method: str
    version: str
    status: str
    source_kind: str
    source_id: Optional[str] = None
    description: str = ""
    request_schema: dict[str, Any] = Field(default_factory=dict)
    response_schema: dict[str, Any] = Field(default_factory=dict)
    total_calls: int = 0
    success_calls: int = 0
    failed_calls: int = 0
    is_public: bool = False
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    published_at: Optional[datetime] = None
    last_error: Optional[str] = None


class PlatformAPIUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Optional[str] = Field(default=None, min_length=1, max_length=256)
    status: Optional[str] = None
    description: Optional[str] = Field(default=None, max_length=10000)
    endpoint: Optional[str] = Field(default=None, max_length=512)
    is_public: Optional[bool] = None

    @field_validator("status")
    @classmethod
    def validate_status(cls, value: Optional[str]) -> Optional[str]:
        if value is not None and value not in {"published", "offline", "failed"}:
            raise ValueError("unsupported API status")
        return value

    @field_validator("endpoint")
    @classmethod
    def validate_update_endpoint(cls, value: Optional[str]) -> Optional[str]:
        if value is not None and not value.startswith("/api/"):
            raise ValueError("endpoint must be an internal /api/ path")
        return value


def _serialize_api(api: PlatformAPI) -> PlatformAPIItem:
    return PlatformAPIItem(
        id=str(api.id), name=api.name, api_type=api.api_type,
        algorithm_type=api.algorithm_type or "", endpoint=api.endpoint or "",
        method=api.method, version=api.version, status=api.status,
        source_kind=api.source_kind or api.api_type,
        source_id=str(api.source_id) if api.source_id else None,
        description=api.description or "", request_schema=api.request_schema or {},
        response_schema=api.response_schema or {}, total_calls=api.total_calls or 0,
        success_calls=api.success_calls or 0, failed_calls=api.failed_calls or 0,
        is_public=bool(api.is_public), created_at=api.created_at,
        updated_at=api.updated_at, published_at=api.published_at,
        last_error=api.last_error,
    )


@router.get("")
def list_apis(
    api_type: str = Query(None),
    status: str = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    q = db.query(PlatformAPI).filter(or_(
        PlatformAPI.owner_id == current_user.id,
        PlatformAPI.is_public.is_(True),
    ))
    if api_type:
        q = q.filter(PlatformAPI.api_type == api_type)
    if status:
        q = q.filter(PlatformAPI.status == status)
    apis = q.order_by(PlatformAPI.created_at.desc()).all()
    # 编排条目附带大屏资格（通用闭环模板原样七算子）；批量查版本快照避免 N+1 之外的开销
    from app.models.workflow_version import WorkflowVersion

    orchestration_versions = {
        str(a.source_id)
        for a in apis
        if (a.source_kind or a.api_type) == "orchestration" and a.source_id
    }
    snapshots = {}
    if orchestration_versions:
        rows = db.query(WorkflowVersion).filter(
            WorkflowVersion.id.in_([uuid.UUID(v) for v in orchestration_versions]),
        ).all()
        snapshots = {str(row.id): row.nodes_snapshot for row in rows}

    def _eligible(a):
        if (a.source_kind or a.api_type) != "orchestration":
            return False
        snapshot = snapshots.get(str(a.source_id)) if a.source_id else None
        return _showcase_eligible(snapshot)

    return {
        "items": [
            {
                "id": str(a.id),
                "name": a.name,
                "api_type": a.api_type,
                "algorithm_type": a.algorithm_type,
                "endpoint": a.endpoint,
                "method": a.method,
                "version": a.version,
                "status": a.status,
                "source_kind": a.source_kind or a.api_type,
                "source_id": str(a.source_id) if a.source_id else None,
                "description": a.description,
                "request_schema": a.request_schema,
                "response_schema": a.response_schema,
                "total_calls": a.total_calls,
                "success_calls": a.success_calls,
                "failed_calls": a.failed_calls,
                "showcase_eligible": _eligible(a),
                "is_public": a.is_public,
                "created_at": a.created_at.isoformat() if a.created_at else None,
            }
            for a in apis
        ],
        "total": len(apis),
    }


@router.post("", status_code=status.HTTP_201_CREATED, response_model=PlatformAPIItem)
def create_api(data: PlatformAPICreate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    if data.api_type != APIType.custom or data.source_kind != APIType.custom or data.source_id is not None:
        raise HTTPException(
            422,
            detail="model and orchestration APIs must be created from executable sources",
        )
    api = PlatformAPI(
        name=data.name, api_type=data.api_type.value,
        algorithm_type=data.algorithm_type, endpoint=data.endpoint,
        method=data.method.value, version=data.version,
        description=data.description, request_schema=data.request_schema,
        response_schema=data.response_schema, source_kind=data.source_kind.value,
        source_id=data.source_id,
        owner_id=current_user.id,
        is_public=data.is_public,
    )
    db.add(api)
    db.commit()
    db.refresh(api)
    return _serialize_api(api)


@router.put("/{api_id}", response_model=PlatformAPIItem)
def update_api(api_id: str, data: PlatformAPIUpdate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    api = ResourceAccessService().require_owned(
        db,
        PlatformAPI,
        api_id,
        current_user.id,
    )
    if api.source_id is not None or api.source_kind != "custom":
        raise HTTPException(409, detail="source-bound APIs are managed by their deployment lifecycle")
    changes = data.model_dump(exclude_unset=True)
    if "status" in changes:
        allowed = {
            "published": {"offline", "failed", "published"},
            "offline": {"published", "offline"},
            "failed": {"offline", "failed"},
        }
        if changes["status"] not in allowed.get(api.status, set()):
            raise HTTPException(422, detail="invalid API status transition")
    for key, value in changes.items():
        setattr(api, key, value)
    if changes.get("status") == "published":
        api.published_at = datetime.utcnow()
    db.commit()
    db.refresh(api)
    return _serialize_api(api)


@router.delete("/{api_id}")
def delete_api(api_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    api = ResourceAccessService().require_owned(
        db,
        PlatformAPI,
        api_id,
        current_user.id,
    )
    # Custom rows are user-created; orchestration rows are derived from
    # workflow versions and chat rows from knowledge bases — all three can be
    # recreated by re-publishing. Model rows follow the deployment lifecycle:
    # deleting one is allowed only while its deployment is not running (a
    # running deployment would just re-publish the row on its next sync).
    if api.source_kind == "model":
        deployment = None
        if api.source_id is not None:
            from app.models.model_registry import InferenceDeployment

            deployment = db.query(InferenceDeployment).filter(
                InferenceDeployment.id == api.source_id,
            ).first()
        if deployment is not None and deployment.desired_state == "running":
            raise HTTPException(
                409,
                detail={"code": "DEPLOYMENT_STILL_RUNNING",
                        "message": "该 API 由运行中的推理部署生成；请先在市场对该 API 执行「下线」（停止部署）后再删除"},
            )
    db.delete(api)
    db.commit()
    return {"status": "deleted"}


def _deployment_service(db):
    from app.config import settings as app_settings

    from app.models.model_registry import InferenceDeployment
    from app.services.inference_deployment import InferenceDeploymentService
    from app.services.inference_runtime_client import InferenceRuntimeClient

    secret = app_settings.resolved_inference_internal_secret
    if not app_settings.inference_runtime_url or secret is None:
        return None
    client = InferenceRuntimeClient(
        app_settings.inference_runtime_url,
        secret.get_secret_value(),
        load_timeout_seconds=app_settings.inference_load_timeout_seconds,
        predict_timeout_seconds=app_settings.inference_predict_timeout_seconds,
    )
    return InferenceDeploymentService(client, SessionLocal)


def _get_owned_api(api_id: str, current_user: User, db: Session) -> PlatformAPI:
    return ResourceAccessService().require_owned(
        db, PlatformAPI, api_id, current_user.id,
    )


@router.post("/{api_id}/online")
def online_api(
    api_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Bring a catalog API back online, by source kind:
    model → start the deployment; chat/orchestration → re-publish; custom →
    draft/offline → published."""
    api = _get_owned_api(api_id, current_user, db)
    kind = api.source_kind or api.api_type
    try:
        if kind == "model":
            _deployment_service(db).start(db, api.source_id)
            sync_deployment_publication(db, api.source_id, current_user.id, running=True)
        elif kind == "chat":
            publish_chat_api(db, api.source_id, current_user.id)
        elif kind == "orchestration":
            if api.workflow_id is None or not str(api.version or "").lstrip("v").isdigit():
                raise HTTPException(409, detail={"code": "ORPHANED_ORCHESTRATION_API",
                                                 "message": "该编排 API 的工作流版本已不存在，无法上线；请删除后重新发布"})
            publish_workflow_version(db, api.workflow_id, int(str(api.version).lstrip("v")), current_user.id)
        else:
            if api.status == "published":
                pass
            elif api.status in ("draft", "offline"):
                api.status = "published"
                db.commit()
            else:
                raise HTTPException(409, detail={"code": "INVALID_STATUS_TRANSITION",
                                                 "message": f"当前状态 {api.status} 不允许上线"})
    except HTTPException:
        raise
    except APIPublicationError as error:
        status_code = 404 if error.code.endswith("NOT_FOUND") else 403 if error.code.endswith("PERMISSION_DENIED") else 409
        raise HTTPException(status_code, detail={"code": error.code, "message": str(error)}) from error
    db.refresh(api)
    return _serialize_api(api)


@router.post("/{api_id}/offline")
def offline_api(
    api_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Take a catalog API offline, by source kind:
    model → stop the deployment; chat → unpublish; orchestration → unpublish;
    custom → published → offline."""
    api = _get_owned_api(api_id, current_user, db)
    kind = api.source_kind or api.api_type
    try:
        if kind == "model":
            _deployment_service(db).stop(db, api.source_id)
            sync_deployment_publication(db, api.source_id, current_user.id, running=False)
        elif kind == "chat":
            unpublish_chat_api(db, api.source_id, current_user.id)
        elif kind == "orchestration":
            if api.workflow_id is None:
                api.status = "offline"
                db.commit()
            else:
                unpublish_workflow_version(db, api.workflow_id, int(str(api.version).lstrip("v")), current_user.id)
        else:
            if api.status == "published":
                api.status = "offline"
                db.commit()
            elif api.status == "offline":
                pass
            else:
                raise HTTPException(409, detail={"code": "INVALID_STATUS_TRANSITION",
                                                 "message": f"当前状态 {api.status} 不允许下线"})
    except HTTPException:
        raise
    except APIPublicationError as error:
        status_code = 404 if error.code.endswith("NOT_FOUND") else 403 if error.code.endswith("PERMISSION_DENIED") else 409
        raise HTTPException(status_code, detail={"code": error.code, "message": str(error)}) from error
    db.refresh(api)
    return _serialize_api(api)


@router.get("/stats")
def api_stats(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    query = db.query(PlatformAPI).filter(or_(
        PlatformAPI.owner_id == current_user.id,
        PlatformAPI.is_public.is_(True),
    ))
    total = query.count()
    published = query.filter(PlatformAPI.status == "published").count()
    total_calls = query.with_entities(PlatformAPI.total_calls).all()
    return {
        "total_apis": total,
        "published": published,
        "offline": query.filter(PlatformAPI.status == "offline").count(),
        "failed": query.filter(PlatformAPI.status == "failed").count(),
        "total_calls": sum(c[0] or 0 for c in total_calls),
    }


@router.post("/publish/deployment/{deployment_id}", response_model=PlatformAPIItem, status_code=status.HTTP_201_CREATED)
def publish_deployment_api(
    deployment_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        return _serialize_api(publish_deployment(db, deployment_id, current_user.id))
    except APIPublicationError as error:
        status_code = 404 if error.code.endswith("NOT_FOUND") else 403 if error.code.endswith("PERMISSION_DENIED") else 409
        raise HTTPException(status_code, detail={"code": error.code, "message": str(error)}) from error


@router.post("/publish/deployment/{deployment_id}/offline", response_model=PlatformAPIItem)
def unpublish_deployment_api(
    deployment_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        return _serialize_api(unpublish_deployment(db, deployment_id, current_user.id))
    except APIPublicationError as error:
        raise HTTPException(404, detail={"code": error.code, "message": str(error)}) from error


@router.post("/publish/workflow/{workflow_id}/{version_number}", response_model=PlatformAPIItem, status_code=status.HTTP_201_CREATED)
def publish_workflow_api(
    workflow_id: str,
    version_number: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        return _serialize_api(publish_workflow_version(db, workflow_id, version_number, current_user.id))
    except APIPublicationError as error:
        status_code = 404 if error.code.endswith("NOT_FOUND") else 403 if error.code.endswith("PERMISSION_DENIED") else 409
        raise HTTPException(status_code, detail={"code": error.code, "message": str(error)}) from error


@router.post("/publish/workflow/{workflow_id}/{version_number}/offline", response_model=PlatformAPIItem)
def unpublish_workflow_api(
    workflow_id: str,
    version_number: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        return _serialize_api(unpublish_workflow_version(db, workflow_id, version_number, current_user.id))
    except APIPublicationError as error:
        raise HTTPException(404, detail={"code": error.code, "message": str(error)}) from error


class OrchestrationInvokeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    record: dict


@router.post("/orchestration/{version_id}/invoke")
def invoke_orchestration_api(    version_id: str,
    data: OrchestrationInvokeRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from datetime import datetime, timezone

    from app.engine.data_bus import DataBus
    from app.engine.dag_executor import DAGExecutor
    from app.models.workflow import Workflow
    from app.models.workflow_version import WorkflowVersion
    from app.services.artifact_service import build_artifact_service
    from app.services.project_access import ProjectAccessError, ProjectAccessService

    def _error(code: str, message: str, http_status: int):
        return HTTPException(http_status, detail={"code": code, "message": message})

    try:
        version_uuid = uuid.UUID(version_id)
    except (TypeError, ValueError, AttributeError) as error:
        raise _error("ORCHESTRATION_API_NOT_FOUND", "Orchestration API not found", 404) from error
    api = db.query(PlatformAPI).filter(
        PlatformAPI.source_kind == "orchestration",
        PlatformAPI.source_id == version_uuid,
    ).order_by(PlatformAPI.created_at.desc()).first()
    if api is None:
        raise _error("ORCHESTRATION_API_NOT_FOUND", "Orchestration API not found", 404)
    if api.status != "published":
        raise _error("ORCHESTRATION_API_OFFLINE", "该编排 API 当前处于下线状态", 409)
    version = db.query(WorkflowVersion).filter(WorkflowVersion.id == version_uuid).first()
    if version is None:
        raise _error("ORCHESTRATION_API_NOT_FOUND", "Bound workflow version no longer exists", 404)
    workflow = db.query(Workflow).filter(Workflow.id == version.workflow_id).first()
    if workflow is None:
        raise _error("ORCHESTRATION_API_NOT_FOUND", "Bound workflow no longer exists", 404)
    try:
        ProjectAccessService().require(db, workflow.project_id, current_user.id, "project.read")
    except ProjectAccessError as error:
        code = "ORCHESTRATION_API_NOT_FOUND" if error.hidden else "ORCHESTRATION_API_FORBIDDEN"
        raise _error(code, "Workflow is not accessible", 404 if error.hidden else 403) from error

    record = data.record
    if not record:
        raise _error("ORCHESTRATION_INVOKE_INVALID", "record must be a non-empty object", 422)

    run_id = f"invoke-{uuid.uuid4()}"
    executor = DAGExecutor(
        nodes=version.nodes_snapshot or [],
        edges=version.edges_snapshot or [],
        artifact_service=build_artifact_service(db),
        project_id=str(workflow.project_id),
        workflow_id=str(workflow.id),
        input_payload=record,
        operator_id=str(workflow.created_by) if workflow.created_by else None,
    )
    started = datetime.now(timezone.utc)
    try:
        results = executor.execute(run_id)
    except Exception as error:
        api.total_calls = (api.total_calls or 0) + 1
        api.failed_calls = (api.failed_calls or 0) + 1
        api.last_error = str(error)[:2000]
        db.commit()
        raise _error(
            "ORCHESTRATION_INVOKE_FAILED",
            f"工作流执行失败：{error}",
            422,
        ) from error

    # 拓扑序最后一个节点即输出节点；读回其数据总线产物。
    def _as_rows(node_results, port):
        path = node_results.get(port)
        if not path:
            return []
        payload = DataBus.load_data(path)
        if isinstance(payload, pd.DataFrame):
            payload = payload.to_dict(orient="records")
        return payload if isinstance(payload, list) else [payload]

    final_node_id = next(reversed(results))
    node_results = results[final_node_id] or {}
    output_port = next((p for p in node_results if p != "artifacts"), None)
    rows = _as_rows(node_results, output_port) if output_port else []
    branch = None
    if "true_branch" in node_results and "false_branch" in node_results:
        true_rows = _as_rows(node_results, "true_branch")
        false_rows = _as_rows(node_results, "false_branch")
        branch = "true" if true_rows else ("false" if false_rows else None)
        # Condition outputs split rows across two ports: surface the rows of
        # the branch the record actually took.
        rows = true_rows if branch == "true" else (false_rows if branch == "false" else rows)

    api.total_calls = (api.total_calls or 0) + 1
    api.success_calls = (api.success_calls or 0) + 1
    api.last_error = None

    # 实时大屏留痕：报错/告警计数、事件流、重训任务与换模引用（编排 API 专页数据源）
    nodes_snapshot = version.nodes_snapshot or []
    condition_node_id = next(
        (node.get("id") for node in nodes_snapshot if node.get("operator_id") == "condition"),
        None,
    )
    notify_node_id = next(
        (node.get("id") for node in nodes_snapshot if node.get("operator_id") == "notify_admins"),
        None,
    )
    swap_deployment_id = next(
        (
            (node.get("params") or {}).get("swap_deployment_id")
            for node in nodes_snapshot
            if node.get("operator_id") == "retrain_threshold"
        ),
        None,
    )
    # 报错行判定：条件分支节点 true 分支有输出即命中（输出节点的 branch 恒为 null）
    error_row_hit = False
    if condition_node_id and condition_node_id in results:
        condition_results = results[condition_node_id] or {}
        if "true_branch" in condition_results:
            error_row_hit = bool(_as_rows(condition_results, "true_branch"))
    alert_fired = bool(notify_node_id and results.get(notify_node_id))
    state = dict(api.showcase_state or {})
    events = list(state.get("events") or [])[-48:]
    now_iso = started.isoformat()
    if error_row_hit:
        api.error_calls = (api.error_calls or 0) + 1
        events.append({"id": str(uuid.uuid4()), "event_type": "error_row", "severity": "warning",
                       "message": f"报错行命中回流（累计第 {api.error_calls} 行）", "created_at": now_iso})
        if alert_fired:
            api.alert_calls = (api.alert_calls or 0) + 1
            events.append({"id": str(uuid.uuid4()), "event_type": "alert_triggered", "severity": "warning",
                           "message": "方案B报错告警：错误数据已回流", "created_at": now_iso})
    else:
        events.append({"id": str(uuid.uuid4()), "event_type": "row_predicted", "severity": "info",
                       "message": "正常预测", "created_at": now_iso})
    triggered = any(isinstance(r, dict) and r.get("triggered") for r in rows)
    if triggered:
        from app.models.training import TrainingJob

        retrain_job = (
            db.query(TrainingJob)
            .filter(
                TrainingJob.project_id == workflow.project_id,
                TrainingJob.name.like("编排闭环-自动建模-%"),
            )
            .order_by(TrainingJob.created_at.desc())
            .first()
        )
        if retrain_job is not None:
            state["last_retrain_job_id"] = str(retrain_job.id)
            events.append({"id": str(uuid.uuid4()), "event_type": "retrain_triggered",
                           "severity": "info",
                           "message": f"错误积累达阈值，自动建模已触发（{retrain_job.name}）",
                           "created_at": now_iso})
    if swap_deployment_id:
        state["swap_deployment_id"] = str(swap_deployment_id)
        from app.models.model_registry import InferenceDeployment

        deployment = db.query(InferenceDeployment).filter(
            InferenceDeployment.id == uuid.UUID(str(swap_deployment_id)),
        ).first()
        current_version = str(deployment.model_version_id) if deployment else None
        previous_version = state.get("last_model_version_id")
        if current_version and previous_version and current_version != previous_version:
            events.append({"id": str(uuid.uuid4()), "event_type": "model_swapped",
                           "severity": "info", "message": "推理模型已替换为重训最优版本",
                           "created_at": now_iso})
        if current_version:
            state["last_model_version_id"] = current_version
    state["events"] = events
    api.showcase_state = state
    db.commit()

    def _safe(value):
        import math

        if value is None or isinstance(value, (str, int, bool)):
            return value
        if isinstance(value, float):
            return value if math.isfinite(value) else None
        if isinstance(value, dict):
            return {str(k): _safe(v) for k, v in value.items()}
        if isinstance(value, (list, tuple)):
            return [_safe(v) for v in value]
        return str(value)

    return {
        "api_id": str(api.id),
        "workflow_version": api.version,
        "output_node": final_node_id,
        "branch": branch,
        "records": _safe(rows),
        "invoked_at": started.isoformat(),
    }


# 实时大屏仅面向"通用闭环服务模板"原样结构：七算子缺一不可、不得增减。
SHOWCASE_OPERATOR_SET = frozenset({
    "api_input",
    "load_model_artifact",
    "apply_model",
    "condition",
    "append_error_dataset",
    "notify_admins",
    "retrain_threshold",
})


def _showcase_eligible(nodes_snapshot) -> bool:
    operators = {
        (node.get("operator_id") or "")
        for node in (nodes_snapshot or [])
        if isinstance(node, dict)
    }
    return operators == SHOWCASE_OPERATOR_SET


def _threshold_rows(nodes_snapshot) -> int:
    for node in nodes_snapshot or []:
        if node.get("operator_id") == "retrain_threshold":
            value = (node.get("params") or {}).get("threshold_rows")
            try:
                return max(1, int(value))
            except (TypeError, ValueError):
                return 3
    return 3


@router.get("/orchestration/{version_id}/showcase-status")
def orchestration_showcase_status(
    version_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """编排 API 实时大屏数据源（字段与闭环任务 status 同构）。"""
    from app.models.model_registry import InferenceDeployment, ModelVersion
    from app.models.training import TrainingJob
    from app.models.workflow import Workflow
    from app.models.workflow_version import WorkflowVersion
    from app.services.project_access import ProjectAccessError, ProjectAccessService

    from datetime import datetime, timezone

    def utcnow():
        return datetime.now(timezone.utc)

    def _error(code: str, message: str, http_status: int):
        return HTTPException(http_status, detail={"code": code, "message": message})

    try:
        version_uuid = uuid.UUID(version_id)
    except (TypeError, ValueError, AttributeError) as error:
        raise _error("ORCHESTRATION_API_NOT_FOUND", "Orchestration API not found", 404) from error
    api = db.query(PlatformAPI).filter(
        PlatformAPI.source_kind == "orchestration",
        PlatformAPI.source_id == version_uuid,
    ).order_by(PlatformAPI.created_at.desc()).first()
    if api is None:
        raise _error("ORCHESTRATION_API_NOT_FOUND", "Orchestration API not found", 404)
    version = db.query(WorkflowVersion).filter(WorkflowVersion.id == version_uuid).first()
    if version is None:
        raise _error("ORCHESTRATION_API_NOT_FOUND", "Bound workflow version no longer exists", 404)
    workflow = db.query(Workflow).filter(Workflow.id == version.workflow_id).first()
    if workflow is None:
        raise _error("ORCHESTRATION_API_NOT_FOUND", "Bound workflow no longer exists", 404)
    try:
        ProjectAccessService().require(db, workflow.project_id, current_user.id, "project.read")
    except ProjectAccessError as error:
        code = "ORCHESTRATION_API_NOT_FOUND" if error.hidden else "ORCHESTRATION_API_FORBIDDEN"
        raise _error(code, "Workflow is not accessible", 404 if error.hidden else 403) from error
    if not _showcase_eligible(version.nodes_snapshot):
        raise _error(
            "SHOWCASE_NOT_ELIGIBLE",
            "仅支持未增减算子的通用闭环服务模板结构（七算子）",
            409,
        )

    state = dict(api.showcase_state or {})
    events = list(state.get("events") or [])[-50:]
    total = int(api.total_calls or 0)
    errors = int(api.error_calls or 0)

    # 惰性合成重训事件：重训任务的创建与 invoke 响应存在时序差，轮询侧兜底
    latest_retrain = db.query(TrainingJob).filter(
        TrainingJob.project_id == workflow.project_id,
        TrainingJob.name.like("编排闭环-自动建模-%"),
    ).order_by(TrainingJob.created_at.desc()).first()
    if latest_retrain is not None and str(latest_retrain.id) != state.get("last_retrain_job_id"):
        events.append({"id": str(uuid.uuid4()), "event_type": "retrain_triggered",
                       "severity": "info",
                       "message": f"错误积累达阈值，自动建模已触发（{latest_retrain.name}）",
                       "created_at": (latest_retrain.created_at or utcnow()).isoformat()})
        state["last_retrain_job_id"] = str(latest_retrain.id)
        api.showcase_state = state
        db.commit()

    retrain_status = "idle"
    retrain_job_id = state.get("last_retrain_job_id")
    retrain_job = None
    if retrain_job_id:
        try:
            retrain_job = db.query(TrainingJob).filter(
                TrainingJob.id == uuid.UUID(str(retrain_job_id)),
            ).first()
        except (TypeError, ValueError, AttributeError):
            retrain_job = None
    if retrain_job is not None:
        retrain_status = retrain_job.status if retrain_job.status in {
            "queued", "running", "completed", "failed", "cancelled",
        } else "running"

    model_score = None
    model_version = None
    deployment = None
    swap_deployment_id = state.get("swap_deployment_id")
    if swap_deployment_id:
        try:
            deployment = db.query(InferenceDeployment).filter(
                InferenceDeployment.id == uuid.UUID(str(swap_deployment_id)),
            ).first()
        except (TypeError, ValueError, AttributeError):
            deployment = None
    if deployment is not None and deployment.model_version_id:
        model_version_row = db.query(ModelVersion).filter(
            ModelVersion.id == deployment.model_version_id,
        ).first()
        if model_version_row is not None:
            model_version = f"v{model_version_row.version_number}"
            if model_version_row.registration_task_id:
                registration_job = db.query(TrainingJob).filter(
                    TrainingJob.id == model_version_row.registration_task_id,
                ).first()
                score = (registration_job.metrics or {}).get("best_score") if registration_job else None
                if isinstance(score, (int, float)) and 0 < score <= 1:
                    model_score = round(float(score), 4)

    return {
        "total_count": total,
        "error_count": errors,
        "alert_count": int(api.alert_calls or 0),
        "model_score": model_score,
        "retrain_status": retrain_status,
        "retrain_job_id": retrain_job_id,
        "retrain_threshold_rows": _threshold_rows(version.nodes_snapshot),
        "model_version": model_version,
        "events": events,
    }


class ChatInvokeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message: str = Field(min_length=1, max_length=8000)
    top_k: int = Field(default=4, ge=1, le=10)
    system_prompt: str | None = Field(default=None, max_length=4000)
    temperature: float | None = Field(default=None, ge=0, le=1)


@router.post("/publish/chat/{kb_id}", response_model=PlatformAPIItem, status_code=status.HTTP_201_CREATED)
def publish_chat_kb_api(
    kb_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        return _serialize_api(publish_chat_api(db, kb_id, current_user.id))
    except APIPublicationError as error:
        status_code = 404 if error.code.endswith("NOT_FOUND") else 403 if error.code.endswith("PERMISSION_DENIED") else 409
        raise HTTPException(status_code, detail={"code": error.code, "message": str(error)}) from error


@router.post("/publish/chat/{kb_id}/offline", response_model=PlatformAPIItem)
def unpublish_chat_kb_api(
    kb_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        return _serialize_api(unpublish_chat_api(db, kb_id, current_user.id))
    except APIPublicationError as error:
        raise HTTPException(404, detail={"code": error.code, "message": str(error)}) from error


@router.post("/chat/{kb_id}/invoke")
def invoke_chat_api(
    kb_id: str,
    data: ChatInvokeRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Remote RAG chat invocation over a published chat API.

    Error semantics are HTTP status codes (remote integration surface, unlike
    the interactive /api/chat): 404 unknown/unauthorized, 409 offline, 422
    invalid payload, 503 LLM unconfigured, 502 LLM call failed. LLM credentials
    always come from server settings - callers cannot pass keys or models.
    """
    from datetime import datetime, timezone

    from app.config import settings
    from app.models.knowledge import KnowledgeBase
    from app.services.knowledge_retrieval import (
        RAG_SYSTEM_APPENDIX,
        build_rag_context,
        retrieve_chunks,
    )

    def _error(code: str, message: str, http_status: int):
        return HTTPException(http_status, detail={"code": code, "message": message})

    try:
        kb_uuid = uuid.UUID(kb_id)
    except (TypeError, ValueError, AttributeError) as error:
        raise _error("CHAT_API_NOT_FOUND", "Chat API not found", 404) from error

    api = db.query(PlatformAPI).filter(
        PlatformAPI.source_kind == "chat",
        PlatformAPI.source_id == kb_uuid,
    ).order_by(PlatformAPI.created_at.desc()).first()
    if api is None:
        raise _error("CHAT_API_NOT_FOUND", "Chat API not found", 404)
    if api.status != "published":
        raise _error("CHAT_API_OFFLINE", "该对话 API 当前处于下线状态", 409)

    kb = db.query(KnowledgeBase).filter(KnowledgeBase.id == kb_uuid).first()
    if kb is None or kb.owner_id != current_user.id:
        raise _error("CHAT_API_NOT_FOUND", "Chat API not found", 404)

    message = data.message.strip()
    if not message:
        raise _error("CHAT_INVOKE_INVALID", "message must be a non-empty string", 422)

    def _fail(code: str, http_status: int, error_text: str):
        api.total_calls = (api.total_calls or 0) + 1
        api.failed_calls = (api.failed_calls or 0) + 1
        api.last_error = error_text[:2000]
        db.commit()
        return _error(code, error_text, http_status)

    if not settings.llm_api_key:
        raise _fail("CHAT_LLM_NOT_CONFIGURED", 503, "LLM_API_KEY is not configured on the server")

    started = datetime.now(timezone.utc)
    try:
        results = retrieve_chunks(db, kb, message, top_k=data.top_k)
    except Exception:
        results = []
    context, sources = build_rag_context(results)

    system_prompt = data.system_prompt or "You are a helpful AI assistant for welding manufacturing."
    system_content = f"{system_prompt}\n\n{RAG_SYSTEM_APPENDIX}" if context else system_prompt
    user_content = f"参考资料：\n\n{context}\n\n问题：{message}" if context else message

    import requests
    try:
        resp = requests.post(
            settings.llm_api_url,
            headers={"Authorization": f"Bearer {settings.llm_api_key}", "Content-Type": "application/json"},
            json={
                "model": settings.llm_model,
                "messages": [
                    {"role": "system", "content": system_content},
                    {"role": "user", "content": user_content},
                ],
                "temperature": data.temperature if data.temperature is not None else 0.7,
                "max_tokens": 2000,
            },
            timeout=30,
        )
        resp.raise_for_status()
        payload = resp.json()
        reply = payload.get("choices", [{}])[0].get("message", {}).get("content", "")
        usage = payload.get("usage", {})
    except Exception as error:
        raise _fail("CHAT_LLM_CALL_FAILED", 502, f"LLM call failed: {error}") from error

    api.total_calls = (api.total_calls or 0) + 1
    api.success_calls = (api.success_calls or 0) + 1
    api.last_error = None
    db.commit()

    return {
        "api_id": str(api.id),
        "reply": reply,
        "sources": sources,
        "kb": {"id": str(kb.id), "name": kb.name},
        "kb_warning": None if sources else "知识库中没有检索到相关内容",
        "usage": {
            "prompt_tokens": usage.get("prompt_tokens", 0),
            "completion_tokens": usage.get("completion_tokens", 0),
        },
        "invoked_at": started.isoformat(),
    }
