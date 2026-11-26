"""Drift monitoring API (补齐路线第一批 F4, B1-09).

技术方案 §9C.3：报告读取 = project.read；转重训提案与手动触发扫描 = quality.manage。
漂移是触发器不是自动开关：提案只通知项目负责人并留痕，审批流属第二批（已暂停）。
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session, sessionmaker

from app.api.auth import get_current_user
from app.api.project_security import require_project_access
from app.config import settings as app_settings
from app.database import get_db
from app.models.drift import DriftReport, DriftReportFeature
from app.models.model_registry import InferenceDeployment
from app.models.user import User
from app.services import drift_detection as drift
from app.services.audit import AuditIntent, AuditService
from app.services.project_access import ProjectAccess

logger = logging.getLogger(__name__)

router = APIRouter(tags=["drift"])


def _audit_service(db: Session) -> AuditService:
    return AuditService(sessionmaker(bind=db.get_bind()))


def _report_out(report: DriftReport) -> dict:
    return {
        "id": str(report.id),
        "project_id": str(report.project_id),
        "deployment_id": str(report.deployment_id) if report.deployment_id else None,
        "model_version_id": str(report.model_version_id) if report.model_version_id else None,
        "started_at": report.started_at.isoformat() if report.started_at else None,
        "ended_at": report.ended_at.isoformat() if report.ended_at else None,
        "level": report.level,
        "sample_count": int(report.sample_count or 0),
        "summary": report.summary or {},
        "proposal_at": report.proposal_at.isoformat() if report.proposal_at else None,
        "created_at": report.created_at.isoformat() if report.created_at else None,
    }


def _feature_out(item: DriftReportFeature) -> dict:
    return {
        "feature_name": item.feature_name, "signal_kind": item.signal_kind,
        "value": item.value, "threshold": item.threshold, "level": item.level,
        "detail": item.detail or {},
    }


def _deployment_out(db: Session, deployment: InferenceDeployment, latest: DriftReport | None) -> dict:
    return {
        "id": str(deployment.id), "name": deployment.name,
        "model_version_id": str(deployment.model_version_id),
        # 没有训练分布基线（无训练数据血缘）的部署做不了特征级检测：如实标出
        "has_baseline": drift.ensure_baselines(db, deployment.model_version_id) is not None,
        "latest": _report_out(latest) if latest is not None else None,
    }


@router.get("/api/projects/{project_id}/drift/deployments")
def drift_deployments(
    project_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """本项目运行态的部署、是否有基线、以及每个部署最近一次报告。"""
    require_project_access(db, project_id, current_user.id, "project.read")
    deployments = (
        db.query(InferenceDeployment)
        .filter(
            InferenceDeployment.project_id == project_id,
            InferenceDeployment.desired_state == "running",
        )
        .order_by(InferenceDeployment.created_at.asc())
        .all()
    )
    items = []
    for deployment in deployments:
        latest = (
            db.query(DriftReport)
            .filter(DriftReport.deployment_id == deployment.id)
            .order_by(DriftReport.created_at.desc())
            .first()
        )
        items.append(_deployment_out(db, deployment, latest))
    return {"items": items, "scan_interval_seconds": app_settings.drift_scan_interval_seconds}


@router.get("/api/projects/{project_id}/drift/reports")
def drift_reports(
    project_id: UUID,
    deployment_id: str | None = None,
    page: int = 1,
    page_size: int = 20,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    require_project_access(db, project_id, current_user.id, "project.read")
    query = db.query(DriftReport).filter(DriftReport.project_id == project_id)
    if deployment_id:
        query = query.filter(DriftReport.deployment_id == deployment_id)
    total = query.count()
    page = max(1, page)
    page_size = min(max(1, page_size), 100)
    rows = (
        query.order_by(DriftReport.created_at.desc())
        .offset((page - 1) * page_size).limit(page_size).all()
    )
    names = {
        str(item.id): item.name
        for item in db.query(InferenceDeployment).filter(
            InferenceDeployment.project_id == project_id,
        ).all()
    }
    return {
        "items": [
            {**_report_out(report), "deployment_name": names.get(str(report.deployment_id))}
            for report in rows
        ],
        "total": total, "page": page, "page_size": page_size,
    }


@router.get("/api/projects/{project_id}/drift/reports/{report_id}")
def drift_report_detail(
    project_id: UUID,
    report_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    require_project_access(db, project_id, current_user.id, "project.read")
    report = db.query(DriftReport).filter(
        DriftReport.project_id == project_id,
        DriftReport.id == _id_or_404(report_id),
    ).first()
    if report is None:
        raise HTTPException(404, {"code": "DRIFT_REPORT_NOT_FOUND"})
    features = (
        db.query(DriftReportFeature)
        .filter(DriftReportFeature.report_id == report.id)
        .order_by(DriftReportFeature.value.desc())
        .all()
    )
    return {
        **_report_out(report),
        "features": [_feature_out(item) for item in features],
        # 页面须如实显示：本期未接入的信号
        "not_wired": (report.summary or {}).get("not_wired", []),
    }


def _id_or_404(value):
    try:
        return uuid.UUID(str(value))
    except (TypeError, ValueError, AttributeError):
        raise HTTPException(404, {"code": "DRIFT_REPORT_NOT_FOUND"}) from None


@router.post("/api/projects/{project_id}/drift/reports/{report_id}/propose-retrain")
def propose_retrain(
    project_id: UUID,
    report_id: str,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """「转重训提案」：创建 retrain_proposal 审批单（S1 队列）+ 通知 + 审计。

    第二批 S1 接线：提案进统一四眼审批队列（驳回落拒绝水位线 E05，
    批准经部署绑定闭环触发重训轮）；同部署同报告水位线未越过时 409。
    """
    access: ProjectAccess = require_project_access(
        db, project_id, current_user.id, "quality.manage",
    )
    report = db.query(DriftReport).filter(
        DriftReport.project_id == project_id,
        DriftReport.id == _id_or_404(report_id),
    ).first()
    if report is None:
        raise HTTPException(404, {"code": "DRIFT_REPORT_NOT_FOUND"})
    if report.proposal_at is not None:
        raise HTTPException(409, {"code": "DRIFT_PROPOSAL_ALREADY_CREATED", "message": "该报告已提交过重训提案"})
    drifted = sorted({
        item.feature_name for item in db.query(DriftReportFeature).filter(
            DriftReportFeature.report_id == report.id,
            DriftReportFeature.signal_kind == "feature_psi",
        ).all()
    })
    proposal_payload = {
        "deployment_id": str(report.deployment_id) if report.deployment_id else None,
        "report_id": str(report.id),
        "model_version_id": str(report.model_version_id) if report.model_version_id else None,
        "report_created_at": report.created_at.isoformat() if report.created_at else None,
        "level": report.level,
        "drifted_features": len(drifted),
    }
    with _audit_service(db).project_action(
        db, request=request, actor=current_user, access=access,
        permission="quality.manage",
        intent=AuditIntent(
            project_id=project_id, action="drift.propose_retrain",
            resource_type="drift_report", resource_id=str(report.id),
            changes={"level": report.level, "drifted_features": len(drifted)},
        ),
        allowed_changes={"level", "drifted_features"},
    ):
        from app.services.approvals import ApprovalError, create_approval

        approval = create_approval(
            db,
            project_id=project_id,
            approval_type="retrain_proposal",
            title=f"重训提案：漂移报告 {str(report.id)[:8]}（{report.level}）",
            payload=proposal_payload,
            initiator_id=current_user.id,
        )
        report.proposal_at = datetime.utcnow()
        report.proposal_by_id = current_user.id
        db.commit()
    from app.services.closed_loop_actions import notify_project_admins

    notified = notify_project_admins(
        db, project_id,
        title=f"重训提案：漂移报告 {str(report.id)[:8]}（{report.level}）",
        body=(
            f"{current_user.username} 基于漂移报告提交了重训提案："
            f"{len(drifted)} 个特征分布偏离训练基线"
            + (f"（{'、'.join(drifted[:5])}{'…' if len(drifted) > 5 else ''}）" if drifted else "")
            + "。漂移是触发信号，是否重训由人工评估；已进统一审批队列。"
        ),
        severity="warning", event_type="drift.retrain_proposal",
        payload={"report_id": str(report.id), "approval_id": str(approval.id)},
    )
    return {
        "report_id": str(report.id),
        "proposal_at": report.proposal_at.isoformat(),
        "approval_id": str(approval.id),
        "notified": notified,
    }


@router.post("/api/projects/{project_id}/drift/scan")
def drift_scan(
    project_id: UUID,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """手动触发一次全平台漂移批检（与定时任务同一实现）。"""
    access: ProjectAccess = require_project_access(
        db, project_id, current_user.id, "quality.manage",
    )
    with _audit_service(db).project_action(
        db, request=request, actor=current_user, access=access,
        permission="quality.manage",
        intent=AuditIntent(
            project_id=project_id, action="drift.scan",
            resource_type="drift_report", resource_id=None,
            changes={"trigger": "manual"},
        ),
        allowed_changes={"trigger"},
    ):
        # 扫描用独立短会话（每个部署一个事务）；先结束本请求会话的只读事务
        db.commit()
        summary = drift.run_drift_scan(session_factory=sessionmaker(bind=db.get_bind()))
    return summary
