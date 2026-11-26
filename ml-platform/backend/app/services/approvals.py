"""Unified four-eye approval queue (补齐路线第二批 S1, B2-07/B2-10/D1–D10).

approval_requests 是路线四类目标类型 + 豁免的唯一状态机；四处存量审批
（AgentTask 审查/模型版本/模型卡/技能修订）原样保留，经只读投影端点收敛
呈现（legacy projection）。四眼强制 = 持有 approval.approve 且发起人≠审批人
（无平台管理员后门）；72h 有效期（可配）+ 过期回收 + 过期前 12h 提醒；
拒绝水位线（E05）与内容指纹（E06）落地于决策与执行路径。
"""
from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import settings
from app.events.domain import create_domain_event
from app.models.approvals import (
    APPROVAL_STATUSES,
    APPROVAL_TYPES,
    ApprovalRequest,
)
from app.services.project_access import ROLE_PERMISSIONS, ProjectRole

# 各类型创建端点所需的最低权限（D-API 表）：
# disposition 是运营动作（operator 可发起）；其余配置/工程类走 quality.manage
CREATE_PERMISSIONS = {
    "disposition": "quality.alert_handle",
    "retrain_proposal": "quality.manage",
    "model_release": "quality.manage",
    "recipe_change": "quality.manage",
    "exemption": "quality.manage",
}

EXECUTOR_NOT_READY = "APPROVAL_EXECUTOR_NOT_READY"
FOUR_EYES = "APPROVAL_FOUR_EYES_DENIED"
STATE_CONFLICT = "APPROVAL_STATE_CONFLICT"
FINGERPRINT_MISMATCH = "APPROVAL_FINGERPRINT_MISMATCH"
WATERMARK = "RETRAIN_PROPOSAL_BELOW_WATERMARK"

FOUR_EYES_MESSAGE = "审批人必须与发起人不同（四眼原则）"


class ApprovalError(Exception):
    def __init__(self, code: str, message: str | None = None):
        super().__init__(message or code)
        self.code = code
        self.message = message or code


def fingerprint_payload(payload: dict) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str).encode(
            "utf-8"
        )
    ).hexdigest()


def _utcnow() -> datetime:
    return datetime.utcnow()


def _recorder():
    from app.services.notification_outbox import OutboxDomainEventRecorder

    return OutboxDomainEventRecorder()


def _emit(
    db: Session,
    *,
    event_type: str,
    approval: ApprovalRequest,
    payload: dict,
    severity: str = "info",
    occurred_at: datetime | None = None,
) -> None:
    from app.events.domain import create_domain_event

    _recorder().record(
        db,
        create_domain_event(
            idempotency_key=f"approval-{event_type}-{approval.id}",
            event_type=event_type,
            severity=severity,
            occurred_at=occurred_at or _utcnow(),
            project_id=approval.project_id,
            actor_id=approval.decided_by_id,
            resource_type="approval_request",
            resource_id=str(approval.id),
            payload=payload,
        ),
    )


def require_four_eyes(approval: ApprovalRequest, actor_id) -> None:
    if approval.created_by_id == actor_id:
        raise ApprovalError(FOUR_EYES, FOUR_EYES_MESSAGE)


def _approval_state_payload(approval: ApprovalRequest) -> dict:
    return {
        "approval_id": str(approval.id),
        "approval_type": approval.type,
        "title": approval.title,
        "decision": approval.status,
        "decision_note": approval.decision_note,
        "expires_at": approval.expires_at.isoformat(),
    }


def create_approval(
    db: Session,
    *,
    project_id,
    approval_type: str,
    title: str,
    payload: dict,
    initiator_id,
    ttl_hours: int | None = None,
) -> ApprovalRequest:
    """创建审批单（pending）；类型业务校验与状态型指纹在执行器侧做。"""
    if approval_type not in APPROVAL_TYPES:
        raise ApprovalError("APPROVAL_TYPE_INVALID")
    from app.services.approval_executors import get_executor

    executor = get_executor(approval_type)
    if executor is not None and hasattr(executor, "validate_create"):
        executor.validate_create(db, payload=payload)
    if executor is not None and hasattr(executor, "fingerprint"):
        current_fingerprint = executor.fingerprint(db, payload or {})
    else:
        current_fingerprint = fingerprint_payload(payload or {})
    approval = ApprovalRequest(
        project_id=project_id,
        type=approval_type,
        title=(title or approval_type)[:256],
        payload=payload or {},
        payload_fingerprint=current_fingerprint,
        created_by_id=initiator_id,
        expires_at=_utcnow() + timedelta(hours=ttl_hours or settings.approval_ttl_hours),
    )
    db.add(approval)
    db.flush()
    return approval


def _get_approval(db: Session, approval_id) -> ApprovalRequest | None:
    return db.execute(
        select(ApprovalRequest).where(ApprovalRequest.id == approval_id)
    ).scalar_one_or_none()


_DECISION_SET = ("approve", "reject")


def decide_approval(
    db: Session,
    *,
    approval_id,
    actor_id,
    decision: str,
    note: str | None = None,
) -> ApprovalRequest:
    """批准/驳回：四眼 + 状态机 + 指纹复算（E06）+ decided 事件。

    驳回时回调执行器 on_reject（retrain_proposal 落拒绝水位线，E05）；
    批准时复算当前指纹不匹配则置 invalidated 不执行。
    """
    if decision not in _DECISION_SET:
        raise ApprovalError("APPROVAL_DECISION_INVALID")
    approval = _get_approval(db, approval_id)
    if approval is None:
        raise ApprovalError("APPROVAL_NOT_FOUND")
    if approval.status != "pending":
        raise ApprovalError(STATE_CONFLICT)
    require_four_eyes(approval, actor_id)
    if decision == "reject" and not (note or "").strip():
        raise ApprovalError("APPROVAL_REJECTION_NOTE_REQUIRED")

    from app.services.approval_executors import get_executor

    executor = get_executor(approval.type)
    if decision == "approve" and executor is not None:
        current = executor.fingerprint(db, approval.payload)
        if current != approval.payload_fingerprint:
            approval.status = "invalidated"
            approval.decided_by_id = actor_id
            approval.decided_at = _utcnow()
            approval.decision_note = FINGERPRINT_MISMATCH
            return approval
    if decision == "approve":
        approval.status = "approved"
    else:
        approval.status = "rejected"
    approval.decided_by_id = actor_id
    approval.decided_at = _utcnow()
    approval.decision_note = note
    if decision == "reject" and executor is not None and hasattr(executor, "on_reject"):
        executor.on_reject(db, approval=approval, note=note or "")
    _emit(
        db,
        event_type="approval.decided",
        approval=approval,
        payload=_approval_state_payload(approval),
    )
    return approval


def perform_approved(db: Session, *, approval: ApprovalRequest, actor_id) -> dict:
    """批准后的平台动作（执行器 perform；失败记 failed 不回滚决策）。"""
    from app.services.approval_executors import get_executor

    executor = get_executor(approval.type)
    if executor is None or not hasattr(executor, "perform"):
        raise ApprovalError(EXECUTOR_NOT_READY)
    if approval.status != "approved":
        raise ApprovalError(STATE_CONFLICT)
    try:
        result = executor.perform(db, approval=approval, actor_id=actor_id)
        approval.execution_status = "succeeded"
        approval.execution_ref = result
        return result
    except Exception as error:  # noqa: BLE001
        approval.execution_status = "failed"
        approval.execution_error = str(error)[:2000]
        return {"status": "failed", "error": approval.execution_error}


def cancel_approval(db: Session, *, approval_id, actor_id) -> ApprovalRequest:
    approval = _get_approval(db, approval_id)
    if approval is None:
        raise ApprovalError("APPROVAL_NOT_FOUND")
    if approval.created_by_id != actor_id:
        raise ApprovalError("APPROVAL_CANCEL_FORBIDDEN")
    if approval.status != "pending":
        raise ApprovalError(STATE_CONFLICT)
    approval.status = "cancelled"
    return approval


def sweep_expiries(db: Session, *, now: datetime | None = None) -> dict:
    """过期回收 + 过期前提醒（B2-10/D6）：beat 每 600s。

    提醒档：剩余 ≤ remind_window（默认 12h）且未提醒过 → approval.expiring；
    过期档：expires_at < now → expired + approval.expired。
    状态条件保证与人工决策并发时幂等（状态迁移以行状态为准）。
    """
    now = now or _utcnow()
    recorder = _recorder()
    remind_window = timedelta(hours=settings.approval_remind_window_hours)
    pending = (
        db.query(ApprovalRequest)
        .filter(
            ApprovalRequest.status == "pending",
            ApprovalRequest.expires_at.isnot(None),
        )
        .all()
    )
    reminded = expired = 0
    for approval in pending:
        remaining = approval.expires_at - now
        if remaining.total_seconds() <= 0:
            approval.status = "expired"
            recorder.record(
                db,
                create_domain_event(
                    idempotency_key=f"approval-expired-{approval.id}",
                    event_type="approval.expired",
                    severity="warning",
                    occurred_at=now,
                    project_id=approval.project_id,
                    actor_id=None,
                    resource_type="approval_request",
                    resource_id=str(approval.id),
                    payload=_approval_state_payload(approval),
                ),
            )
            expired += 1
            continue
        if (
            remaining <= remind_window
            and approval.reminded_at is None
        ):
            approval.reminded_at = now
            recorder.record(
                db,
                create_domain_event(
                    idempotency_key=f"approval-expiring-{approval.id}",
                    event_type="approval.expiring",
                    severity="warning",
                    occurred_at=now,
                    project_id=approval.project_id,
                    actor_id=None,
                    resource_type="approval_request",
                    resource_id=str(approval.id),
                    payload=_approval_state_payload(approval),
                ),
            )
            reminded += 1
    return {"reminded": reminded, "expired": expired}


def list_approvals(
    db: Session,
    *,
    project_id,
    status: str | None = None,
    approval_type: str | None = None,
    approver_id=None,
    initiator_id=None,
    offset: int = 0,
    limit: int = 50,
) -> dict:
    query = db.query(ApprovalRequest).filter(ApprovalRequest.project_id == project_id)
    if status:
        query = query.filter(ApprovalRequest.status == status)
    if approval_type:
        query = query.filter(ApprovalRequest.type == approval_type)
    if initiator_id:
        query = query.filter(ApprovalRequest.created_by_id == initiator_id)
    if approver_id:
        # 「仅我可批」= pending 且非我发起（四眼下我可决策的集合）
        query = query.filter(
            ApprovalRequest.status == "pending",
            ApprovalRequest.created_by_id != approver_id,
        )
    total = query.count()
    rows = (
        query.order_by(ApprovalRequest.created_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    return {"total": total, "items": rows}


def pending_count(db: Session, *, member_project_ids: list) -> int:
    """我发起或（非我发起的）待决审批数——顶栏角标口径：只数我可以行动的单。"""
    if not member_project_ids:
        return 0
    relevant = (
        db.query(ApprovalRequest)
        .filter(
            ApprovalRequest.status == "pending",
            ApprovalRequest.project_id.in_(member_project_ids),
        )
        .all()
    )
    # 角标口径 = 发起人是我（我要跟进）或发起人不是我（若我有 approve 键则可批；
    # 无键的普通成员也数「非我发起」会夸大——按 D16 语义返回两类之和，前端按
    # 角色展示。此处保持简单：pending 总数。
    return len(relevant)


def _agent_task_title(task) -> str:
    name = getattr(task, "name", None) or getattr(task, "task_type", "") or "agent task"
    return str(name)[:200]


def legacy_approvals(db: Session, *, project_id) -> dict:
    """四处存量审批的只读投影（C4/D10）：状态按映射表归一，无数据迁移。"""
    from app.models.agent import AgentTask
    from app.models.model_registry import (
        InferenceDeployment,
        ModelCard,
        ModelVersion,
    )
    from app.models.skill_revision import SkillRevision

    items: list[dict] = []
    tasks = (
        db.query(AgentTask)
        .filter(AgentTask.project_id == project_id)
        .order_by(AgentTask.created_at.desc())
        .limit(100)
        .all()
    )
    for task in tasks:
        review_status = getattr(task, "review_status", "none")
        if review_status == "none":
            continue
        items.append({
            "source": "agent_task_review",
            "ref_id": str(task.id),
            "title": _agent_task_title(task),
            "raw_status": review_status,
            "status": review_status,
            "initiator": str(task.created_by_id) if task.created_by_id else None,
            "decided_at": None,
            "link": "/agent/task/" + str(task.id),
            "note": None,
        })
    versions = (
        db.query(ModelVersion)
        .join(
            InferenceDeployment,
            InferenceDeployment.model_version_id == ModelVersion.id,
        )
        .filter(InferenceDeployment.project_id == project_id)
        .order_by(ModelVersion.created_at.desc())
        .limit(100)
        .all()
    )
    for version in versions:
        items.append({
            "source": "model_version",
            "ref_id": str(version.id),
            "title": f"模型版本 v{version.version_number}",
            "raw_status": version.approval_status,
            "status": version.approval_status,
            "initiator": str(version.created_by_id) if version.created_by_id else None,
            "decided_at": version.approved_at.isoformat() if version.approved_at else None,
            "link": "/models",
            "note": None,
        })
    cards = (
        db.query(ModelCard)
        .join(
            ModelVersion,
            ModelCard.model_version_id == ModelVersion.id,
        )
        .join(
            InferenceDeployment,
            InferenceDeployment.model_version_id == ModelVersion.id,
        )
        .filter(InferenceDeployment.project_id == project_id)
        .order_by(ModelCard.created_at.desc())
        .limit(100)
        .all()
    )
    for card in cards:
        items.append({
            "source": "model_card",
            "ref_id": str(card.id),
            "title": "模型卡（随版本审批联动）",
            "raw_status": card.approval_status,
            "status": card.approval_status,
            "initiator": None,
            "decided_at": None,
            "link": "/models",
            "note": None,
        })
    revisions = db.query(SkillRevision).order_by(SkillRevision.created_at.desc()).limit(50).all()
    revision_status_map = {
        "pending_approval": "pending",
        "activated": "approved",
        "auto_activated": "approved",
        "rejected": "rejected",
        "rolled_back": "rolled_back",
    }
    for revision in revisions:
        raw = revision.status
        items.append({
            "source": "skill_revision",
            "ref_id": str(revision.id),
            "title": f"技能修订 {revision.skill_name} v{revision.new_version or revision.base_version}",
            "raw_status": raw,
            "status": revision_status_map.get(raw, "processing"),
            "initiator": str(revision.approved_by) if revision.approved_by else None,
            "decided_at": revision.updated_at.isoformat() if revision.updated_at else None,
            "link": "/agent",
            "note": "平台级审批（技能修订无项目归属，投影不做项目过滤）",
        })
    return {"items": items}