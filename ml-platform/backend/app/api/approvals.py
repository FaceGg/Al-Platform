"""Unified approval queue endpoints (补齐路线第二批 S1, B2-07/B2-10, §2.3)."""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.api.auth import get_current_user
from app.api.project_security import (
    audit_service,
    require_project_access,
    resolve_project_access,
)
from app.database import get_db
from app.models.access import AuditEvent
from app.models.user import User
from app.services.approvals import (
    ApprovalError,
    CREATE_PERMISSIONS,
    cancel_approval,
    create_approval,
    decide_approval,
    legacy_approvals,
    list_approvals,
    pending_count,
    perform_approved,
)
from app.services.audit import AuditIntent
from app.services.project_access import ROLE_PERMISSIONS

router = APIRouter(tags=["approvals"])


class ApprovalCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: str
    title: str = Field(min_length=1, max_length=256)
    payload: dict = Field(default_factory=dict)
    ttl_hours: int | None = Field(default=None, ge=1, le=24 * 30)


class ApprovalDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    note: str | None = Field(default=None, max_length=2000)


def _approval_view(db: Session, approval, *, can_approve: bool) -> dict:
    return {
        "id": str(approval.id),
        "project_id": str(approval.project_id),
        "type": approval.type,
        "title": approval.title,
        "payload": approval.payload,
        "status": approval.status,
        "decision_note": approval.decision_note,
        "created_by_id": str(approval.created_by_id) if approval.created_by_id else None,
        "decided_by_id": str(approval.decided_by_id) if approval.decided_by_id else None,
        "decided_at": approval.decided_at.isoformat() if approval.decided_at else None,
        "expires_at": approval.expires_at.isoformat() if approval.expires_at else None,
        "reminded_at": approval.reminded_at.isoformat() if approval.reminded_at else None,
        "execution_status": approval.execution_status,
        "execution_ref": approval.execution_ref,
        "execution_error": approval.execution_error,
        "trace_id": approval.trace_id,
        "created_at": approval.created_at.isoformat() if approval.created_at else None,
        "can_approve": can_approve,
    }


def _raise_approval_error(error: ApprovalError) -> None:
    status = 409 if error.code in {
        "APPROVAL_STATE_CONFLICT",
        "APPROVAL_FINGERPRINT_MISMATCH_CODE",
        "RETRAIN_PROPOSAL_BELOW_WATERMARK",
        "APPROVAL_EXECUTOR_NOT_READY",
        "DISPOSITION_TRANSITION_INVALID",
    } else 400
    if error.code == "APPROVAL_NOT_FOUND":
        status = 404
    raise HTTPException(status, {"code": error.code, "message": error.message})


@router.post("/api/projects/{project_id}/approvals")
def create_approval_endpoint(
    project_id: UUID,
    payload_in: ApprovalCreate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """发起审批（D2/D-API 表）：disposition 是运营动作（alert_handle 可发起），
    其余类型走 quality.manage；创建即按执行器做类型业务校验与状态型指纹。"""
    access = require_project_access(
        db, project_id, current_user.id,
        CREATE_PERMISSIONS.get(payload_in.type, "quality.manage"),
    )
    with audit_service(db).project_action(
        db, request=request, actor=current_user, access=access,
        permission=CREATE_PERMISSIONS.get(payload_in.type, "quality.manage"),
        intent=AuditIntent(
            project_id=project_id,
            action="approval.create",
            resource_type="approval_request",
            changes={"type": payload_in.type, "title": payload_in.title},
        ),
        allowed_changes={"type", "title"},
    ):
        try:
            approval = create_approval(
                db,
                project_id=project_id,
                approval_type=payload_in.type,
                title=payload_in.title,
                payload=payload_in.payload,
                initiator_id=current_user.id,
                ttl_hours=payload_in.ttl_hours,
            )
        except ApprovalError as error:
            _raise_approval_error(error)
    return _approval_view(db, approval, can_approve=False)


@router.get("/api/projects/{project_id}/approvals")
def list_approvals_endpoint(
    project_id: UUID,
    status: str | None = Query(default=None),
    type: str | None = Query(default=None),
    mine: str | None = Query(default=None, description="initiated | approvable"),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    require_project_access(db, project_id, current_user.id, "project.read")
    access = resolve_project_access(db, project_id, current_user.id)
    can_approve = access is not None and "approval.approve" in ROLE_PERMISSIONS.get(
        access.role, set()
    )
    initiator_id = current_user.id if mine == "initiated" else None
    approver_id = current_user.id if mine == "approvable" else None
    try:
        result = list_approvals(
            db, project_id=project_id, status=status, approval_type=type,
            approver_id=approver_id, initiator_id=initiator_id,
            offset=offset, limit=limit,
        )
    except ApprovalError as error:
        _raise_approval_error(error)
    return {
        "total": result["total"],
        "items": [
            _approval_view(db, row, can_approve=can_approve and row.created_by_id != current_user.id)
            for row in result["items"]
        ],
    }


def _decide_endpoint(
    db: Session,
    request: Request,
    current_user: User,
    project_id: UUID,
    approval_id: UUID,
    decision: str,
    payload_in: ApprovalDecision,
):
    """决策端点公共体：四眼在服务层二次强制，权限键在 API 层校验。"""
    access = require_project_access(
        db, project_id, current_user.id, "approval.approve",
    )
    with audit_service(db).project_action(
        db, request=request, actor=current_user, access=access,
        permission="approval.approve",
        intent=AuditIntent(
            project_id=project_id,
            action=f"approval.{decision}",
            resource_type="approval_request",
            resource_id=str(approval_id),
            changes={"decision": decision, "note": payload_in.note},
        ),
        allowed_changes={"decision", "note"},
    ):
        try:
            approval = decide_approval(
                db,
                approval_id=approval_id,
                actor_id=current_user.id,
                decision=decision,
                note=payload_in.note,
            )
            if decision == "approve" and approval.status == "approved":
                # 执行器错误与决策错误同通道映射：保留类型无执行器 → 409
                # APPROVAL_EXECUTOR_NOT_READY，而非 500（三批复审 U1）
                perform_approved(db, approval=approval, actor_id=current_user.id)
        except ApprovalError as error:
            _raise_approval_error(error)
    return _approval_view(db, approval, can_approve=False)


@router.post("/api/projects/{project_id}/approvals/{approval_id}/approve")
def approve_approval_endpoint(
    project_id: UUID,
    approval_id: UUID,
    payload_in: ApprovalDecision,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return _decide_endpoint(
        db, request, current_user, project_id, approval_id, "approve", payload_in
    )


@router.post("/api/projects/{project_id}/approvals/{approval_id}/reject")
def reject_approval_endpoint(
    project_id: UUID,
    approval_id: UUID,
    payload_in: ApprovalDecision,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return _decide_endpoint(
        db, request, current_user, project_id, approval_id, "reject", payload_in
    )


@router.post("/api/projects/{project_id}/approvals/{approval_id}/cancel")
def cancel_approval_endpoint(
    project_id: UUID,
    approval_id: UUID,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    require_project_access(db, project_id, current_user.id, "project.read")
    try:
        approval = cancel_approval(
            db, approval_id=approval_id, actor_id=current_user.id,
        )
    except ApprovalError as error:
        _raise_approval_error(error)
    return _approval_view(db, approval, can_approve=False)


@router.get("/api/projects/{project_id}/approvals/{approval_id}")
def approval_detail_endpoint(
    project_id: UUID,
    approval_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    require_project_access(db, project_id, current_user.id, "project.read")
    access = resolve_project_access(db, project_id, current_user.id)
    can_approve = access is not None and "approval.approve" in ROLE_PERMISSIONS.get(
        access.role, set()
    )
    from sqlalchemy import select as _select

    from app.models.approvals import ApprovalRequest as _AR

    approval = db.execute(
        _select(_AR).where(
            _AR.id == approval_id, _AR.project_id == project_id,
        )
    ).scalar_one_or_none()
    if approval is None:
        raise HTTPException(404, {"code": "APPROVAL_NOT_FOUND"})
    trail = (
        db.query(AuditEvent)
        .filter(AuditEvent.request_id.isnot(None))
        .filter(AuditEvent.resource_id == str(approval_id))
        .order_by(AuditEvent.created_at.desc())
        .limit(50)
        .all()
    )
    view = _approval_view(db, approval, can_approve=can_approve)
    view["trail"] = [
        {
            "action": row.action,
            "result": row.result,
            "actor": row.actor_username,
            "created_at": row.created_at.isoformat() if row.created_at else None,
            "changes": row.changes,
        }
        for row in trail
    ]
    return view


@router.get("/api/projects/{project_id}/approvals/legacy")
def legacy_approvals_endpoint(
    project_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """四处存量审批的只读投影（C4/D10）：状态按映射归一，无数据迁移。"""
    require_project_access(db, project_id, current_user.id, "project.read")
    return legacy_approvals(db, project_id=project_id)


@router.get("/api/approvals/pending-count")
def approvals_pending_count_endpoint(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """顶栏角标：我所在项目里 pending 的审批单数（D16 轻量口径）。"""
    from app.models.access import ProjectMember

    memberships = (
        db.query(ProjectMember.project_id)
        .filter(ProjectMember.user_id == current_user.id)
        .all()
    )
    member_project_ids = [row[0] for row in memberships]
    from app.models.project import Project

    owned = (
        db.query(Project.id).filter(Project.owner_id == current_user.id).all()
    )
    member_project_ids.extend(row[0] for row in owned)
    unique_ids = list({pid for pid in member_project_ids})
    return {"count": pending_count(db, member_project_ids=unique_ids)}
