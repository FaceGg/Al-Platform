"""Quality monitoring API (补齐路线第一批 F3, B1-03/04/05).

技术方案 §9B：驾驶舱、趋势帕累托、实时监控三页的读接口全部经
services/quality_aggregates 的同一组函数取数（D27）；读 = project.read，
词表维护 = quality.manage；实时页的两个入口（确认收到 / 呼叫质量人员）=
quality.alert_handle（D30）。
"""
from __future__ import annotations

import json
import logging
import time
import uuid
from datetime import datetime, timedelta
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.orm import Session, sessionmaker

from app.api.auth import get_current_user
from app.api.project_security import require_project_access
from app.database import SessionLocal, get_db
from app.models.demo_loop import DemoLoopConfig
from app.models.notifications import InAppNotification
from app.models.project import Project
from app.models.quality_alerts import QualityAlert, QualityAlertEvent
from app.models.quality_domain import QualityScene, QualityStation
from app.models.user import User
from app.schemas.quality_alerts import parse_uuid
from app.services import quality_aggregates as agg
from app.services import quality_alerts as alert_service
from app.services.audit import AuditIntent, AuditService
from app.services.closed_loop_actions import notify_project_admins
from app.services.project_access import ProjectAccess, ProjectAccessService

logger = logging.getLogger(__name__)

router = APIRouter(tags=["quality-monitor"])

# SSE：轮询周期 2 秒（满足「新事件 5 秒内上屏」），每 15 秒发一个心跳注释帧
STREAM_POLL_SECONDS = 2.0
STREAM_HEARTBEAT_SECONDS = 15.0
STREAM_BATCH_LIMIT = 200


def _audit_service(db: Session) -> AuditService:
    return AuditService(sessionmaker(bind=db.get_bind()))


def _scope(factory, workshop, production_line, station_id, scene_id) -> agg.MonitorScope:
    return agg.MonitorScope(
        factory=factory or None, workshop=workshop or None,
        production_line=production_line or None,
        station_id=parse_uuid(station_id, "STATION_ID_INVALID") if station_id else None,
        scene_id=parse_uuid(scene_id, "SCENE_ID_INVALID") if scene_id else None,
    )


def _window(days: int, now: datetime) -> tuple[datetime, datetime]:
    """近 N 天 = 今天与前 N-1 个自然日。"""
    since = (now - timedelta(days=days - 1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return since, now + timedelta(seconds=1)


def _window_payload(since: datetime, until: datetime, days: int) -> dict:
    return {"days": days, "since": since.isoformat(), "until": until.isoformat()}


def dashboard_payload(
    db: Session, project_id, scope: agg.MonitorScope, *, days: int, now: datetime,
) -> dict:
    """驾驶舱的全部读数：一次取齐，供页面与推送快照共用。"""
    since, until = _window(days, now)
    production = agg.production_totals(db, project_id, scope, since=since, until=until)
    alerts = agg.alert_kpis(db, project_id, scope, since=since, until=until)
    return {
        "scope": scope.as_dict(),
        "window": _window_payload(since, until, days),
        "production": production,
        "alerts": alerts,
        "disposition_ops": agg.disposition_ops(
            db, project_id, scope, since=since, until=until, pieces=production["total"],
        ),
        "trend": agg.trend_view(db, project_id, scope, since=since, until=until),
        "recent": agg.recent_alerts(db, project_id, scope),
        "station_ranking": agg.station_ranking(db, project_id, scope, since=since, until=until),
        "line_status": agg.line_status(db, project_id, scope, now=now),
        "stale": agg.stale_state(db, project_id, scope, now=now),
        "generated_at": now.isoformat(),
    }


@router.get("/api/projects/{project_id}/quality-monitor/scope-options")
def scope_options(
    project_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    require_project_access(db, project_id, current_user.id, "project.read")
    return agg.scope_options(db, project_id)


@router.get("/api/projects/{project_id}/quality-monitor/dashboard")
def dashboard(
    project_id: UUID,
    factory: str | None = None,
    workshop: str | None = None,
    production_line: str | None = None,
    station_id: str | None = None,
    scene_id: str | None = None,
    days: int = 7,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    require_project_access(db, project_id, current_user.id, "project.read")
    if not 1 <= days <= 90:
        raise HTTPException(422, {"code": "DAYS_OUT_OF_RANGE", "message": "天数须在 1–90 之间"})
    return dashboard_payload(
        db, project_id, _scope(factory, workshop, production_line, station_id, scene_id),
        days=days, now=datetime.utcnow(),
    )


@router.get("/api/projects/{project_id}/quality-monitor/trends")
def trends(
    project_id: UUID,
    factory: str | None = None,
    workshop: str | None = None,
    production_line: str | None = None,
    station_id: str | None = None,
    scene_id: str | None = None,
    days: int = 7,
    dimension: str = "defect",
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    require_project_access(db, project_id, current_user.id, "project.read")
    if days not in (7, 30, 90):
        raise HTTPException(422, {"code": "DAYS_INVALID", "message": "时间窗只支持 7 / 30 / 90 天"})
    if dimension not in agg.PARETO_DIMENSIONS:
        raise HTTPException(422, {"code": "PARETO_DIMENSION_INVALID"})
    scope = _scope(factory, workshop, production_line, station_id, scene_id)
    now = datetime.utcnow()
    since, until = _window(days, now)
    vocabulary = agg.load_project_option(db, agg.OPTION_NG_VOCABULARY, project_id, {})
    return {
        "scope": scope.as_dict(),
        "window": _window_payload(since, until, days),
        "trend": agg.trend_view(db, project_id, scope, since=since, until=until),
        "pareto": agg.pareto(
            db, project_id, scope, since=since, until=until,
            dimension=dimension, vocabulary=vocabulary,
        ),
        "ng_vocabulary": vocabulary,
        "generated_at": now.isoformat(),
    }


class NgVocabularyUpdate(BaseModel):
    """NG 词表：{预测标签: 缺陷类别}。与质量报告（B3-08）共用同一份。"""

    vocabulary: dict[str, str] = Field(default_factory=dict)


@router.put("/api/projects/{project_id}/quality-monitor/ng-vocabulary")
def update_ng_vocabulary(
    project_id: UUID,
    request: Request,
    data: NgVocabularyUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    access: ProjectAccess = require_project_access(
        db, project_id, current_user.id, "quality.manage",
    )
    vocabulary: dict[str, str] = {}
    for label, category in data.vocabulary.items():
        label = str(label).strip()
        if not label or len(label) > 128:
            raise HTTPException(422, {"code": "NG_LABEL_INVALID", "message": "预测标签须为 1–128 个字符"})
        category = str(category or "").strip()
        if len(category) > 64:
            raise HTTPException(422, {"code": "NG_CATEGORY_INVALID", "message": "缺陷类别最多 64 个字符"})
        # 类别留空 = 该标签按「未归类」处理
        vocabulary[label] = category
    if len(vocabulary) > 200:
        raise HTTPException(422, {"code": "NG_VOCABULARY_TOO_LARGE", "message": "词表最多 200 条"})
    with _audit_service(db).project_action(
        db, request=request, actor=current_user, access=access,
        permission="quality.manage",
        intent=AuditIntent(
            project_id=project_id, action="quality.ng_vocabulary.update",
            resource_type="quality_ng_vocabulary", resource_id=str(project_id),
            changes={"entries": len(vocabulary)},
        ),
        allowed_changes={"entries"},
    ):
        agg.store_project_option(db, agg.OPTION_NG_VOCABULARY, project_id, vocabulary)
    return {"vocabulary": vocabulary}


# ----------------------------------------------------------------------
# 实时生产监控（B1-05）
# ----------------------------------------------------------------------

@router.get("/api/projects/{project_id}/quality-monitor/stations")
def stations(
    project_id: UUID,
    factory: str | None = None,
    workshop: str | None = None,
    production_line: str | None = None,
    station_id: str | None = None,
    scene_id: str | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """当前班次、工位卡与产线 / 工位 / 设备三级树。"""
    require_project_access(db, project_id, current_user.id, "project.read")
    scope = _scope(factory, workshop, production_line, station_id, scene_id)
    now = datetime.utcnow()
    schedule = agg.load_project_option(db, agg.OPTION_SHIFT_SCHEDULE, project_id, None)
    shift_start, shift_label = agg.current_shift_start(now, schedule)
    return {
        "scope": scope.as_dict(),
        "now": now.isoformat(),
        "shift": {"label": shift_label, "start": shift_start.isoformat()},
        "cards": agg.station_cards(db, project_id, scope, now=now, shift_start=shift_start),
        "tree": agg.production_tree(db, project_id, scope, now=now),
        "stale": agg.stale_state(db, project_id, scope, now=now),
    }


def _sse(payload: dict) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False, default=str)}\n\n"


def _scoped_event_query(db: Session, project_id, scope: agg.MonitorScope):
    return (
        db.query(
            QualityAlertEvent.id, QualityAlertEvent.alert_id, QualityAlertEvent.action,
            QualityAlertEvent.from_status, QualityAlertEvent.to_status, QualityAlertEvent.note,
            QualityAlertEvent.created_at,
            QualityAlert.title, QualityAlert.severity, QualityAlert.status,
            QualityAlert.station_id,
        )
        .join(QualityAlert, QualityAlert.id == QualityAlertEvent.alert_id)
        .outerjoin(QualityStation, QualityStation.id == QualityAlert.station_id)
        .filter(
            QualityAlert.project_id == project_id,
            QualityAlert.is_demo.is_(False),
            *agg.alert_scope_filters(scope),
        )
    )


def _events_since(db: Session, project_id, scope, cursor, skip_ids: set, limit: int):
    """自游标以来的预警轨迹事件。

    游标是事件的 created_at。同一时刻可能有多条事件（不同预警），所以用
    「>= 游标」取数，再用上一批已发过的 id 集合把边界上的旧事件剔除。
    """
    query = _scoped_event_query(db, project_id, scope)
    if cursor is not None:
        query = query.filter(QualityAlertEvent.created_at >= cursor)
    rows = query.order_by(
        QualityAlertEvent.created_at.asc(), QualityAlertEvent.id.asc(),
    ).limit(limit).all()
    events: list[dict] = []
    boundary: set = set()
    for row in rows:
        if row.id in skip_ids:
            continue
        cursor = row.created_at
        boundary.add(row.id)
        events.append({
            "event_id": str(row.id), "alert_id": str(row.alert_id), "action": row.action,
            "from_status": row.from_status, "to_status": row.to_status, "note": row.note,
            "created_at": row.created_at.isoformat() if row.created_at else None,
            "title": row.title, "severity": row.severity, "status": row.status,
            "station_id": str(row.station_id) if row.station_id else None,
        })
    return events, cursor, boundary


def _stream_counts(db: Session, project_id, scope: agg.MonitorScope) -> dict:
    base = agg.scoped_alerts(db, project_id, scope).filter(QualityAlert.status.in_(agg.OPEN_STATUSES))
    open_count = base.with_entities(func.count(QualityAlert.id)).scalar()
    high_count = base.filter(QualityAlert.severity.in_(agg.HIGH_SEVERITIES)).with_entities(
        func.count(QualityAlert.id),
    ).scalar()
    return {"open": int(open_count), "high_risk": int(high_count)}


def monitor_event_stream(
    project_id, scope: agg.MonitorScope, *, session_factory=None,
    poll_seconds: float = STREAM_POLL_SECONDS,
    heartbeat_seconds: float = STREAM_HEARTBEAT_SECONDS,
    max_ticks: int | None = None, sleep=time.sleep,
):
    """SSE 事件流（D29）：连接即发快照，随后每个轮询周期推送新增的预警轨迹事件。

    每个周期用一个短会话取数后立即关闭，流期间不长期占用数据库连接。
    max_ticks 只用于测试（生产为 None，直到客户端断开）。
    """
    factory = session_factory or SessionLocal
    with factory() as db:
        now = datetime.utcnow()
        snapshot = dashboard_payload(db, project_id, scope, days=1, now=now)
        cursor = _scoped_event_query(db, project_id, scope).with_entities(
            func.max(QualityAlertEvent.created_at),
        ).scalar()
        _, cursor, skip_ids = _events_since(db, project_id, scope, cursor, set(), STREAM_BATCH_LIMIT)
    yield _sse({"type": "snapshot", "dashboard": snapshot})
    last_heartbeat = time.monotonic()
    ticks = 0
    while max_ticks is None or ticks < max_ticks:
        ticks += 1
        sleep(poll_seconds)
        with factory() as db:
            events, cursor, skip_ids = _events_since(
                db, project_id, scope, cursor, skip_ids, STREAM_BATCH_LIMIT,
            )
            counts = _stream_counts(db, project_id, scope) if events else None
        if events:
            yield _sse({"type": "alerts", "events": events, "counts": counts})
        if time.monotonic() - last_heartbeat >= heartbeat_seconds:
            yield ": keepalive\n\n"
            last_heartbeat = time.monotonic()


@router.get("/api/projects/{project_id}/quality-monitor/stream")
def stream(
    project_id: UUID,
    factory: str | None = None,
    workshop: str | None = None,
    production_line: str | None = None,
    station_id: str | None = None,
    scene_id: str | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """SSE：鉴权走请求头（同聊天流先例），事件源是预警轨迹表（每 2 秒轮询）。"""
    require_project_access(db, project_id, current_user.id, "project.read")
    # 结束只读事务：流期间请求会话不再持有数据库连接
    db.commit()
    return StreamingResponse(
        monitor_event_stream(project_id, _scope(factory, workshop, production_line, station_id, scene_id)),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def _station_or_404(db: Session, project_id: UUID, station_id: str) -> QualityStation:
    """工位经场景归属到项目（工位的外键指向场景，不是项目）。"""
    station = (
        db.query(QualityStation)
        .join(QualityScene, QualityScene.id == QualityStation.scene_id)
        .filter(
            QualityStation.id == parse_uuid(station_id, "QUALITY_STATION_NOT_FOUND"),
            QualityScene.project_id == project_id,
        )
        .first()
    )
    if station is None:
        raise HTTPException(404, {"code": "QUALITY_STATION_NOT_FOUND"})
    return station


@router.post("/api/projects/{project_id}/quality-stations/{station_id}/ack-received")
def ack_received(
    project_id: UUID,
    station_id: str,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """「确认收到」：对该工位全部待处置预警执行确认，责任人记为当前用户（留痕）。"""
    access: ProjectAccess = require_project_access(
        db, project_id, current_user.id, "quality.alert_handle",
    )
    station = _station_or_404(db, project_id, station_id)
    pending = agg.scoped_alerts(
        db, project_id, agg.MonitorScope(station_id=station.id),
    ).filter(QualityAlert.status.in_(agg.OPEN_STATUSES)).all()
    with _audit_service(db).project_action(
        db, request=request, actor=current_user, access=access,
        permission="quality.alert_handle",
        intent=AuditIntent(
            project_id=project_id, action="quality.station.ack_received",
            resource_type="quality_station", resource_id=str(station.id),
            changes={"acknowledged": len(pending)},
        ),
        allowed_changes={"acknowledged"},
    ):
        for alert in pending:
            alert_service.acknowledge_alert(
                db, alert, assignee_id=current_user.id, actor_id=current_user.id,
                note="监控页确认收到",
            )
        db.commit()
    return {"station_id": str(station.id), "acknowledged": len(pending)}


class CallQualityRequest(BaseModel):
    reason: str = Field(min_length=2, max_length=500)


@router.post("/api/projects/{project_id}/quality-stations/{station_id}/call-quality")
def call_quality(
    project_id: UUID,
    station_id: str,
    request: Request,
    data: CallQualityRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """「呼叫质量人员」：通知工位责任人与项目负责人，并落审计。"""
    access: ProjectAccess = require_project_access(
        db, project_id, current_user.id, "quality.alert_handle",
    )
    station = _station_or_404(db, project_id, station_id)
    reason = data.reason.strip()
    title = f"质量呼叫：工位 {station.name}（{station.code}）"
    body = f"{current_user.username} 在实时监控呼叫质量人员。原因：{reason}"
    project = db.get(Project, project_id)
    with _audit_service(db).project_action(
        db, request=request, actor=current_user, access=access,
        permission="quality.alert_handle",
        intent=AuditIntent(
            project_id=project_id, action="quality.station.call_quality",
            resource_type="quality_station", resource_id=str(station.id),
            changes={"reason": reason[:200]},
        ),
        allowed_changes={"reason"},
    ):
        # 工位责任人单独通知；若责任人就是项目负责人，下面的负责人通知会覆盖，不重复发
        responsible = station.responsible_user_id
        if responsible and (project is None or responsible != project.owner_id):
            db.add(InAppNotification(
                recipient_user_id=responsible, project_id=project_id,
                event_id=uuid.uuid4(), event_type="quality.station.call",
                deduplication_key=f"qc-{uuid.uuid4().hex[:16]}", severity="warning",
                title=title, body=body, payload={"station_id": str(station.id)},
            ))
        db.commit()
    try:
        # notify_project_admins 自行 commit；通知失败不回滚已落审计的呼叫记录
        notified = notify_project_admins(
            db, project_id, title, body, severity="warning",
            event_type="quality.station.call", payload={"station_id": str(station.id)},
        )
    except Exception:  # noqa: BLE001
        logger.exception("call-quality notification failed for station %s", station.id)
        notified = 0
    return {
        "station_id": str(station.id), "notified": notified,
        "responsible_notified": bool(
            station.responsible_user_id
            and (project is None or station.responsible_user_id != project.owner_id)
        ),
    }


@router.get("/api/demo-loop/presence")
def demo_presence(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """演示态常驻标识的数据源（D33）：用户可访问的项目里是否存在演示循环配置。"""
    accessible = [
        row.id for row in ProjectAccessService()
        .accessible_project_query(db, current_user.id).with_entities(Project.id).all()
    ]
    projects = (
        db.query(Project.id, Project.name)
        .join(DemoLoopConfig, DemoLoopConfig.project_id == Project.id)
        .filter(Project.id.in_(accessible))
        .distinct().order_by(Project.name.asc())
        .all()
        if accessible else []
    )
    return {
        "present": bool(projects),
        "projects": [{"id": str(item_id), "name": name} for item_id, name in projects],
    }
