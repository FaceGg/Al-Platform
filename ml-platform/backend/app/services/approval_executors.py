"""Approval executor registry (补齐路线第二批 S1, D5/D7).

按类型注册审批执行器：fingerprint（当前状态指纹，E06 批准时复算）、
on_reject（拒绝侧回调，E05 水位线）、perform（批准后平台动作）。
新类型接入 = 注册一项，不改队列（decide/perform 通用逻辑不变）。
S1 落地 disposition 与 retrain_proposal（R4）；model_release / recipe_change /
exemption 为保留类型（生产者随 S2b / B4-04 接入）。
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.models.approvals import ApprovalRequest


class RetrainProposalExecutor:
    """发起重训提案（E05 拒绝水位线；批准触发部署绑定的闭环重训轮）。"""

    def fingerprint(self, db: Session, payload: dict) -> str:
        """身份对指纹：(deployment_id, report_id)——载荷被换即失效（E06）。"""
        from app.services.approvals import fingerprint_payload

        return fingerprint_payload({
            "deployment_id": payload.get("deployment_id"),
            "report_id": payload.get("report_id"),
        })

    def validate_create(self, db: Session, payload: dict) -> None:
        from app.services.approvals import ApprovalError, WATERMARK

        count = _proposal_sample_count(db, payload)
        watermark = _latest_rejection_watermark(db, payload)
        if watermark is not None and count <= watermark["sample_count"]:
            raise ApprovalError(WATERMARK)

    def on_reject(self, db: Session, *, approval: ApprovalRequest, note: str) -> None:
        count = _proposal_sample_count(db, approval.payload)
        approval.payload = dict(approval.payload or {}) | {
            "watermark": {
                "sample_count": count,
                "recorded_at": approval.decided_at.isoformat()
                if approval.decided_at
                else None,
            }
        }

    def perform(self, db: Session, *, approval: ApprovalRequest, actor_id) -> dict:
        """批准 → 经部署绑定的闭环配置触发重训轮（D7/D9；未绑定闭环的部署
        诚实执行失败——重训合同依赖闭环配置的数据集与目标列，凭空构建是
        假执行）。"""
        from app.models.demo_loop import DemoLoopConfig
        from app.services.demo_loop import DemoLoopService

        deployment_id = (approval.payload or {}).get("deployment_id")
        if not deployment_id:
            raise ValueError("payload missing deployment_id")
        import uuid as _uuid

        if not isinstance(deployment_id, _uuid.UUID):
            deployment_id = _uuid.UUID(str(deployment_id))
        config = (
            db.query(DemoLoopConfig)
            .filter(DemoLoopConfig.deployment_id == deployment_id)
            .first()
        )
        if config is None:
            raise ValueError("deployment has no closed-loop retrain config")
        service = DemoLoopService(db)
        return service.trigger_retrain_from_approval(config, actor_id)


def _proposal_sample_count(db: Session, payload: dict) -> int:
    """该部署自报告产出时刻起的推理结果明细行数（D9 口径，按 occurred_at 复算）。"""
    import uuid as _uuid
    from datetime import datetime

    from app.models.inference_result import InferenceResult

    deployment_id = payload.get("deployment_id")
    report_created_at = payload.get("report_created_at")
    if not deployment_id:
        return 0
    query = db.query(InferenceResult).filter(
        InferenceResult.deployment_id
        == (_uuid.UUID(str(deployment_id)) if not isinstance(deployment_id, _uuid.UUID) else deployment_id)
    )
    if report_created_at:
        try:
            anchor = datetime.fromisoformat(str(report_created_at))
        except ValueError:
            return 0
        query = query.filter(InferenceResult.occurred_at >= anchor)
    return int(query.count())


def _latest_rejection_watermark(db: Session, payload: dict) -> dict | None:
    from app.models.approvals import ApprovalRequest

    deployment_id = payload.get("deployment_id")
    if not deployment_id:
        return None
    rows = (
        db.query(ApprovalRequest)
        .filter(
            ApprovalRequest.type == "retrain_proposal",
            ApprovalRequest.status == "rejected",
        )
        .order_by(ApprovalRequest.decided_at.desc())
        .limit(20)
        .all()
    )
    for row in rows:
        row_payload = row.payload or {}
        if str(row_payload.get("deployment_id")) == str(deployment_id):
            watermark = row_payload.get("watermark") or {}
            if watermark.get("sample_count") is not None:
                return watermark
    return None


class DispositionExecutor:
    """异常处置（D8）：critical 关闭走审批；执行器复用 transition_alert 关闭。"""

    def fingerprint(self, db: Session, payload: dict) -> str:
        """状态型指纹：(alert_id, alert 当前状态)——创建后预警又流转/被关闭
        会让批准时的复算不匹配 → invalidated（E06 的具体形态）。"""
        from app.services.approvals import fingerprint_payload

        alert = _disposition_alert(db, payload)
        status = alert.status if alert is not None else None
        return fingerprint_payload({
            "alert_id": payload.get("alert_id"),
            "alert_status": status,
        })

    def validate_create(self, db: Session, payload: dict) -> None:
        from app.models.quality_alerts import ALERT_RESOLUTIONS
        from app.services.approvals import ApprovalError
        from app.services.quality_alerts import ALERT_STATUS_FLOW

        alert = _disposition_alert(db, payload)
        if alert is None:
            raise ApprovalError("DISPOSITION_ALERT_NOT_FOUND")
        if "closed" not in ALERT_STATUS_FLOW.get(alert.status, set()):
            raise ApprovalError("DISPOSITION_TRANSITION_INVALID")
        resolution = payload.get("resolution") or "confirmed_issue"
        if resolution not in ALERT_RESOLUTIONS:
            raise ApprovalError("DISPOSITION_RESOLUTION_INVALID")

    def on_reject(self, db: Session, *, approval: ApprovalRequest, note: str) -> None:
        return None

    def perform(self, db: Session, *, approval: ApprovalRequest, actor_id) -> dict:
        from app.services.quality_alerts import transition_alert

        alert = _disposition_alert(db, approval.payload)
        if alert is None:
            raise ValueError("alert no longer exists")
        resolution = (approval.payload or {}).get("resolution") or "confirmed_issue"
        transition_alert(
            db,
            alert,
            "closed",
            actor_id=actor_id,
            resolution=resolution,
            note="审批通过关闭（" + str(approval.id) + "）",
        )
        return {"alert_id": str(alert.id), "closed": True}


def _disposition_alert(db: Session, payload: dict):
    import uuid as _uuid
    from sqlalchemy import select as _select

    from app.models.quality_alerts import QualityAlert

    alert_id = payload.get("alert_id")
    if not alert_id:
        return None
    if not isinstance(alert_id, _uuid.UUID):
        try:
            alert_id = _uuid.UUID(str(alert_id))
        except (TypeError, ValueError):
            return None
    return db.execute(
        _select(QualityAlert).where(QualityAlert.id == alert_id)
    ).scalar_one_or_none()


# 类型 → 执行器实例（新类型在此注册一项）
_EXECUTORS = {
    "retrain_proposal": RetrainProposalExecutor(),
    "disposition": DispositionExecutor(),
}

_RESERVED_TYPES = ("model_release", "recipe_change", "exemption")


def get_executor(approval_type: str):
    """保留类型返回 None → 队列侧给 EXECUTOR_NOT_READY（诚实降级，不假装执行）。"""
    return _EXECUTORS.get(approval_type)
