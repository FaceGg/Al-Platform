"""Admin endpoints for agent action audit + audit chain verification (S1, B2-08/E10)."""

import csv
import io
from datetime import datetime
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.api.users import get_current_admin
from app.database import get_db
from app.models.agent_audit import AgentActionAudit
from app.models.user import User
from app.services.audit_chain import verify_all
from app.services.platform_audit import PlatformAuditIntent, record_platform_event

router = APIRouter(prefix="/api/admin", tags=["agent-audit"])

# CSV 行数上限（超出截断并在响应头注明——动作审计行含大载荷，全量导出无意义）
CSV_EXPORT_LIMIT = 50_000


@router.get("/audit-chain/verify")
def verify_audit_chain(
    request: Request,
    db: Session = Depends(get_db),
    admin: User = Depends(get_current_admin),
):
    """两表审计链完整性校验（E10）：{table: {chained, unchained, complete, first_break}}。"""
    report = verify_all(db)
    record_platform_event(
        db,
        actor=admin,
        request=request,
        intent=PlatformAuditIntent(
            action="audit.chain.verify",
            resource_type="audit_chain",
            changes={"tables": sorted(report)},
        ),
        result="success",
    )
    db.commit()
    return report


def _filtered_query(
    db: Session,
    *,
    agent_type: str | None,
    status: str | None,
    tool_name: str | None,
    project_id: UUID | None,
    from_time: datetime | None,
    to_time: datetime | None,
):
    query = db.query(AgentActionAudit)
    if agent_type is not None:
        query = query.filter(AgentActionAudit.agent_type == agent_type)
    if status is not None:
        query = query.filter(AgentActionAudit.status == status)
    if tool_name is not None:
        query = query.filter(AgentActionAudit.tool_name == tool_name)
    if project_id is not None:
        query = query.filter(AgentActionAudit.project_id == project_id)
    if from_time is not None:
        query = query.filter(AgentActionAudit.created_at >= from_time)
    if to_time is not None:
        query = query.filter(AgentActionAudit.created_at <= to_time)
    return query


def _payload_chars_value(payload) -> int:
    if isinstance(payload, dict):
        return int(payload.get("payload_chars") or 0)
    return 0


@router.get("/agent-actions")
def list_agent_actions(
    agent_type: str | None = None,
    status: Literal["success", "error", "timeout"] | None = None,
    tool_name: str | None = None,
    project_id: UUID | None = None,
    from_time: datetime | None = None,
    to_time: datetime | None = None,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
    admin: User = Depends(get_current_admin),
):
    """动作审计分页查询（B2-08：按智能体/工具类型/成败筛选）。"""
    query = _filtered_query(
        db, agent_type=agent_type, status=status, tool_name=tool_name,
        project_id=project_id, from_time=from_time, to_time=to_time,
    )
    total = query.count()
    rows = (
        query.order_by(AgentActionAudit.created_at.desc(), AgentActionAudit.id.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    items = []
    for row in rows:
        items.append(
            {
                "id": str(row.id),
                "created_at": row.created_at.isoformat() if row.created_at else None,
                "agent_type": row.agent_type,
                "tool_name": row.tool_name,
                "status": row.status,
                "error_code": row.error_code,
                "duration_ms": row.duration_ms,
                "project_id": str(row.project_id) if row.project_id else None,
                "actor_id": str(row.actor_id) if row.actor_id else None,
                "trace_id": row.trace_id,
                "approval_id": str(row.approval_id) if row.approval_id else None,
                "idempotency_key": row.idempotency_key,
                "repeat_count": row.repeat_count,
                "last_repeat_at": (
                    row.last_repeat_at.isoformat() if row.last_repeat_at else None
                ),
                "usage": row.usage,
                "model_profile": row.model_profile,
                "request_payload": row.request_payload,
                "response_payload": row.response_payload,
            }
        )
    return {"total": total, "items": items}


@router.get("/agent-actions/export.csv")
def export_agent_actions_csv(
    request: Request,
    agent_type: str | None = None,
    status: Literal["success", "error", "timeout"] | None = None,
    tool_name: str | None = None,
    project_id: UUID | None = None,
    from_time: datetime | None = None,
    to_time: datetime | None = None,
    db: Session = Depends(get_db),
    admin: User = Depends(get_current_admin),
):
    """动作审计 CSV 导出（与列表同筛选；行数上限 5 万行，超出截断）。

    载荷列只导 payload_chars——脱敏后完整载荷在列表行展开查看；
    BOM+UTF-8 便于 Excel 直开。
    """
    query = _filtered_query(
        db, agent_type=agent_type, status=status, tool_name=tool_name,
        project_id=project_id, from_time=from_time, to_time=to_time,
    )
    total = query.count()
    rows = (
        query.order_by(AgentActionAudit.created_at.asc(), AgentActionAudit.id.asc())
        .limit(CSV_EXPORT_LIMIT)
        .all()
    )
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow([
        "created_at", "agent_type", "tool_name", "status", "error_code",
        "duration_ms", "project_id", "actor_id", "trace_id", "approval_id",
        "idempotency_key", "repeat_count", "model_profile",
        "request_payload_chars", "response_payload_chars",
    ])
    for row in rows:
        writer.writerow([
            row.created_at.isoformat() if row.created_at else "",
            row.agent_type,
            row.tool_name or "",
            row.status,
            row.error_code or "",
            row.duration_ms if row.duration_ms is not None else "",
            str(row.project_id) if row.project_id else "",
            str(row.actor_id) if row.actor_id else "",
            row.trace_id or "",
            str(row.approval_id) if row.approval_id else "",
            row.idempotency_key or "",
            row.repeat_count,
            row.model_profile or "",
            _payload_chars_value(row.request_payload),
            _payload_chars_value(row.response_payload),
        ])
    record_platform_event(
        db,
        actor=admin,
        request=request,
        intent=PlatformAuditIntent(
            action="agent_action.audit.export",
            resource_type="agent_action_audit",
            changes={"rows": len(rows), "total": total},
        ),
        result="success",
    )
    db.commit()
    buffer.seek(0)
    return StreamingResponse(
        iter(["\ufeff", buffer.getvalue()]),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": "attachment; filename=agent-action-audit.csv",
            **({"X-Truncated-Total": str(total)} if total > len(rows) else {}),
        },
    )
