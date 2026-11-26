"""Audit hash chain over the two audit tables (补齐路线第二批 S1, E10/D14).

每次审计写入在同一事务内 append：取链尾状态行 → seq=last+1 →
entry_hash = sha256(table|seq|prev|核心字段规范 JSON)。存量行（迁移 _113 前）
三列保持 NULL=链前史，verify 计 unchained、不算断点；历史行不做回填改写
（历史记录保留纪律）。已知边界：哈希链检测「修改」与「断链」，不检测
「尾部截断」（无外部锚点的哈希链固有限制，验收口径为篡改定位）。
"""
import hashlib
import json

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.access import AuditEvent
from app.models.agent_audit import AUDIT_CHAIN_TABLES, AuditChainState
from app.models.platform_audit import PlatformAuditEvent

# 核心字段：篡改任一字段都会改变 entry_hash 重算值（changes 规范化 sort_keys）
_CORE_FIELDS = (
    "actor_username",
    "action",
    "resource_type",
    "resource_id",
    "result",
    "request_id",
    "source_ip",
    "error_code",
    "changes",
    "created_at",
)


def _canonical_core(event) -> str:
    payload = {name: getattr(event, name, None) for name in _CORE_FIELDS}
    return json.dumps(
        payload,
        sort_keys=True,
        ensure_ascii=False,
        default=str,
    )


def append(db: Session, table_name: str, event) -> None:
    """Assign chain fields on `event` (caller commits with their transaction)."""
    if table_name not in AUDIT_CHAIN_TABLES:
        raise ValueError(f"table not under audit chain: {table_name}")
    if getattr(event, "entry_hash", None) is not None:
        return  # 幂等：已入链的事件不重复取号

    state = db.execute(
        select(AuditChainState)
        .where(AuditChainState.table_name == table_name)
        .with_for_update()
    ).scalar_one_or_none()
    if state is None:
        state = AuditChainState(table_name=table_name)
        db.add(state)
        seq = 1
        prev_hash = None
    else:
        seq = (state.last_seq or 0) + 1
        prev_hash = state.last_hash

    # 先落行再取哈希：created_at 等是 server_default，不 flush 时实例上是 None，
    # 而 verify 从库里读终值重算——哈希必须基于与库内一致的终值
    db.add(event)
    db.flush()

    entry_hash = hashlib.sha256(
        f"{table_name}|{seq}|{prev_hash or ''}|{_canonical_core(event)}".encode("utf-8")
    ).hexdigest()
    event.chain_seq = seq
    event.prev_hash = prev_hash
    event.entry_hash = entry_hash

    state.last_seq = seq
    state.last_hash = entry_hash
    state.updated_at = func.now()
    # 链三列随调用方 commit 一并 UPDATE 落库（INSERT 已在上方 flush 完成）


def verify(db: Session, table_name: str) -> dict:
    """Walk the chained rows (chain_seq NOT NULL) and locate the first break."""
    if table_name not in AUDIT_CHAIN_TABLES:
        raise ValueError(f"table not under audit chain: {table_name}")

    event_model = {
        "audit_events": AuditEvent,
        "platform_audit_events": PlatformAuditEvent,
    }[table_name]
    event_cls = event_model

    chained = (
        db.execute(
            select(event_cls)
            .where(event_cls.chain_seq.isnot(None))
            .order_by(event_cls.chain_seq.asc())
        )
        .scalars()
        .all()
    )
    unchained = db.execute(
        select(func.count())
        .select_from(event_cls)
        .where(event_cls.chain_seq.is_(None))
    ).scalar() or 0

    first_break = None
    prev_hash = None
    expected_seq = 1
    for event in chained:
        if event.chain_seq != expected_seq:
            first_break = {
                "seq": event.chain_seq,
                "id": str(event.id),
                "reason": "link_mismatch",
            }
            break
        if (event.prev_hash or None) != prev_hash:
            first_break = {
                "seq": event.chain_seq,
                "id": str(event.id),
                "reason": "link_mismatch",
            }
            break
        if event.entry_hash != hashlib.sha256(
            f"{table_name}|{event.chain_seq}|{event.prev_hash or ''}|"
            f"{_canonical_core(event)}".encode("utf-8")
        ).hexdigest():
            first_break = {
                "seq": event.chain_seq,
                "id": str(event.id),
                "reason": "hash_mismatch",
            }
            break
        prev_hash = event.entry_hash
        expected_seq += 1

    return {
        "table": table_name,
        "chained": len(chained),
        "unchained": int(unchained),
        "complete": first_break is None,
        "first_break": first_break,
    }


def verify_all(db: Session) -> dict:
    return {table_name: verify(db, table_name) for table_name in AUDIT_CHAIN_TABLES}
