"""Unified approval queue (补齐路线第二批 S1, B2-07/B2-10).

统一四眼审批中心（技术方案-补齐路线第二批 §2，D1–D9）：
- approval_requests 是路线四类目标类型（异常处置/发起重训/模型发布/工艺配方变更）
  + 豁免的唯一状态机（D1）；四处存量审批（AgentTask 审查/模型版本/模型卡/技能修订）
  原样保留，统一中心经只读投影端点收敛呈现（D10）。
- 四眼强制 = 批准/驳回动作要求持有 approval.approve 且 actor != 发起人（D3）。
- 72h 有效期（可配）+ 过期回收 + 过期前 12h 提醒（D6）；拒绝水位线（D9）与
  内容指纹（D5）落在 payload 与 decision_note 上，不另建表（轨迹走 audit_events）。
"""
import uuid

from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    JSON,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import UUID

from app.database import Base

# 队列类型枚举（D2）：S1 落地生产者的只有 disposition / retrain_proposal；
# model_release 随 S2b（B2-03/G2）、recipe_change 随 B4-04、exemption 随 B2-03 接入。
APPROVAL_TYPES = (
    "disposition",
    "retrain_proposal",
    "model_release",
    "recipe_change",
    "exemption",
)

# 状态机（D4）：invalidated = 批准时内容指纹复算不匹配（E06「批的是 A、发的是 B」防线）
APPROVAL_STATUSES = (
    "pending",
    "approved",
    "rejected",
    "expired",
    "invalidated",
    "cancelled",
)

EXECUTION_STATUSES = ("none", "succeeded", "failed")


class ApprovalRequest(Base):
    __tablename__ = "approval_requests"
    __table_args__ = (
        CheckConstraint(
            "type IN ('disposition', 'retrain_proposal', 'model_release', "
            "'recipe_change', 'exemption')",
            name="ck_approval_requests_type",
        ),
        CheckConstraint(
            "status IN ('pending', 'approved', 'rejected', 'expired', "
            "'invalidated', 'cancelled')",
            name="ck_approval_requests_status",
        ),
        CheckConstraint(
            "execution_status IN ('none', 'succeeded', 'failed')",
            name="ck_approval_requests_execution_status",
        ),
        Index("ix_approval_requests_project_status", "project_id", "status"),
        Index("ix_approval_requests_status_expires", "status", "expires_at"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id = Column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
    )
    type = Column(String(16), nullable=False)
    title = Column(String(256), nullable=False)
    payload = Column(JSON, nullable=False, default=dict)
    payload_fingerprint = Column(String(64), nullable=False)
    status = Column(String(16), nullable=False, default="pending")
    created_by_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    decided_by_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    decided_at = Column(DateTime, nullable=True)
    decision_note = Column(Text, nullable=True)
    expires_at = Column(DateTime, nullable=False)
    reminded_at = Column(DateTime, nullable=True)
    execution_status = Column(String(16), nullable=False, default="none")
    execution_ref = Column(JSON, nullable=True)
    execution_error = Column(Text, nullable=True)
    trace_id = Column(String(64), nullable=False, default=lambda: uuid.uuid4().hex)
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    updated_at = Column(DateTime, nullable=False, server_default=func.now())
