"""Streaming chat SSE endpoint with full /chat parameter parity (stream2).

旧 ``/chat/stream`` 只带 message/kb（无思考强度/多模态附件/编排/工具往返）。
本端点与 ``/chat`` 完全同参：KB 检索、白名单工具编排前置（命中→一次性
reply 事件）、三格式流式转发（逐 delta 下发）、上游 usage 里的缓存命中
tokens 提取（上下文容量弹层「平均缓存命中率」数据源）、egress 审计
（destination metadata only，§17.1——流式直连也不能绕过审计）。

事件协议（SSE，data: JSON）：
- {"type": "sources", "sources": [...]}      KB 命中时先行下发引用
- {"type": "delta", "text": "..."}           回答增量
- {"type": "reply", "text": "...", "tool_call": {...}}  工具编排一次性答复
- {"type": "done", "usage": {...}, "cache": {"hit", "prompt"}}  正常结束
- {"type": "error", "message": "..."}        失败（含上游 4xx/5xx 摘要）
- data: [DONE]                               流结束哨兵
"""
import json as _json
import time
from types import SimpleNamespace

from fastapi import APIRouter, Body, Depends, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.api.auth import get_current_user
from app.api.chat import (
    TOOL_HINT_KEYWORDS,
    _assemble_messages,
    _resolve_bound_kb,
    _retrieve_for_chat,
    _validate_attachments,
)
from app.database import get_db
from app.models.user import User
from app.services.llm_gateway import (
    LLMProfileNotFoundError,
    _HTTP_CLIENT,
    _build_llm_request,
    _parse_llm_stream_event,
    resolve_profile,
)

router = APIRouter(prefix="/api/chat", tags=["chat"])


def _sse(payload: dict) -> str:
    return f"data: {_json.dumps(payload, ensure_ascii=False)}\n\n"


def _extract_cache(raw_usage: dict) -> dict | None:
    """从上游原始 usage 提取缓存命中（解析器只归一 prompt/completion）。

    三种供应商形态：
    - deepseek(openai 兼容): prompt_cache_hit_tokens，prompt_tokens 为总输入
    - openai: prompt_tokens_details.cached_tokens，prompt_tokens 为总输入
    - anthropic（含 deepseek 的 /anthropic 兼容端点）: cache_read_input_tokens；
      注意 anthropic 语义 input_tokens **不含**缓存读/写——总输入 =
      cache_read + cache_creation + input_tokens（分母算错会出 976% 这种
      荒谬命中率，实测踩坑）。
    """
    if not isinstance(raw_usage, dict):
        return None
    hit = raw_usage.get("prompt_cache_hit_tokens")
    if hit is None:
        details = raw_usage.get("prompt_tokens_details") or {}
        hit = details.get("cached_tokens") if isinstance(details, dict) else None
    anthropic = hit is None and raw_usage.get("cache_read_input_tokens") is not None
    if anthropic:
        hit = raw_usage.get("cache_read_input_tokens")
    if hit is None:
        return None
    hit = int(hit or 0)
    if anthropic:
        total = (
            hit
            + int(raw_usage.get("cache_creation_input_tokens") or 0)
            + int(raw_usage.get("input_tokens") or 0)
        )
    else:
        total = int(raw_usage.get("prompt_tokens") or 0)
    if total <= 0:
        return None
    return {"hit": min(hit, total), "prompt": total}


@router.post("/stream2")
def chat_stream2(
    message: str = Body(...),
    system_prompt: str = Body(default="You are a helpful AI assistant for welding manufacturing."),
    temperature: float = Body(default=0.7, ge=0, le=1),
    history: list[dict] = Body(default_factory=list, max_length=50),
    thinking_level: str | None = Body(default=None, pattern="^(off|[a-z0-9_-]{1,32})$"),
    profile_id: str | None = Body(default=None, max_length=64),
    kb_id: str | None = Body(default=None, max_length=64),
    top_k: int = Body(default=4, ge=1, le=10),
    attachments: list[dict] = Body(default_factory=list, max_length=6),
    tool_context: dict | None = Body(default=None),
    request: Request = None,  # type: ignore[assignment] - FastAPI 注入
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Stream a chat reply over SSE; parameters identical to POST /api/chat."""
    _validate_attachments(attachments)
    kb = _resolve_bound_kb(db, kb_id, current_user)
    sources: list[dict] = []
    kb_info: dict | None = None
    context = None
    if kb is not None:
        kb_info = {"id": str(kb.id), "name": kb.name}
        results = _retrieve_for_chat(db, kb, message, top_k)
        context, sources = _build_context(results)

    try:
        config = resolve_profile(db, profile_id=profile_id, purpose="chat_stream2")
    except LLMProfileNotFoundError:
        from fastapi import HTTPException

        raise HTTPException(404, detail={"code": "LLM_PROFILE_NOT_FOUND"})

    def event_stream():
        if kb_info is not None:
            yield _sse({"type": "sources", "sources": sources})
        if not config.api_key:
            yield _sse({"type": "error", "message": "LLM API key not configured. Please configure an LLM profile."})
            yield "data: [DONE]\n\n"
            return

        # 白名单工具编排前置：命中即一次性答复（编排内部多步 LLM 调用
        # 无法流式，且工具答复以结论为主；普通消息走逐 delta 流式）。
        tool_hint = any(keyword in message for keyword in TOOL_HINT_KEYWORDS)
        if tool_context or tool_hint:
            from app.services.chat_tool_orchestrator import orchestrate

            outcome = orchestrate(
                db, config=config, user=current_user, message=message, tool_context=tool_context,
            )
            if outcome.mode != "chat":
                event: dict = {"type": "reply", "text": outcome.reply}
                if outcome.tool_call is not None:
                    event["tool_call"] = outcome.tool_call
                yield _sse(event)
                yield "data: [DONE]\n\n"
                return

        thinking = None if thinking_level in (None, "off") else thinking_level
        messages = _assemble_messages(system_prompt, message, context, history, attachments)
        # 输出预算不显式传 → 走档案「最大输出 Token」（config.max_tokens）
        url, headers, body = _build_llm_request(config, messages, temperature, config.max_tokens, thinking)
        started = time.perf_counter()
        usage: dict = {}
        cache: dict | None = None
        status_code = 0
        payload_chars = sum(len(str(m.get("content") or "")) if isinstance(m.get("content"), str) else 200 for m in messages)
        try:
            with _HTTP_CLIENT.stream(
                "POST", url, headers=headers, json=body, timeout=config.timeout_seconds,
            ) as resp:
                status_code = resp.status_code
                if status_code != 200:
                    err_body = resp.read().decode("utf-8", errors="replace")
                    yield _sse({"type": "error", "message": f"模型上游错误 {status_code}: {err_body[:280]}"})
                    yield "data: [DONE]\n\n"
                    _audit(db, current_user, request, config, purpose="chat_stream2",
                           model=config.model_id, chars=payload_chars, status_code=status_code,
                           tokens=None)
                    db.commit()
                    return
                for line in resp.iter_lines():
                    if not line.startswith("data:") and not line.startswith("event:"):
                        continue
                    if line.startswith("event:"):
                        continue
                    chunk = line[len("data:"):].strip()
                    if not chunk or chunk == "[DONE]":
                        continue
                    try:
                        event = _json.loads(chunk)
                    except ValueError:
                        continue
                    delta, event_usage, _reasoning = _parse_llm_stream_event(config.provider, event)
                    if delta:
                        yield _sse({"type": "delta", "text": delta})
                    if event_usage:
                        usage = event_usage
                    raw_usage = event.get("usage") if isinstance(event, dict) else None
                    extracted = _extract_cache(raw_usage)
                    if extracted is not None:
                        cache = extracted
            yield _sse({"type": "done", "usage": usage, **({"cache": cache} if cache else {})})
        except Exception as error:  # noqa: BLE001 - 流中断以事件形式告知前端
            yield _sse({"type": "error", "message": str(error)[:300]})
        tokens = (
            int(usage.get("prompt_tokens") or 0) + int(usage.get("completion_tokens") or 0)
            if usage else None
        )
        _audit(db, current_user, request, config, purpose="chat_stream2",
               model=config.model_id, chars=payload_chars, status_code=status_code,
               tokens=tokens)
        db.commit()
        yield "data: [DONE]\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


def _build_context(results) -> tuple[str | None, list[dict]]:
    from app.services.knowledge_retrieval import build_rag_context

    return build_rag_context(results)


def _audit(db, user, request, config, *, purpose, model, chars, status_code, tokens):
    """流式直连的 egress 审计（与 chat_completion 同口径：只记元数据）。"""
    from app.services.platform_audit import PlatformAuditIntent, record_platform_event

    if request is None:
        request = SimpleNamespace(state=SimpleNamespace(request_id=None), client=None)
    changes: dict = {"purpose": purpose, "model": model, "chars": chars, "status_code": status_code}
    if tokens is not None:
        changes["total_tokens"] = tokens
    if config.profile_id:
        changes["profile"] = config.profile_name
    try:
        record_platform_event(
            db,
            actor=user,
            request=request,
            intent=PlatformAuditIntent(
                action="llm_gateway.egress",
                resource_type="llm_profile",
                resource_id=config.profile_id,
                changes=changes,
            ),
            result="success" if status_code == 200 else "failed",
            error_code=None if status_code == 200 else f"LLM_UPSTREAM_{status_code}",
        )
    except Exception:  # noqa: BLE001 - 审计失败不阻断回答
        db.rollback()
