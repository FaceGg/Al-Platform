# -*- coding: utf-8 -*-
"""S1 approval queue + agent action audit + audit hash chain (B2-07/B2-08/E10).

补齐路线第二批 S1（技术方案-补齐路线第二批 §1 R0，D4/D11/D14/D18）：
- 两张审计表（audit_events / platform_audit_events）各加哈希链三列
  （chain_seq/prev_hash/entry_hash，nullable——存量行保持 NULL=链前史，
  校验端点计 unchained，不算断点；历史行不做回填改写）；
- audit_chain_state：每表链尾状态（append 在同一事务内取号）；
- agent_action_audits：LLM/Agent 每次工具调用的动作审计（七键脱敏、
  幂等键重复沿用原动作 repeat_count）；
- approval_requests：统一四眼审批队列（四类目标类型 + 豁免的唯一状态机；
  存量四处审批原样保留、只读投影收敛）。

全部为加列/新建，不动数据。SQLite batch；PG 原生 ALTER。
"""
import sqlalchemy as sa
from alembic import op

revision = "20261126_113"
down_revision = "20261126_112"
branch_labels = None
depends_on = None


def _column_names(table: str) -> set:
    inspector = sa.inspect(op.get_bind())
    return {col["name"] for col in inspector.get_columns(table)}


def _constraint_names(table: str) -> set:
    inspector = sa.inspect(op.get_bind())
    names: set = set()
    for kind in ("check_constraints", "foreign_keys", "unique_constraints"):
        for constraint in getattr(inspector, f"get_{kind}")(table):
            names.add(constraint.get("name"))
    return names


def _index_names(table: str) -> set:
    inspector = sa.inspect(op.get_bind())
    return {index["name"] for index in inspector.get_indexes(table)}


def _table_names() -> set:
    inspector = sa.inspect(op.get_bind())
    return set(inspector.get_table_names())


def upgrade() -> None:
    # 1) 两张审计表加哈希链三列（nullable，不加 CHECK/索引——链列只顺序追加读）
    with op.batch_alter_table("audit_events") as batch:
        batch.add_column(sa.Column("chain_seq", sa.BigInteger(), nullable=True))
        batch.add_column(sa.Column("prev_hash", sa.String(length=64), nullable=True))
        batch.add_column(sa.Column("entry_hash", sa.String(length=64), nullable=True))
    with op.batch_alter_table("platform_audit_events") as batch:
        batch.add_column(sa.Column("chain_seq", sa.BigInteger(), nullable=True))
        batch.add_column(sa.Column("prev_hash", sa.String(length=64), nullable=True))
        batch.add_column(sa.Column("entry_hash", sa.String(length=64), nullable=True))

    # 2) 链尾状态表
    op.create_table(
        "audit_chain_state",
        sa.Column("table_name", sa.String(length=64), primary_key=True),
        sa.Column("last_seq", sa.BigInteger(), nullable=True),
        sa.Column("last_hash", sa.String(length=64), nullable=True),
        sa.Column(
            "updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False
        ),
    )

    # 3) 统一审批队列（D4）：先建——动作审计表有 FK 指向它
    op.create_table(
        "approval_requests",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "project_id", sa.Uuid(),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("type", sa.String(length=16), nullable=False),
        sa.Column("title", sa.String(length=256), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("payload_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column(
            "created_by_id", sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "decided_by_id", sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("decided_at", sa.DateTime(), nullable=True),
        sa.Column("decision_note", sa.Text(), nullable=True),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("reminded_at", sa.DateTime(), nullable=True),
        sa.Column("execution_status", sa.String(length=16), nullable=False),
        sa.Column("execution_ref", sa.JSON(), nullable=True),
        sa.Column("execution_error", sa.Text(), nullable=True),
        sa.Column("trace_id", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "type IN ('disposition', 'retrain_proposal', 'model_release', "
            "'recipe_change', 'exemption')",
            name="ck_approval_requests_type",
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'approved', 'rejected', 'expired', "
            "'invalidated', 'cancelled')",
            name="ck_approval_requests_status",
        ),
        sa.CheckConstraint(
            "execution_status IN ('none', 'succeeded', 'failed')",
            name="ck_approval_requests_execution_status",
        ),
    )
    op.create_index(
        "ix_approval_requests_project_status", "approval_requests",
        ["project_id", "status"],
    )
    op.create_index(
        "ix_approval_requests_status_expires", "approval_requests",
        ["status", "expires_at"],
    )

    # 4) 动作审计表（D11）：幂等键 UNIQUE（nullable 列，NULL 互不冲突，天然支持）
    op.create_table(
        "agent_action_audits",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("trace_id", sa.String(length=64), nullable=True),
        sa.Column(
            "project_id", sa.Uuid(),
            sa.ForeignKey("projects.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "actor_id", sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("agent_type", sa.String(length=32), nullable=False),
        sa.Column("tool_name", sa.String(length=128), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("duration_ms", sa.BigInteger(), nullable=True),
        sa.Column("request_payload", sa.JSON(), nullable=True),
        sa.Column("response_payload", sa.JSON(), nullable=True),
        sa.Column("usage", sa.JSON(), nullable=True),
        sa.Column("model_profile", sa.String(length=128), nullable=True),
        sa.Column(
            "approval_id", sa.Uuid(),
            sa.ForeignKey("approval_requests.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("idempotency_key", sa.String(length=128), nullable=True),
        sa.Column("repeat_count", sa.BigInteger(), nullable=False),
        sa.Column("last_repeat_at", sa.DateTime(), nullable=True),
        sa.CheckConstraint(
            "agent_type IN ('chat', 'chat_tool', 'agent_pipeline', "
            "'kg_extract', 'audit_qa', 'other')",
            name="ck_agent_action_audits_agent_type",
        ),
        sa.CheckConstraint(
            "status IN ('success', 'error', 'timeout')",
            name="ck_agent_action_audits_status",
        ),
        sa.UniqueConstraint(
            "idempotency_key", name="uq_agent_action_audits_idempotency_key"
        ),
    )
    op.create_index(
        "ix_agent_action_audits_created_at", "agent_action_audits", ["created_at"]
    )
    op.create_index(
        "ix_agent_action_audits_trace_id", "agent_action_audits", ["trace_id"]
    )
    op.create_index(
        "ix_agent_action_audits_agent_status", "agent_action_audits",
        ["agent_type", "status"],
    )

    # 旧数据保留断言：审计表行不动（只加列）；新表/列/约束/索引就位。
    assert {"chain_seq", "prev_hash", "entry_hash"} <= _column_names("audit_events")
    assert {"chain_seq", "prev_hash", "entry_hash"} <= _column_names(
        "platform_audit_events"
    )
    assert "audit_chain_state" in _table_names()
    assert "approval_requests" in _table_names()
    assert "agent_action_audits" in _table_names()
    assert "ck_approval_requests_type" in _constraint_names("approval_requests")
    assert "uq_agent_action_audits_idempotency_key" in _constraint_names(
        "agent_action_audits"
    )
    assert "ix_agent_action_audits_agent_status" in _index_names(
        "agent_action_audits"
    )
    assert "ix_approval_requests_status_expires" in _index_names("approval_requests")


def downgrade() -> None:
    op.drop_index(
        "ix_agent_action_audits_agent_status", table_name="agent_action_audits"
    )
    op.drop_index("ix_agent_action_audits_trace_id", table_name="agent_action_audits")
    op.drop_index(
        "ix_agent_action_audits_created_at", table_name="agent_action_audits"
    )
    op.drop_table("agent_action_audits")
    op.drop_index(
        "ix_approval_requests_status_expires", table_name="approval_requests"
    )
    op.drop_index(
        "ix_approval_requests_project_status", table_name="approval_requests"
    )
    op.drop_table("approval_requests")
    op.drop_table("audit_chain_state")
    with op.batch_alter_table(
        "platform_audit_events",
        naming_convention={
            "fk": "fk_%(table_name)s_%(column_0_N_name)s_%(referred_table_name)s",
        },
    ) as batch:
        batch.drop_column("entry_hash")
        batch.drop_column("prev_hash")
        batch.drop_column("chain_seq")
    with op.batch_alter_table(
        "audit_events",
        naming_convention={
            "fk": "fk_%(table_name)s_%(column_0_N_name)s_%(referred_table_name)s",
        },
    ) as batch:
        batch.drop_column("entry_hash")
        batch.drop_column("prev_hash")
        batch.drop_column("chain_seq")
