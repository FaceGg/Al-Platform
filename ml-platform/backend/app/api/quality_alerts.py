"""Quality alert & disposition API (补齐路线第一批 F2a, 技术方案 §9.7).

- 读走 project.read；处置动作走 quality.alert_handle（D17：owner/editor/
  operator）；配置类（规则设置 / SOP / 基线冻结）走 quality.manage。
- 全部写端点经 AuditService.project_action 落审计。
- 确认动作强制责任人（防呆，路线 B1-01 验收）；五阶段流转图校验。
"""
from __future__ import annotations

import csv
import io
import logging
import tempfile
import uuid
from datetime import datetime
from pathlib import Path
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile
from fastapi.responses import Response
from sqlalchemy.orm import Session, sessionmaker

from app.api.auth import get_current_user
from app.api.project_security import require_project_access
from app.config import settings as app_settings
from app.database import get_db
from app.models.data_version import DatasetSample, DatasetVersion
from app.models.quality_alerts import (
    ALERT_STATUSES,
    ALERT_STATUS_FLOW,
    ALERT_SEVERITIES,
    QualityAlert,
    QualityAlertEvent,
    QualitySop,
    QualitySpcBaseline,
)
from app.models.quality_domain import QualityScene, QualitySpecLimit, QualityStation
from app.models.user import User
from app.schemas.quality_alerts import (
    AlertAckRequest,
    AlertAssignRequest,
    AlertSettingsUpdate,
    AlertTransferRequest,
    AlertTransitionRequest,
    DispositionRequest,
    SopCreate,
    SpcBaselineFreezeRequest,
    parse_uuid,
)
from app.services.audit import AuditIntent, AuditService
from app.services.project_access import ProjectAccess
from app.services import quality_alerts as alert_service

logger = logging.getLogger(__name__)

router = APIRouter(tags=["quality-alerts"])

_CSV_COLUMNS = [
    "id", "source_type", "severity", "status", "title", "sample_key",
    "batch_no", "condition_value", "assigned_to", "occurrence_count",
    "sla_due_at", "created_at", "closed_at", "resolution", "is_demo",
]


def _audit_service(db: Session) -> AuditService:
    return AuditService(sessionmaker(bind=db.get_bind()))


def _alert_out(alert: QualityAlert) -> dict:
    return {
        "id": str(alert.id),
        "project_id": str(alert.project_id),
        "scene_id": str(alert.scene_id) if alert.scene_id else None,
        "station_id": str(alert.station_id) if alert.station_id else None,
        "device_id": str(alert.device_id) if alert.device_id else None,
        "condition_value": alert.condition_value,
        "source_type": alert.source_type,
        "risk_score": alert.risk_score,
        "severity": alert.severity,
        "title": alert.title,
        "sample_key": alert.sample_key,
        "batch_no": alert.batch_no,
        "product_code": alert.product_code,
        "evidence": alert.evidence or {},
        "status": alert.status,
        "assigned_to": str(alert.assigned_to_id) if alert.assigned_to_id else None,
        "first_ack_at": alert.first_ack_at.isoformat() if alert.first_ack_at else None,
        "closed_at": alert.closed_at.isoformat() if alert.closed_at else None,
        "sla_due_at": alert.sla_due_at.isoformat() if alert.sla_due_at else None,
        "sla_notify_level": int(alert.sla_notify_level or 0),
        "resolution": alert.resolution,
        "occurrence_count": int(alert.occurrence_count or 1),
        "merge_key": alert.merge_key,
        "merge_open": bool(alert.merge_open),
        "last_event_at": alert.last_event_at.isoformat() if alert.last_event_at else None,
        "is_demo": bool(alert.is_demo),
        "created_at": alert.created_at.isoformat() if alert.created_at else None,
    }


def _event_out(event: QualityAlertEvent) -> dict:
    return {
        "id": str(event.id),
        "alert_id": str(event.alert_id),
        "action": event.action,
        "from_status": event.from_status,
        "to_status": event.to_status,
        "actor": str(event.actor_id) if event.actor_id else None,
        "note": event.note,
        "form_snapshot": event.form_snapshot,
        "snapshot": event.snapshot,
        "created_at": event.created_at.isoformat() if event.created_at else None,
    }


def _get_alert(db: Session, project_id: UUID, alert_id) -> QualityAlert:
    alert = db.query(QualityAlert).filter(
        QualityAlert.id == parse_uuid(alert_id, "QUALITY_ALERT_ID_INVALID"),
        QualityAlert.project_id == project_id,
    ).first()
    if alert is None:
        raise HTTPException(404, {"code": "QUALITY_ALERT_NOT_FOUND"})
    return alert


def _allowed_transitions(alert: QualityAlert) -> list[str]:
    return sorted(ALERT_STATUS_FLOW.get(alert.status, set()))


def _error_payload(error: ValueError) -> dict:
    """错误码取「（」之前的机器可读部分；完整说明放 message。

    服务层抛的是「CODE（中文说明）」形态——code 必须保持干净，前端按它分支。
    """
    text = str(error)
    code, _, _ = text.partition("（")
    return {"code": code, "message": text}


@router.get("/api/projects/{project_id}/quality-alerts")
def list_alerts(
    project_id: UUID,
    status: str | None = None,
    severity: str | None = None,
    source_type: str | None = None,
    scene_id: str | None = None,
    station_id: str | None = None,
    sample_key: str | None = None,
    batch_no: str | None = None,
    include_demo: bool = False,
    sla_overdue: bool = False,
    open: bool = False,
    min_severity: str | None = None,
    occurred_from: str | None = None,
    occurred_to: str | None = None,
    page: int = 1,
    page_size: int = 20,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    require_project_access(db, project_id, current_user.id, "project.read")
    query = db.query(QualityAlert).filter(QualityAlert.project_id == project_id)
    # 演示隔离（D18/诚实设计⑥）：默认排除演示预警，显式开关可见
    if not include_demo:
        query = query.filter(QualityAlert.is_demo.is_(False))
    if sla_overdue:
        # SLA 已超时且仍未处置完（驾驶舱「超时」口径与此同源）
        query = query.filter(
            QualityAlert.sla_due_at.isnot(None),
            QualityAlert.sla_due_at < datetime.utcnow(),
            QualityAlert.status.in_(("open", "acknowledged", "processing")),
        )
    if open:
        # 「未关闭」= 驾驶舱「待处理」卡的口径（四个未关闭阶段），与只筛 open 状态不同
        query = query.filter(
            QualityAlert.status.in_([value for value in ALERT_STATUSES if value != "closed"]),
        )
    if min_severity:
        # 「不低于某级别」= 驾驶舱「高风险」卡的口径（高风险 + 严重）
        if min_severity not in ALERT_SEVERITIES:
            raise HTTPException(422, {"code": "SEVERITY_INVALID", "message": "min_severity 须为 warning / high / critical"})
        floor = ("warning", "high", "critical").index(min_severity)
        query = query.filter(QualityAlert.severity.in_(("warning", "high", "critical")[floor:]))
    if status:
        query = query.filter(QualityAlert.status == status)
    if severity:
        query = query.filter(QualityAlert.severity == severity)
    if source_type:
        query = query.filter(QualityAlert.source_type == source_type)
    if scene_id:
        query = query.filter(QualityAlert.scene_id == parse_uuid(scene_id, "SCENE_ID_INVALID"))
    if station_id:
        query = query.filter(QualityAlert.station_id == parse_uuid(station_id, "STATION_ID_INVALID"))
    if sample_key:
        query = query.filter(QualityAlert.sample_key == sample_key)
    if batch_no:
        query = query.filter(QualityAlert.batch_no == batch_no)
    if occurred_from:
        query = query.filter(QualityAlert.created_at >= _parse_time(occurred_from))
    if occurred_to:
        query = query.filter(QualityAlert.created_at <= _parse_time(occurred_to))
    total = query.count()
    page = max(1, page)
    page_size = min(max(1, page_size), 100)
    items = (
        query.order_by(QualityAlert.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return {"items": [_alert_out(a) for a in items], "total": total,
            "page": page, "page_size": page_size}


def _parse_time(value: str) -> datetime:
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        raise HTTPException(422, {"code": "TIME_INVALID"}) from None


@router.get("/api/projects/{project_id}/quality-alerts/export.csv")
def export_alerts_csv(
    project_id: UUID,
    status: str | None = None,
    severity: str | None = None,
    source_type: str | None = None,
    include_demo: bool = False,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    require_project_access(
        db, project_id, current_user.id, "quality.alert_handle",
    )
    query = db.query(QualityAlert).filter(QualityAlert.project_id == project_id)
    if not include_demo:
        query = query.filter(QualityAlert.is_demo.is_(False))
    if status:
        query = query.filter(QualityAlert.status == status)
    if severity:
        query = query.filter(QualityAlert.severity == severity)
    if source_type:
        query = query.filter(QualityAlert.source_type == source_type)
    rows = query.order_by(QualityAlert.created_at.desc()).limit(10000).all()
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(_CSV_COLUMNS)
    for alert in rows:
        writer.writerow([
            str(alert.id), alert.source_type, alert.severity, alert.status,
            alert.title, alert.sample_key or "", alert.batch_no or "",
            alert.condition_value or "",
            str(alert.assigned_to_id) if alert.assigned_to_id else "",
            int(alert.occurrence_count or 1),
            alert.sla_due_at.isoformat() if alert.sla_due_at else "",
            alert.created_at.isoformat() if alert.created_at else "",
            alert.closed_at.isoformat() if alert.closed_at else "",
            alert.resolution or "", "1" if alert.is_demo else "0",
        ])
    return Response(
        content="\ufeff" + buffer.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=quality-alerts.csv"},
    )


@router.get("/api/projects/{project_id}/quality-alerts/{alert_id}")
def get_alert(
    project_id: UUID,
    alert_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    require_project_access(db, project_id, current_user.id, "project.read")
    alert = _get_alert(db, project_id, alert_id)
    events = (
        db.query(QualityAlertEvent)
        .filter(QualityAlertEvent.alert_id == alert.id)
        .order_by(QualityAlertEvent.created_at.asc())
        .all()
    )
    payload = _alert_out(alert)
    payload["events"] = [_event_out(e) for e in events]
    payload["allowed_transitions"] = _allowed_transitions(alert)
    return payload


def _assignee_or_422(db: Session, assignee_id: str):
    from app.models.user import User as UserModel

    try:
        resolved = uuid.UUID(str(assignee_id))
    except (TypeError, ValueError, AttributeError):
        raise HTTPException(422, {"code": "ASSIGNEE_ID_INVALID"}) from None
    if db.query(UserModel.id).filter(UserModel.id == resolved).first() is None:
        raise HTTPException(422, {"code": "ASSIGNEE_NOT_FOUND"})
    return resolved


@router.post("/api/projects/{project_id}/quality-alerts/{alert_id}/ack")
def ack_alert(
    project_id: UUID,
    alert_id: str,
    request: Request,
    data: AlertAckRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """确认动作：强制填写责任人（防呆；缺失 422，路线 B1-01 验收）。"""
    access: ProjectAccess = require_project_access(
        db, project_id, current_user.id, "quality.alert_handle",
    )
    alert = _get_alert(db, project_id, alert_id)
    assignee_id = _assignee_or_422(db, data.assignee_id)
    with _audit_service(db).project_action(
        db, request=request, actor=current_user, access=access,
        permission="quality.alert_handle",
        intent=AuditIntent(
            project_id=project_id, action="quality.alert.ack",
            resource_type="quality_alert", resource_id=str(alert.id),
            changes={"assignee_id": str(assignee_id)},
        ),
        allowed_changes={"assignee_id"},
    ):
        alert_service.acknowledge_alert(
            db, alert, assignee_id=assignee_id,
            actor_id=current_user.id, note=data.note,
        )
        db.commit()
        db.refresh(alert)
    return _alert_out(alert)


@router.post("/api/projects/{project_id}/quality-alerts/{alert_id}/assign")
def assign_alert(
    project_id: UUID,
    alert_id: str,
    request: Request,
    data: AlertAssignRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    access: ProjectAccess = require_project_access(
        db, project_id, current_user.id, "quality.alert_handle",
    )
    alert = _get_alert(db, project_id, alert_id)
    assignee_id = _assignee_or_422(db, data.assignee_id)
    with _audit_service(db).project_action(
        db, request=request, actor=current_user, access=access,
        permission="quality.alert_handle",
        intent=AuditIntent(
            project_id=project_id, action="quality.alert.assign",
            resource_type="quality_alert", resource_id=str(alert.id),
            changes={"assignee_id": str(assignee_id)},
        ),
        allowed_changes={"assignee_id"},
    ):
        alert.assigned_to_id = assignee_id
        alert_service.append_event(
            db, alert, "assigned", actor_id=current_user.id, note=data.note,
        )
        db.commit()
        db.refresh(alert)
    return _alert_out(alert)


@router.post("/api/projects/{project_id}/quality-alerts/{alert_id}/transition")
def transition_alert(
    project_id: UUID,
    alert_id: str,
    request: Request,
    data: AlertTransitionRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    access: ProjectAccess = require_project_access(
        db, project_id, current_user.id, "quality.alert_handle",
    )
    alert = _get_alert(db, project_id, alert_id)
    with _audit_service(db).project_action(
        db, request=request, actor=current_user, access=access,
        permission="quality.alert_handle",
        intent=AuditIntent(
            project_id=project_id, action="quality.alert.transition",
            resource_type="quality_alert", resource_id=str(alert.id),
            changes={"to_status": data.to_status},
        ),
        allowed_changes={"to_status", "resolution"},
    ):
        try:
            alert_service.transition_alert(
                db, alert, data.to_status, actor_id=current_user.id,
                note=data.note, resolution=data.resolution,
            )
        except alert_service.AlertTransitionError as error:
            db.rollback()
            raise HTTPException(422, _error_payload(error)) from None
        db.commit()
        db.refresh(alert)
    return _alert_out(alert)


@router.post("/api/projects/{project_id}/quality-alerts/{alert_id}/disposition")
def disposition_alert(
    project_id: UUID,
    alert_id: str,
    request: Request,
    data: DispositionRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """处置表单提交（B1-02）：表单快照 + 三要素快照；误报触发回流（D22）。"""
    access: ProjectAccess = require_project_access(
        db, project_id, current_user.id, "quality.alert_handle",
    )
    alert = _get_alert(db, project_id, alert_id)
    form = {
        "type": data.type, "cause": data.cause, "action": data.action,
        "downtime": data.downtime, "rework": data.rework,
        "expanded_inspection": data.expanded_inspection,
    }
    with _audit_service(db).project_action(
        db, request=request, actor=current_user, access=access,
        permission="quality.alert_handle",
        intent=AuditIntent(
            project_id=project_id, action="quality.alert.disposition",
            resource_type="quality_alert", resource_id=str(alert.id),
            changes={"resolution": data.resolution},
        ),
        allowed_changes={"resolution", "status"},
    ):
        try:
            review_annotator_ids = [
                parse_uuid(item, "REVIEW_ANNOTATOR_ID_INVALID")
                for item in data.review_annotator_ids
            ]
            outcome = alert_service.submit_disposition(
                db, alert, actor_id=current_user.id, form=form,
                resolution=data.resolution, note=data.note,
                review_annotator_ids=review_annotator_ids,
            )
        except alert_service.AlertTransitionError as error:
            db.rollback()
            raise HTTPException(422, _error_payload(error)) from None
        db.commit()
        db.refresh(alert)
    payload = _alert_out(alert)
    payload["outcome"] = outcome
    return payload


@router.post("/api/projects/{project_id}/quality-alerts/{alert_id}/transfer")
def transfer_alert(
    project_id: UUID,
    alert_id: str,
    request: Request,
    data: AlertTransferRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    access: ProjectAccess = require_project_access(
        db, project_id, current_user.id, "quality.alert_handle",
    )
    alert = _get_alert(db, project_id, alert_id)
    assignee_id = _assignee_or_422(db, data.assignee_id)
    with _audit_service(db).project_action(
        db, request=request, actor=current_user, access=access,
        permission="quality.alert_handle",
        intent=AuditIntent(
            project_id=project_id, action="quality.alert.transfer",
            resource_type="quality_alert", resource_id=str(alert.id),
            changes={"assignee_id": str(assignee_id)},
        ),
        allowed_changes={"assignee_id"},
    ):
        alert.assigned_to_id = assignee_id
        alert_service.append_event(
            db, alert, "transfer", actor_id=current_user.id, note=data.note,
        )
        db.commit()
        db.refresh(alert)
    return _alert_out(alert)


@router.post("/api/projects/{project_id}/quality-alerts/{alert_id}/request-review")
def request_review(
    project_id: UUID,
    alert_id: str,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    access: ProjectAccess = require_project_access(
        db, project_id, current_user.id, "quality.alert_handle",
    )
    alert = _get_alert(db, project_id, alert_id)
    with _audit_service(db).project_action(
        db, request=request, actor=current_user, access=access,
        permission="quality.alert_handle",
        intent=AuditIntent(
            project_id=project_id, action="quality.alert.request_review",
            resource_type="quality_alert", resource_id=str(alert.id),
            changes={"to_status": "review_pending"},
        ),
        allowed_changes={"to_status"},
    ):
        try:
            alert_service.transition_alert(
                db, alert, "review_pending", actor_id=current_user.id,
                note="请求复核", action="review_requested",
            )
        except alert_service.AlertTransitionError as error:
            db.rollback()
            raise HTTPException(422, _error_payload(error)) from None
        db.commit()
        db.refresh(alert)
    return _alert_out(alert)


@router.post("/api/projects/{project_id}/quality-alerts/{alert_id}/attachments")
async def upload_attachment(
    project_id: UUID,
    alert_id: str,
    request: Request,
    file: UploadFile,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """处置附件上传（B1-02：照片/文件接 MinIO；竞品「未配置」是反面教材）。"""
    access: ProjectAccess = require_project_access(
        db, project_id, current_user.id, "quality.alert_handle",
    )
    alert = _get_alert(db, project_id, alert_id)
    from app.services.artifact_service import ArtifactService
    from app.storage.factory import create_artifact_storage

    suffix = Path(file.filename or "attachment.bin").suffix[:16] or ".bin"
    safe_name = f"alert-{str(alert.id)[:8]}-attachment{suffix}"
    with tempfile.TemporaryDirectory() as workdir:
        target = Path(workdir) / safe_name
        size = 0
        with target.open("wb") as handle:
            while chunk := await file.read(1024 * 1024):
                size += len(chunk)
                if size > 20 * 1024 * 1024:
                    raise HTTPException(413, {"code": "ATTACHMENT_TOO_LARGE"})
                handle.write(chunk)
        storage = create_artifact_storage(app_settings)
        service = ArtifactService(db, storage)
        with _audit_service(db).project_action(
            db, request=request, actor=current_user, access=access,
            permission="quality.alert_handle",
            intent=AuditIntent(
                project_id=project_id, action="quality.alert.attachment",
                resource_type="quality_alert", resource_id=str(alert.id),
                changes={"name": safe_name},
            ),
            allowed_changes={"name"},
        ):
            artifact = service.create_from_file(
                project_id=project_id,
                source_path=target,
                name=safe_name,
                artifact_type="attachment",
                metadata={
                    "alert_id": str(alert.id),
                    "uploaded_by": str(current_user.id),
                },
                commit=True,
            )
    alert_service.append_event(
        db, alert, "attachment_added", actor_id=current_user.id,
        note=file.filename or safe_name,
        form_snapshot={
            "artifact_id": str(artifact.id), "name": safe_name, "size": size,
        },
    )
    db.commit()
    return {"artifact_id": str(artifact.id), "name": safe_name, "size": size}


@router.get("/api/projects/{project_id}/quality-alerts/{alert_id}/criteria")
def get_criteria(
    project_id: UUID,
    alert_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """判据链复算（D20 口径）：规格读当前值、σ 绑定当时基线版本。"""
    require_project_access(db, project_id, current_user.id, "project.read")
    alert = _get_alert(db, project_id, alert_id)
    return {"alert_id": str(alert.id), "criteria": alert_service.evaluate_criteria_chain(db, alert)}


@router.get("/api/projects/{project_id}/quality-alerts/{alert_id}/waveform")
def get_waveform(
    project_id: UUID,
    alert_id: str,
    dataset_version_id: str | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """曲线叠加数据（D23）：样本键定位数据集行 → 波形列解码；目标窗口=规格。"""
    require_project_access(db, project_id, current_user.id, "project.read")
    alert = _get_alert(db, project_id, alert_id)
    if not alert.sample_key:
        return {"status": "no_waveform", "reason": "预警无样本键，无法定位波形"}
    sample_query = (
        db.query(DatasetSample)
        .join(DatasetVersion, DatasetSample.dataset_version_id == DatasetVersion.id)
        .filter(
            # 限定在本项目内——样本键不是全局唯一的，不能跨项目取数
            DatasetVersion.project_id == project_id,
            DatasetSample.sample_id == str(alert.sample_key),
            DatasetVersion.status == "ready",
        )
    )
    if dataset_version_id:
        sample_query = sample_query.filter(
            DatasetSample.dataset_version_id
            == parse_uuid(dataset_version_id, "DATASET_VERSION_ID_INVALID"),
        )
    sample = sample_query.order_by(DatasetSample.id.desc()).first()
    if sample is None:
        return {"status": "no_waveform", "reason": "样本不在本项目的任何就绪数据集版本中"}
    scene = (
        db.query(QualityScene).filter(QualityScene.id == alert.scene_id).first()
        if alert.scene_id else None
    )
    field_roles = dict((scene.field_roles or {}) if scene else {})
    waveform_column = field_roles.get("waveform") or (
        scene.waveform_column if scene else None
    )
    values = dict(sample.values or {})
    if not waveform_column or waveform_column not in values:
        return {"status": "no_waveform", "reason": "场景未声明波形列或该行无波形数据"}
    points = alert_service.decode_waveform_column(values[waveform_column])
    if not points:
        return {"status": "decode_failed", "reason": "波形解码失败（编码格式不符）"}
    # 目标窗口来自规格定义（E27 单一来源）：同一波形列可按多个统计量设规格
    specs = (
        db.query(QualitySpecLimit)
        .filter(
            QualitySpecLimit.scene_id == alert.scene_id,
            QualitySpecLimit.field == waveform_column,
        )
        .order_by(QualitySpecLimit.statistic.asc())
        .all()
        if alert.scene_id else []
    )
    return {
        "status": "ok",
        "column": waveform_column,
        "points": points,
        "dataset_version_id": str(sample.dataset_version_id),
        "specs": [
            {
                "statistic": spec.statistic,
                "target": spec.target,
                "usl": spec.usl,
                "lsl": spec.lsl,
                "unit": spec.unit,
            }
            for spec in specs
        ],
    }


# ----------------------------------------------------------------------
# 配置类：预警规则设置（D14）/ SOP（E07）/ SPC 基线冻结（E08）
# ----------------------------------------------------------------------

@router.put("/api/projects/{project_id}/quality-scenes/{scene_id}/alert-settings")
def update_alert_settings(
    project_id: UUID,
    scene_id: str,
    request: Request,
    data: AlertSettingsUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    access: ProjectAccess = require_project_access(
        db, project_id, current_user.id, "quality.manage",
    )
    scene = db.query(QualityScene).filter(
        QualityScene.id == parse_uuid(scene_id, "QUALITY_SCENE_NOT_FOUND"),
        QualityScene.project_id == project_id,
    ).first()
    if scene is None:
        raise HTTPException(404, {"code": "QUALITY_SCENE_NOT_FOUND"})
    settings_payload = {
        key: value for key, value in data.model_dump().items() if value is not None
    }
    # 只存显式配置的键（平台默认后续调整时场景能跟随），但校验的是
    # 与平台默认合并后的完整规则——避免「高」档低于默认触发下限这类矛盾配置
    resolved = alert_service.resolve_alert_settings(scene)
    resolved.update(settings_payload)
    try:
        alert_service.validate_alert_settings(resolved)
    except ValueError as error:
        raise HTTPException(422, _error_payload(error)) from None
    with _audit_service(db).project_action(
        db, request=request, actor=current_user, access=access,
        permission="quality.manage",
        intent=AuditIntent(
            project_id=project_id, action="quality.scene.alert_settings",
            resource_type="quality_scene", resource_id=str(scene.id),
            changes=dict(settings_payload),
        ),
        allowed_changes=set(settings_payload),
    ):
        scene.alert_settings = settings_payload
        db.commit()
        db.refresh(scene)
    return {
        "scene_id": str(scene.id),
        "alert_settings": scene.alert_settings or {},
        "resolved": alert_service.resolve_alert_settings(scene),
    }


@router.get("/api/projects/{project_id}/quality-scenes/{scene_id}/alert-settings")
def get_alert_settings(
    project_id: UUID,
    scene_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    require_project_access(db, project_id, current_user.id, "project.read")
    scene = db.query(QualityScene).filter(
        QualityScene.id == parse_uuid(scene_id, "QUALITY_SCENE_NOT_FOUND"),
        QualityScene.project_id == project_id,
    ).first()
    if scene is None:
        raise HTTPException(404, {"code": "QUALITY_SCENE_NOT_FOUND"})
    return {
        "scene_id": str(scene.id),
        "alert_settings": scene.alert_settings or {},
        "resolved": alert_service.resolve_alert_settings(scene),
    }


def _sop_out(item: QualitySop) -> dict:
    return {
        "id": str(item.id),
        "project_id": str(item.project_id),
        "scene_id": str(item.scene_id) if item.scene_id else None,
        "code": item.code,
        "version": int(item.version or 1),
        "title": item.title,
        "content": item.content or {},
        "condition_value": item.condition_value,
        "effective_from": item.effective_from.isoformat() if item.effective_from else None,
        "retired_at": item.retired_at.isoformat() if item.retired_at else None,
        "is_active": item.retired_at is None,
        "created_at": item.created_at.isoformat() if item.created_at else None,
    }


@router.get("/api/projects/{project_id}/quality-sops")
def list_sops(
    project_id: UUID,
    code: str | None = None,
    active_only: bool = False,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    require_project_access(db, project_id, current_user.id, "project.read")
    query = db.query(QualitySop).filter(QualitySop.project_id == project_id)
    if code:
        query = query.filter(QualitySop.code == code)
    if active_only:
        query = query.filter(QualitySop.retired_at.is_(None))
    items = query.order_by(QualitySop.code.asc(), QualitySop.version.desc()).all()
    return {"items": [_sop_out(s) for s in items], "total": len(items)}


@router.post("/api/projects/{project_id}/quality-sops")
def create_sop(
    project_id: UUID,
    request: Request,
    data: SopCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """新建 SOP 版本（E07）：同 code+工况旧版本退役，版本号递增。"""
    access: ProjectAccess = require_project_access(
        db, project_id, current_user.id, "quality.manage",
    )
    scene_id = (
        parse_uuid(data.scene_id, "QUALITY_SCENE_NOT_FOUND") if data.scene_id else None
    )
    if scene_id is not None:
        owned_scene = db.query(QualityScene.id).filter(
            QualityScene.id == scene_id, QualityScene.project_id == project_id,
        ).first()
        if owned_scene is None:
            raise HTTPException(404, {"code": "QUALITY_SCENE_NOT_FOUND"})
    now = datetime.utcnow()
    sop_id = uuid.uuid4()
    with _audit_service(db).project_action(
        db, request=request, actor=current_user, access=access,
        permission="quality.manage",
        intent=AuditIntent(
            project_id=project_id, action="quality.sop.create",
            resource_type="quality_sop", resource_id=str(sop_id),
            changes={"code": data.code, "condition_value": data.condition_value},
        ),
        allowed_changes={"code", "title", "content", "condition_value", "scene_id"},
    ):
        previous = (
            db.query(QualitySop)
            .filter(
                QualitySop.project_id == project_id,
                QualitySop.code == data.code.strip(),
                QualitySop.condition_value.is_(None) if data.condition_value is None
                else QualitySop.condition_value == data.condition_value,
                QualitySop.retired_at.is_(None),
            )
            .all()
        )
        version = max((int(item.version or 1) for item in previous), default=0) + 1
        for item in previous:
            item.retired_at = now
        sop = QualitySop(
            id=sop_id,
            project_id=project_id,
            scene_id=scene_id,
            code=data.code.strip(),
            version=version,
            title=data.title.strip(),
            content=data.content.model_dump(),
            condition_value=data.condition_value,
            effective_from=now,
            created_by_id=current_user.id,
            created_at=now,
        )
        db.add(sop)
        db.commit()
        db.refresh(sop)
    return _sop_out(sop)


@router.post("/api/projects/{project_id}/quality-scenes/{scene_id}/spc-baselines")
def freeze_spc_baseline(
    project_id: UUID,
    scene_id: str,
    request: Request,
    data: SpcBaselineFreezeRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """冻结 SPC 基线（E08）：数值由服务端从数据集版本的稳定时段取出，
    I-MR 计算；20–500 与恒定拒绝；新版本生成并置同键旧版本失效（旧行保留可查）。
    """
    access: ProjectAccess = require_project_access(
        db, project_id, current_user.id, "quality.manage",
    )
    scene = db.query(QualityScene).filter(
        QualityScene.id == parse_uuid(scene_id, "QUALITY_SCENE_NOT_FOUND"),
        QualityScene.project_id == project_id,
    ).first()
    if scene is None:
        raise HTTPException(404, {"code": "QUALITY_SCENE_NOT_FOUND"})
    dataset_version = db.query(DatasetVersion).filter(
        DatasetVersion.id == parse_uuid(data.dataset_version_id, "DATASET_VERSION_NOT_FOUND"),
        DatasetVersion.project_id == project_id,
        DatasetVersion.status == "ready",
    ).first()
    if dataset_version is None:
        raise HTTPException(404, {"code": "DATASET_VERSION_NOT_FOUND"})
    station_id = (
        parse_uuid(data.station_id, "QUALITY_STATION_NOT_FOUND")
        if data.station_id else None
    )
    field_roles = dict(scene.field_roles or {})
    time_column = field_roles.get("collected_at") or field_roles.get("time")
    try:
        time_from = datetime.fromisoformat(data.time_from) if data.time_from else None
        time_to = datetime.fromisoformat(data.time_to) if data.time_to else None
    except ValueError:
        raise HTTPException(422, {"code": "TIME_INVALID"}) from None
    if (time_from is not None or time_to is not None) and not time_column:
        raise HTTPException(422, {
            "code": "SCENE_TIME_ROLE_REQUIRED",
            "message": "时间窗需要场景声明时间字段角色（collected_at 或 time）",
        })
    if (
        data.row_index_from is not None and data.row_index_to is not None
        and data.row_index_from > data.row_index_to
    ):
        raise HTTPException(422, {"code": "ROW_RANGE_INVALID"})
    with _audit_service(db).project_action(
        db, request=request, actor=current_user, access=access,
        permission="quality.manage",
        intent=AuditIntent(
            project_id=project_id, action="quality.spc_baseline.freeze",
            resource_type="quality_spc_baseline", resource_id=str(scene.id),
            changes={"field": data.field, "statistic": data.statistic,
                     "dataset_version_id": str(dataset_version.id)},
        ),
        allowed_changes={"field", "statistic", "dataset_version_id",
                         "station_id", "condition_value"},
    ):
        try:
            values, reference = alert_service.collect_baseline_values(
                db,
                dataset_version=dataset_version,
                field=data.field,
                condition_column=scene.condition_column,
                condition_value=data.condition_value,
                time_column=time_column,
                time_from=time_from,
                time_to=time_to,
                row_index_from=data.row_index_from,
                row_index_to=data.row_index_to,
            )
            reference.update({
                "dataset_version_id": str(dataset_version.id),
                "dataset_version": dataset_version.version,
                "content_hash": dataset_version.content_hash,
                "field": data.field,
                "condition_value": data.condition_value,
                "row_index_from": data.row_index_from,
                "row_index_to": data.row_index_to,
                "time_from": data.time_from,
                "time_to": data.time_to,
            })
            baseline = alert_service.freeze_baseline(
                db,
                project_id=project_id,
                scene_id=scene.id,
                station_id=station_id,
                condition_value=data.condition_value,
                field=data.field,
                statistic=data.statistic,
                values=values,
                reference=reference,
                window_start=time_from,
                window_end=time_to,
                actor_id=current_user.id,
            )
        except ValueError as error:
            db.rollback()
            raise HTTPException(422, _error_payload(error)) from None
        db.commit()
        db.refresh(baseline)
    return {
        "id": str(baseline.id),
        "scene_id": str(baseline.scene_id),
        "station_id": str(baseline.station_id) if baseline.station_id else None,
        "condition_value": baseline.condition_value,
        "field": baseline.field,
        "statistic": baseline.statistic,
        "center": baseline.center,
        "sigma": baseline.sigma,
        "sample_count": baseline.sample_count,
        "version": baseline.version,
        "is_active": bool(baseline.is_active),
        "reference": baseline.reference,
        "window_start": baseline.window_start.isoformat(),
        "window_end": baseline.window_end.isoformat(),
    }


@router.get("/api/projects/{project_id}/quality-scenes/{scene_id}/spc-baselines")
def list_spc_baselines(
    project_id: UUID,
    scene_id: str,
    field: str | None = None,
    active_only: bool = False,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    require_project_access(db, project_id, current_user.id, "project.read")
    query = db.query(QualitySpcBaseline).filter(
        QualitySpcBaseline.project_id == project_id,
        QualitySpcBaseline.scene_id == parse_uuid(scene_id, "QUALITY_SCENE_NOT_FOUND"),
    )
    if field:
        query = query.filter(QualitySpcBaseline.field == field)
    if active_only:
        query = query.filter(QualitySpcBaseline.is_active.is_(True))
    items = query.order_by(
        QualitySpcBaseline.field.asc(), QualitySpcBaseline.version.desc()
    ).all()
    return {
        "items": [
            {
                "id": str(item.id),
                "field": item.field,
                "statistic": item.statistic,
                "station_id": str(item.station_id) if item.station_id else None,
                "condition_value": item.condition_value,
                "center": item.center,
                "sigma": item.sigma,
                "sample_count": item.sample_count,
                "version": item.version,
                "is_active": bool(item.is_active),
                "window_start": item.window_start.isoformat() if item.window_start else None,
                "window_end": item.window_end.isoformat() if item.window_end else None,
                "created_at": item.created_at.isoformat() if item.created_at else None,
            }
            for item in items
        ],
        "total": len(items),
    }
