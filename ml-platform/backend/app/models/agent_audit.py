"""Agent action audit + audit hash chain (补齐路线第二批 S1, B2-08/E10).

智能体动作审计（技术方案-补齐路线第二批 §3，D11–D15）：
- agent_action_audits 记录 LLM/Agent 每次工具调用（请求与结果、权限范围、
  耗时、审批关联、错误、追踪 ID）；脱敏机制复用 services/audit.py、键清单
  按路线七键（D12）；幂等键重复沿用原动作（repeat_count，不重复计费）。
- 审计哈希链（E10）：两张审计表（audit_events + platform_audit_events）
  各加 chain_seq/prev_hash/entry_hash 三列（nullable，存量行 NULL=链前史），
  audit_chain_state 记录每表链尾；写入路径在同一事务内 append（D14）。
"""
import uuid

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    JSON,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID

from app.database import Base

# 动作审计的 agent_type 枚举（D11）；新 LLM 功能按需扩枚举 + 迁移
AGENT_ACTION_TYPES = (
    "chat",
    "chat_tool",
    "agent_pipeline",
    "kg_extract",
    "audit_qa",
    "other",
)

AGENT_ACTION_STATUSES = ("success", "error", "timeout")

# 哈希链覆盖的两张审计表（E10 修正：必须同时覆盖，篡改任一张都能定位）
AUDIT_CHAIN_TABLES = ("audit_events", "platform_audit_events")


class AuditChainState(Base):
    __tablename__ = "audit_chain_state"

    table_name = Column(String(64), primary_key=True)
    last_seq = Column(BigInteger, nullable=True)
    last_hash = Column(String(64), nullable=True)
    updated_at = Column(DateTime, nullable=False, server_default=func.now())


class AgentActionAudit(Base):
    __tablename__ = "agent_action_audits"
    __table_args__ = (
        CheckConstraint(
            "agent_type IN ('chat', 'chat_tool', 'agent_pipeline', "
            "'kg_extract', 'audit_qa', 'other')",
            name="ck_agent_action_audits_agent_type",
        ),
        CheckConstraint(
            "status IN ('success', 'error', 'timeout')",
            name="ck_agent_action_audits_status",
        ),
        UniqueConstraint(
            "idempotency_key",
            name="uq_agent_action_audits_idempotency_key",
        ),
        Index("ix_agent_action_audits_created_at", "created_at"),
        Index("ix_agent_action_audits_trace_id", "trace_id"),
        Index("ix_agent_action_audits_agent_status", "agent_type", "status"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    trace_id = Column(String(64), nullable=True)
    project_id = Column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="SET NULL"),
        nullable=True,
    )
    actor_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    agent_type = Column(String(32), nullable=False)
    tool_name = Column(String(128), nullable=True)
    status = Column(String(16), nullable=False)
    error_code = Column(String(64), nullable=True)
    duration_ms = Column(BigInteger, nullable=True)
    request_payload = Column(JSON, nullable=True)
    response_payload = Column(JSON, nullable=True)
    usage = Column(JSON, nullable=True)
    model_profile = Column(String(128), nullable=True)
    approval_id = Column(
        UUID(as_uuid=True),
        ForeignKey("approval_requests.id", ondelete="SET NULL"),
        nullable=True,
    )
    idempotency_key = Column(String(128), nullable=True)
    repeat_count = Column(BigInteger, nullable=False, default=0)
    last_repeat_at = Column(DateTime, nullable=True)
