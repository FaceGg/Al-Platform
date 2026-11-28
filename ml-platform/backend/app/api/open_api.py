"""Open read-only API for QMS/MES (补齐路线第一批 F5a, B1-13).

技术方案 §9A（D45–D47）：
- 鉴权 = `X-Api-Key`（项目级 Key，scope=project.read）；Key 的 project_id 即权限边界，
  与路径项目不匹配 → 401；无用户上下文；
- 三个只读资源（路线 C19 资源重定）：推理任务（B1-16 明细查询口径）、检验结果
  （人工确认的处置结论）、反馈（demo_loop 的 confirmed_fault / false_alarm 标记汇总）；
- 只注册 GET——写动词天然 405；
- 分页 ≤100/页，演示通道 / 演示预警默认排除；
- Key 管理（创建/列表/轮换/吊销）走用户 JWT + quality.manage（D47）。
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.orm import Session, sessionmaker

from app.api.auth import get_current_user
from app.api.project_security import require_project_access
from app.config import settings as app_settings
from app.database import get_db
from app.models.demo_loop import DemoLoopConfig
from app.models.inference_result import InferenceResult
from app.models.model_registry import InferenceApiKey
from app.models.project import Project
from app.models.quality_alerts import QualityAlert
from app.models.user import User
from app.services.audit import AuditIntent, AuditService
from app.services.inference_api_keys import (
    InferenceApiKeyError,
    InferenceApiKeyService,
)
from app.services.project_access import ProjectAccess

logger = logging.getLogger(__name__)

router = APIRouter(tags=["open-api"])

# 写端点审计登记（横向合同 §6-4；第三轮复审 2026-11-28 补齐）。
PROJECT_WRITE_ACTIONS = {
    "POST /api/projects/{project_id}/open-api-keys": "open_api_key.create",
    "POST /api/projects/{project_id}/open-api-keys/{key_id}/rotate": "open_api_key.rotate",
    "POST /api/projects/{project_id}/open-api-keys/{key_id}/revoke": "open_api_key.revoke",
    "POST /api/projects/{project_id}/ingest/publish": "ingest.publish",
}

OPEN_READ_SCOPE = "project.read"


def _audit_service(db: Session) -> AuditService:
    return AuditService(sessionmaker(bind=db.get_bind()))


# ----------------------------------------------------------------------
# 开放侧鉴权（D45）
# ----------------------------------------------------------------------

def require_open_api_key(
    db: Session,
    project_id: UUID,
    x_api_key: str | None,
    *,
    scope: str = OPEN_READ_SCOPE,
):
    """API Key 鉴权：无用户上下文；Key 的项目归属即权限边界。失败统一 401。"""
    if not x_api_key:
        raise HTTPException(401, {"code": "OPEN_API_KEY_REQUIRED", "message": "缺少 X-Api-Key 请求头"})
    try:
        record = InferenceApiKeyService().verify(
            db, x_api_key, scope=scope, touch_last_used=False,
        )
    except InferenceApiKeyError as error:
        raise HTTPException(401, {"code": error.code, "message": "API Key 无效"}) from None
    if record.project_id is None or str(record.project_id) != str(project_id):
        # 部署级 Key 或别的项目的 Key：同一措辞不泄露存在性
        raise HTTPException(401, {"code": "OPEN_API_KEY_INVALID", "message": "API Key 无效"})
    return record


# ----------------------------------------------------------------------
# 三个只读资源（D46）
# ----------------------------------------------------------------------

def _paged(items, total, page: int, page_size: int) -> dict:
    return {"items": items, "total": total, "page": page, "page_size": page_size}


@router.get("/api/v1/open/projects/{project_id}/inference-results")
def open_inference_results(
    project_id: UUID,
    sample_key: str | None = None,
    batch_no: str | None = None,
    occurred_from: str | None = None,
    occurred_to: str | None = None,
    page: int = 1,
    page_size: int = 50,
    db: Session = Depends(get_db),
    x_api_key: str | None = Header(default=None),
):
    """推理任务（B1-16 明细，演示通道排除；路线 C19 资源定义）。"""
    require_open_api_key(db, project_id, x_api_key)
    query = db.query(InferenceResult).filter(
        InferenceResult.project_id == project_id,
        InferenceResult.channel != "demo",
    )
    if sample_key:
        query = query.filter(InferenceResult.sample_key == sample_key)
    if batch_no:
        query = query.filter(InferenceResult.batch_no == batch_no)
    if occurred_from:
        query = query.filter(InferenceResult.occurred_at >= _time(occurred_from))
    if occurred_to:
        query = query.filter(InferenceResult.occurred_at <= _time(occurred_to))
    total = query.count()
    page = max(1, page)
    page_size = min(max(1, page_size), 100)
    rows = (
        query.order_by(InferenceResult.occurred_at.desc(), InferenceResult.id.asc())
        .offset((page - 1) * page_size).limit(page_size).all()
    )
    return _paged([
        {
            "id": str(row.id), "sample_key": row.sample_key, "batch_no": row.batch_no,
            "shift": row.shift, "product_code": row.product_code,
            "predicted_label": row.predicted_label, "predicted_value": row.predicted_value,
            "probability": row.probability, "anomaly_score": row.anomaly_score,
            "is_anomaly": row.is_anomaly, "occurred_at": _iso(row.occurred_at),
        }
        for row in rows
    ], total, page, page_size)


def _time(value: str) -> datetime:
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        raise HTTPException(422, {"code": "TIME_INVALID", "message": "时间须为 ISO 格式"}) from None


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


@router.get("/api/v1/open/projects/{project_id}/inspection-results")
def open_inspection_results(
    project_id: UUID,
    scene_id: str | None = None,
    station_id: str | None = None,
    page: int = 1,
    page_size: int = 50,
    db: Session = Depends(get_db),
    x_api_key: str | None = Header(default=None),
):
    """检验结果（人工确认的结论：confirmed_issue 处置单；路线 C19 资源定义）。"""
    require_open_api_key(db, project_id, x_api_key)
    query = db.query(QualityAlert).filter(
        QualityAlert.project_id == project_id,
        QualityAlert.status == "closed",
        QualityAlert.resolution == "confirmed_issue",
        # 合同 §6-9：演示数据不进任何对外视图（三批复审：演示预警曾随本端点外泄，
        # 运行验证坐实后修复——docstring 所称「演示预警默认排除」自此才有实现）
        QualityAlert.is_demo.is_(False),
    )
    if scene_id:
        query = query.filter(QualityAlert.scene_id == _uuid(scene_id))
    if station_id:
        query = query.filter(QualityAlert.station_id == _uuid(station_id))
    total = query.count()
    page = max(1, page)
    page_size = min(max(1, page_size), 100)
    rows = (
        query.order_by(QualityAlert.closed_at.desc(), QualityAlert.id.asc())
        .offset((page - 1) * page_size).limit(page_size).all()
    )
    return _paged([
        {
            "id": str(row.id), "title": row.title, "sample_key": row.sample_key,
            "batch_no": row.batch_no, "source_type": row.source_type,
            "occurrence_count": int(row.occurrence_count or 1),
            "closed_at": _iso(row.closed_at),
            "disposition": (row.evidence or {}).get("disposition") or None,
        }
        for row in rows
    ], total, page, page_size)


def _uuid(value: str) -> UUID:
    import uuid as uuid_module

    try:
        return uuid_module.UUID(str(value))
    except (TypeError, ValueError, AttributeError):
        raise HTTPException(422, {"code": "ID_INVALID", "message": "ID 格式无效"}) from None


@router.get("/api/v1/open/projects/{project_id}/feedback")
def open_feedback(
    project_id: UUID,
    db: Session = Depends(get_db),
    x_api_key: str | None = Header(default=None),
):
    """反馈（确认故障 / 误报标记汇总；路线 C19 资源定义：「反馈」已有回流样本标记）。"""
    require_open_api_key(db, project_id, x_api_key)
    items = []
    for config in (
        db.query(DemoLoopConfig)
        .filter(
            DemoLoopConfig.project_id == project_id,
            DemoLoopConfig.feedback_marks.isnot(None),
        )
        .order_by(DemoLoopConfig.id.asc())
        .all()
    ):
        marks = config.feedback_marks or {}
        confirmed = false_alarm = 0
        rows = []
        for artifact_id, by_row in sorted(marks.items()):
            for row_index, mark in sorted(by_row.items(), key=lambda item: int(item[0])):
                if mark == "confirmed_fault":
                    confirmed += 1
                elif mark == "false_alarm":
                    false_alarm += 1
                rows.append({
                    "artifact_id": str(artifact_id), "row_index": int(row_index),
                    "mark": str(mark),
                })
        items.append({
            "loop_id": str(config.id), "loop_name": config.name,
            "confirmed_fault": confirmed, "false_alarm": false_alarm,
            "rows": rows[:500], "truncated": len(rows) > 500,
        })
    return {"items": items, "total": len(items)}


# ----------------------------------------------------------------------
# Key 管理（用户 JWT + quality.manage，D47）
# ----------------------------------------------------------------------

class OpenKeyCreate(BaseModel):
    scopes: list[str] = Field(default_factory=lambda: [OPEN_READ_SCOPE])
    expires_at: str | None = None

    def normalized(self) -> tuple[list[str], datetime | None]:
        scopes = [scope.strip() for scope in self.scopes if scope.strip()]
        for scope in scopes:
            if scope != OPEN_READ_SCOPE:
                raise HTTPException(422, {
                    "code": "OPEN_KEY_SCOPE_INVALID",
                    "message": f"项目级 Key 只支持 {OPEN_READ_SCOPE} scope",
                })
        if not scopes:
            scopes = [OPEN_READ_SCOPE]
        expires_at = None
        if self.expires_at:
            try:
                expires_at = datetime.fromisoformat(self.expires_at)
            except ValueError:
                raise HTTPException(422, {"code": "TIME_INVALID", "message": "过期时间须为 ISO 格式"}) from None
        return scopes, expires_at


def _key_view(record: InferenceApiKey) -> dict:
    return {
        "id": str(record.id), "prefix": record.prefix, "scopes": list(record.scopes or []),
        "expires_at": _iso(record.expires_at), "revoked_at": _iso(record.revoked_at),
        "grace_until": _iso(record.grace_until),
        "last_used_at": _iso(record.last_used_at),
        "created_at": _iso(record.created_at),
    }


@router.post("/api/projects/{project_id}/open-api-keys")
def create_open_key(
    project_id: UUID,
    request: Request,
    data: OpenKeyCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    access: ProjectAccess = require_project_access(
        db, project_id, current_user.id, "quality.manage",
    )
    if db.get(Project, project_id) is None:
        raise HTTPException(404, {"code": "PROJECT_NOT_FOUND"})
    scopes, expires_at = data.normalized()
    try:
        created = InferenceApiKeyService().create_project_key(
            db, project_id, current_user.id, scopes, expires_at,
        )
    except InferenceApiKeyError as error:
        db.rollback()
        raise HTTPException(422, {"code": error.code}) from None
    with _audit_service(db).project_action(
        db, request=request, actor=current_user, access=access,
        permission="quality.manage",
        intent=AuditIntent(
            project_id=project_id, action="open_api_key.create",
            resource_type="inference_api_key", resource_id=str(created.record.id),
            changes={"prefix": created.record.prefix, "scopes": scopes},
        ),
        allowed_changes={"prefix", "scopes"},
    ):
        db.commit()
    return {**_key_view(created.record), "plaintext": created.plaintext}


@router.get("/api/projects/{project_id}/open-api-keys")
def list_open_keys(
    project_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    require_project_access(db, project_id, current_user.id, "quality.manage")
    keys = InferenceApiKeyService().list_for_project(db, project_id)
    return {"items": [_key_view(record) for record in keys], "total": len(keys)}


@router.post("/api/projects/{project_id}/open-api-keys/{key_id}/rotate")
def rotate_open_key(
    project_id: UUID,
    key_id: str,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """轮换：旧 Key 进宽限期（api_key_rotation_grace_hours，默认 24h）后失效。"""
    access: ProjectAccess = require_project_access(
        db, project_id, current_user.id, "quality.manage",
    )
    record = db.get(InferenceApiKey, _uuid(key_id))
    if record is None or record.project_id != project_id:
        raise HTTPException(404, {"code": "OPEN_API_KEY_NOT_FOUND"})
    try:
        created = InferenceApiKeyService().rotate(db, key_id, current_user.id)
    except InferenceApiKeyError as error:
        db.rollback()
        raise HTTPException(422, {"code": error.code}) from None
    with _audit_service(db).project_action(
        db, request=request, actor=current_user, access=access,
        permission="quality.manage",
        intent=AuditIntent(
            project_id=project_id, action="open_api_key.rotate",
            resource_type="inference_api_key", resource_id=str(record.id),
            changes={"new_prefix": created.record.prefix,
                     "grace_until": record.grace_until.isoformat() if record.grace_until else None},
        ),
        allowed_changes={"new_prefix", "grace_until"},
    ):
        db.commit()
    return {**_key_view(created.record), "plaintext": created.plaintext,
            "previous_grace_until": _iso(record.grace_until)}


@router.post("/api/projects/{project_id}/open-api-keys/{key_id}/revoke")
def revoke_open_key(
    project_id: UUID,
    key_id: str,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    access: ProjectAccess = require_project_access(
        db, project_id, current_user.id, "quality.manage",
    )
    record = db.get(InferenceApiKey, _uuid(key_id))
    if record is None or record.project_id != project_id:
        raise HTTPException(404, {"code": "OPEN_API_KEY_NOT_FOUND"})
    revoked = InferenceApiKeyService().revoke(db, key_id, current_user.id)
    with _audit_service(db).project_action(
        db, request=request, actor=current_user, access=access,
        permission="quality.manage",
        intent=AuditIntent(
            project_id=project_id, action="open_api_key.revoke",
            resource_type="inference_api_key", resource_id=str(record.id),
            changes={"prefix": record.prefix},
        ),
        allowed_changes={"prefix"},
    ):
        db.commit()
    return _key_view(revoked)


# ----------------------------------------------------------------------
# B1-07：接入通道（手动发布 = 无 Kafka 环境的等价路径；页脚状态 = 诚实设计⑤）
# ----------------------------------------------------------------------

class IngestPublishRequest(BaseModel):
    source: str = Field(default="manual", max_length=64)
    events: list[dict] = Field(min_length=1, max_length=1000)


@router.post("/api/projects/{project_id}/ingest/publish")
def ingest_publish(
    project_id: UUID,
    request: Request,
    data: IngestPublishRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """手动发布一批接入事件（与 Kafka 消费走同一契约校验与幂等落库）。"""
    access: ProjectAccess = require_project_access(
        db, project_id, current_user.id, "quality.manage",
    )
    from app.services.ingest import ingest_batch

    with _audit_service(db).project_action(
        db, request=request, actor=current_user, access=access,
        permission="quality.manage",
        intent=AuditIntent(
            project_id=project_id, action="ingest.publish",
            resource_type="ingest_event", resource_id=None,
            changes={"source": data.source, "count": len(data.events)},
        ),
        allowed_changes={"source", "count"},
    ):
        summary = ingest_batch(db, project_id=project_id, source=data.source, events=data.events)
        db.commit()
    return summary


@router.get("/api/platform/ingest-status")
def ingest_status(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """全站页脚的实时链路状态（诚实设计⑤变体，D52）。

    登录即可见（页脚在登录后的主界面）：匿名可读会向未认证方暴露链路启用状态
    与心跳时间（三批复审：曾实测匿名 200）。
    """
    from app.services.ingest import ingest_status as compute_status

    return compute_status(db)
