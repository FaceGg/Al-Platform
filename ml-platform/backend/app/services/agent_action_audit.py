"""Agent action audit (补齐路线第二批 S1, B2-08/D11–D13).

LLM/Agent 每次工具调用的动作审计：请求与结果（七键脱敏 + 长度封顶）、
权限范围（project/actor）、耗时、审批关联、错误、追踪 ID；幂等键重复
沿用原动作（repeat_count+1，不重复计费——审计层语义）。审计失败不得
中断业务：写行用 SAVEPOINT（幂等竞态只回滚审计行），外层再兜底
try/except 落 warning 日志。
"""
import json
import logging
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.agent_audit import AgentActionAudit
from app.services.audit import USAGE_TOKEN_KEYS

logger = logging.getLogger(__name__)

# 脱敏键清单（D12）：按路线 B2-08 七键（不含 audit.py 审计变更用的
# content/data/path——动作审计若抹掉 prompt/回复内容则失去排障价值）。
# 与 audit.py 的差异是**有意决策**，登记于技术方案 D12/§12。
AGENT_ACTION_SENSITIVE_KEYS = frozenset({
    "password",
    "secret",
    "token",
    "webhook",
    "authorization",
    "cookie",
    "api_key",
    "apikey",
})

# 单个字符串值封顶（kg 抽取等场景 messages 可达数十 KB）
_STRING_CAP = 2000
# 列表条数封顶（list_datasets 等工具结果可能返回大集合）
_LIST_CAP = 50

_PURPOSE_AGENT_TYPE_PREFIXES = (
    ("kg", "kg_extract"),
    ("chat_tool", "chat_tool"),
    ("audit", "audit_qa"),
    ("qa", "audit_qa"),
    ("chat", "chat"),
)


def agent_type_for_purpose(purpose: str | None) -> str:
    text = (purpose or "").lower()
    for prefix, agent_type in _PURPOSE_AGENT_TYPE_PREFIXES:
        if text.startswith(prefix):
            return agent_type
    if text.startswith(("s1", "s2", "s3", "s4", "run", "loop", "agent")):
        return "agent_pipeline"
    return "other"


def _truncate(value: Any) -> Any:
    if isinstance(value, str):
        if len(value) > _STRING_CAP:
            return value[:_STRING_CAP] + "…[truncated]"
        return value
    if isinstance(value, dict):
        return {str(key): _truncate(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        items = [_truncate(item) for item in value[:_LIST_CAP]]
        if len(value) > _LIST_CAP:
            items.append(f"…[truncated {len(value) - _LIST_CAP} more]")
        return items
    return value


def _mask(value: Any) -> Any:
    """七键脱敏 + 长度封顶（复用 audit.py 的递归替换机制，键清单独立）。"""
    masked: Any
    if isinstance(value, dict):
        masked = {}
        for key, item in value.items():
            normalized = str(key).lower()
            if any(part in normalized for part in AGENT_ACTION_SENSITIVE_KEYS):
                masked[str(key)] = "***REDACTED***"
            else:
                masked[str(key)] = _mask(item)
        return masked
    return _truncate(value)


def _usage_view(usage: dict | None) -> dict | None:
    """usage 只留 token 用量键（豁免清单）+ 推理文本有无标记（内容不落）。"""
    if not usage:
        return None
    view = {key: usage[key] for key in USAGE_TOKEN_KEYS if key in usage}
    if usage.get("reasoning_content"):
        view["has_reasoning"] = True
    return view or None


def _payload_chars(payload) -> int:
    try:
        return len(json.dumps(payload, ensure_ascii=False, default=str))
    except Exception:
        return 0


def _content_enabled() -> bool:
    try:
        from app.config import settings

        return bool(settings.agent_action_audit_content)
    except Exception:
        return True


def record_agent_action(
    db: Session,
    *,
    agent_type: str,
    tool_name: str | None = None,
    status: str = "success",
    error_code: str | None = None,
    duration_ms: int | None = None,
    project_id=None,
    actor_id=None,
    trace_id: str | None = None,
    approval_id=None,
    idempotency_key: str | None = None,
    request_payload: dict | None = None,
    response_payload: dict | None = None,
    usage: dict | None = None,
    model_profile: str | None = None,
) -> None:
    """记录一次动作审计（同业务事务，不 commit；失败仅告警不抛）。"""
    try:
        content_enabled = _content_enabled()
        request_view = (
            _mask(request_payload)
            if content_enabled
            else {"payload_chars": _payload_chars(request_payload)}
        )
        response_view = (
            _mask(response_payload)
            if content_enabled
            else {"payload_chars": _payload_chars(response_payload)}
        )

        def _insert() -> AgentActionAudit:
            row = AgentActionAudit(
                agent_type=agent_type,
                tool_name=(tool_name or "")[:128] or None,
                status=status,
                error_code=(error_code or "")[:64] or None,
                duration_ms=duration_ms,
                project_id=project_id,
                actor_id=getattr(actor_id, "id", actor_id),
                trace_id=(trace_id or "")[:64] or None,
                approval_id=approval_id,
                idempotency_key=(idempotency_key or "")[:128] or None,
                request_payload=request_view,
                response_payload=response_view,
                usage=_usage_view(usage),
                model_profile=(model_profile or "")[:128] or None,
            )
            db.add(row)
            return row

        if idempotency_key:
            existing = (
                db.query(AgentActionAudit)
                .filter(AgentActionAudit.idempotency_key == idempotency_key)
                .one_or_none()
            )
            if existing is not None:
                existing.repeat_count = (existing.repeat_count or 0) + 1
                existing.last_repeat_at = datetime.utcnow()
                return
        try:
            # SAVEPOINT：幂等键并发首插竞态只回滚审计行，业务事务不受影响
            with db.begin_nested():
                _insert()
        except IntegrityError:
            existing = (
                db.query(AgentActionAudit)
                .filter(AgentActionAudit.idempotency_key == idempotency_key)
                .one_or_none()
            )
            if existing is not None:
                existing.repeat_count = (existing.repeat_count or 0) + 1
                existing.last_repeat_at = datetime.utcnow()
            else:
                logger.warning(
                    "agent action audit insert failed without dedup target"
                )
    except Exception as error:  # noqa: BLE001 - 审计不得中断业务
        logger.warning("agent action audit write failed: %s", error)


def audited_llm_call(func):
    """chat_completion 装饰器：一次网关调用一行动作审计（成功/异常两路）。

    网关既有出口审计（元数据最小化，v0.9 §17.1）保持原样；本表是 B2-08
    的动作审计（记录请求与结果、七键脱敏），两表职责不同。
    """
    import functools
    import time

    @functools.wraps(func)
    def wrapper(db, *, config, messages, purpose="chat", actor=None, **kwargs):
        started = time.perf_counter()
        try:
            reply, usage, reasoning = func(
                db, config=config, messages=messages, purpose=purpose,
                actor=actor, **kwargs,
            )
        except Exception as error:  # noqa: BLE001 - 审计后原样抛出
            record_agent_action(
                db,
                agent_type=agent_type_for_purpose(purpose),
                tool_name=purpose,
                status="timeout" if "timeout" in type(error).__name__.lower() else "error",
                error_code=f"{type(error).__name__}: {error}"[:64],
                duration_ms=int((time.perf_counter() - started) * 1000),
                actor_id=getattr(actor, "id", None),
                request_payload={"messages": messages, "purpose": purpose},
                response_payload=None,
                model_profile=getattr(config, "profile_name", None),
            )
            raise
        record_agent_action(
            db,
            agent_type=agent_type_for_purpose(purpose),
            tool_name=purpose,
            status="success",
            duration_ms=int((time.perf_counter() - started) * 1000),
            actor_id=getattr(actor, "id", None),
            request_payload={"messages": messages, "purpose": purpose},
            response_payload={"reply": reply, "reasoning": bool(reasoning)},
            usage=usage,
            model_profile=getattr(config, "profile_name", None),
        )
        return reply, usage, reasoning

    return wrapper
