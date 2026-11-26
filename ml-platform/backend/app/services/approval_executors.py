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


class ModelReleaseExecutor:
    """模型发布（B2-03/G2/G3）：批准 → 影子窗口前置 → 预授权或灰度链。

    门禁检查（release_checks）在 release-request 端点创建审批单时已评估落档；
    本执行器在批准时执行发布动作（create_candidate 灰度链）。
    """

    def fingerprint(self, db: Session, payload: dict) -> str:
        from app.services.approvals import fingerprint_payload

        return fingerprint_payload({
            "deployment_id": payload.get("deployment_id"),
            "model_version_id": payload.get("model_version_id"),
        })

    def validate_create(self, db: Session, payload: dict) -> None:
        from app.services.approvals import ApprovalError
        from app.services.release_governance import evaluate_release_gates

        deployment, version = _release_subjects(db, payload)
        from app.models.approvals import ApprovalRequest

        approval = ApprovalRequest(
            project_id=deployment.project_id, type="model_release",
            title="release-gates-probe", payload={},
            payload_fingerprint="0" * 64,
            created_by_id=None, expires_at=_datetime_now(),
        )
        db.add(approval)
        db.flush()
        checks = evaluate_release_gates(db, deployment=deployment, version=version,
                                        approval=approval)
        db.flush()
        for check in checks:
            db.delete(check)
        db.delete(approval)
        db.flush()
        failed = [c for c in checks if c.verdict == "failed"]
        if failed:
            raise ApprovalError(
                "RELEASE_GATE_FAILED",
                "、".join(f"{c.check_key}" for c in failed),
            )

    def on_reject(self, db: Session, *, approval: ApprovalRequest, note: str) -> None:
        return None

    def perform(self, db: Session, *, approval: ApprovalRequest, actor_id) -> dict:
        """批准后发布：预授权命中 → 直接灰度（留痕）；否则按发布单走灰度链。"""
        from app.services.release_governance import (
            GovernanceError,
            check_preauthorization,
            shadow_window_gate,
        )

        payload = approval.payload or {}
        deployment, version = _release_subjects(db, payload)
        # G3 影子观察窗前置（不足可经 quality.manage 强制接管——在 API 层放行）
        gate = shadow_window_gate(db, deployment=deployment)
        if not gate.get("passed"):
            raise ValueError(
                "shadow window gate not passed: " + str(gate.get("reason"))
            )
        auth_id = payload.get("preauthorization_id")
        if auth_id:
            check_preauthorization(
                db, auth_id=_uuid.UUID(str(auth_id)),
                deployment_id=deployment.id,
                gates_fingerprint=str(payload.get("acceptance_gates_fingerprint") or ""),
                applicant_id=approval.created_by_id,
            )
        from app.services.inference_rollout import InferenceRolloutService

        service = InferenceRolloutService(db)
        rollout = service.create_candidate(
            db,
            deployment.id,
            actor_id,
            targets=[{
                "model_version_id": version.id,
                "weight_bps": int(payload.get("weight_bps") or 10000),
            }],
            strategy=str(payload.get("strategy") or "canary"),
        )
        return {
            "rollout_id": str(rollout.id),
            "released_via": "preauthorization" if auth_id else "approval",
        }


def _release_subjects(db: Session, payload: dict):
    import uuid as _uuid

    from app.models.model_registry import InferenceDeployment, ModelVersion
    from app.services.approvals import ApprovalError

    deployment_id = payload.get("deployment_id")
    version_id = payload.get("model_version_id")
    if not deployment_id or not version_id:
        raise ApprovalError("RELEASE_PAYLOAD_INCOMPLETE")
    deployment = db.get(InferenceDeployment, _uuid.UUID(str(deployment_id)))
    version = db.get(ModelVersion, _uuid.UUID(str(version_id)))
    if deployment is None or version is None:
        raise ApprovalError("RELEASE_SUBJECT_NOT_FOUND")
    return deployment, version


class ExemptionExecutor:
    """发布豁免（E01）：仅「终验通过、仅不回退未过」可发起；理由≥10 字；
    豁免人≠发起人（四眼在队列层强制）。其余硬检查不可豁免。"""

    def fingerprint(self, db: Session, payload: dict) -> str:
        from app.services.approvals import fingerprint_payload

        return fingerprint_payload(payload)

    def validate_create(self, db: Session, payload: dict) -> None:
        from app.services.approvals import ApprovalError

        note = str(payload.get("reason") or "")
        if len(note.strip()) < 10:
            raise ApprovalError("EXEMPTION_REASON_TOO_SHORT")
        latest = _latest_release_checks(db, payload)
        if latest is None:
            raise ApprovalError("EXEMPTION_NO_RELEASE_CHECKS")
        verdicts = {c.check_key: c.verdict for c in latest}
        hard_failures = [
            key for key, verdict in verdicts.items()
            if verdict == "failed" and key != "no_regression"
        ]
        if "blind_final_validation" in verdicts and verdicts["blind_final_validation"] != "passed":
            raise ApprovalError("EXEMPTION_FINAL_VALIDATION_NOT_PASSED")
        if hard_failures:
            raise ApprovalError("EXEMPTION_HARD_CHECKS_FAILED")

    def on_reject(self, db: Session, *, approval: ApprovalRequest, note: str) -> None:
        return None

    def perform(self, db: Session, *, approval: ApprovalRequest, actor_id) -> dict:
        return {"exemption_recorded": True,
                "release_checks_kept": bool((approval.payload or {}).get("release_approval_id"))}


def _latest_release_checks(db: Session, payload: dict):
    import uuid as _uuid

    from app.models.release_governance import ReleaseCheck

    release_approval_id = payload.get("release_approval_id")
    if not release_approval_id:
        return None
    return (
        db.query(ReleaseCheck)
        .filter(ReleaseCheck.approval_id == _uuid.UUID(str(release_approval_id)))
        .all()
    )


def _datetime_now():
    from datetime import datetime

    return datetime.utcnow()


# 类型 → 执行器实例（新类型在此注册一项）
_EXECUTORS = {
    "retrain_proposal": RetrainProposalExecutor(),
    "disposition": DispositionExecutor(),
    "model_release": ModelReleaseExecutor(),
    "exemption": ExemptionExecutor(),
}

_RESERVED_TYPES = ("recipe_change",)


def get_executor(approval_type: str):
    """保留类型返回 None → 队列侧给 EXECUTOR_NOT_READY（诚实降级，不假装执行）。"""
    return _EXECUTORS.get(approval_type)
