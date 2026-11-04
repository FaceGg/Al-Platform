"""LLM Chat API - standalone AI chat endpoint.

Supports optional knowledge-base binding (RAG): when ``kb_id`` is provided the
message is answered over retrieved chunks, with numbered citations returned to
the caller. Retrieval goes through app.services.knowledge_retrieval, the same
core used by knowledge-base search and the published chat API.
"""
import uuid

from fastapi import APIRouter, Depends, Body, HTTPException
from sqlalchemy.orm import Session
from app.config import settings
from app.database import get_db
from app.models.user import User
from app.models.knowledge import KnowledgeBase
from app.api.auth import get_current_user
from app.services.knowledge_retrieval import (
    RAG_SYSTEM_APPENDIX,
    build_rag_context,
    retrieve_chunks,
)
from app.services.llm_gateway import (
    LLMProfileNotFoundError,
    chat_completion,
    resolve_profile,
)

router = APIRouter(prefix="/api/chat", tags=["chat"])


def _resolve_bound_kb(db: Session, kb_id, current_user) -> KnowledgeBase | None:
    """Owner-checked KB lookup; hidden 404 mirrors knowledge-base endpoints."""
    if not kb_id:
        return None
    try:
        kb_uuid = uuid.UUID(str(kb_id))
    except (TypeError, ValueError, AttributeError):
        raise HTTPException(404, detail={"code": "KNOWLEDGE_BASE_NOT_FOUND", "message": "Knowledge base not found"})
    kb = db.query(KnowledgeBase).filter(
        KnowledgeBase.id == kb_uuid,
        KnowledgeBase.owner_id == current_user.id,
    ).first()
    if not kb:
        raise HTTPException(404, detail={"code": "KNOWLEDGE_BASE_NOT_FOUND", "message": "Knowledge base not found"})
    return kb


def _retrieve_for_chat(db: Session, kb, message: str, top_k: int):
    """Retrieve chunks for a chat turn; retrieval must never block answering."""
    try:
        return retrieve_chunks(db, kb, message, top_k=top_k)
    except Exception:
        return []


def _assemble_messages(system_prompt: str, message: str, context: str | None, history: list[dict] | None = None):
    """Build provider messages; KB content is data, never instructions.

    history 为客户端传来的多轮上下文（user/assistant 交替），作为数据
    拼在 system 之后、本次问题之前——内容由客户端对话产生，不作为
    指令解释（引述即数据原则同 KB）。"""
    if context:
        system_content = f"{system_prompt}\n\n{RAG_SYSTEM_APPENDIX}"
        user_content = f"参考资料：\n\n{context}\n\n问题：{message}"
    else:
        system_content = system_prompt
        user_content = message
    messages = [{"role": "system", "content": system_content}]
    for item in (history or []):
        role = item.get("role")
        content = str(item.get("content") or "")
        if role in ("user", "assistant") and content:
            messages.append({"role": role, "content": content[:4000]})
    messages.append({"role": "user", "content": user_content})
    return messages


@router.post("")
def chat(
    message: str = Body(...),
    system_prompt: str = Body(default="You are a helpful AI assistant for welding manufacturing."),
    temperature: float = Body(default=0.7, ge=0, le=1),
    # 多轮上下文：[{role: user|assistant, content}]，拼在本次问题前
    history: list[dict] = Body(default_factory=list, max_length=50),
    # 思考强度（off/low/medium/high）：anthropic→thinking.budget、
    # responses→reasoning.effort；chat completions 无标准参数不生效
    thinking_level: str | None = Body(default=None, pattern="^(off|low|medium|high)$"),
    # Deprecated request-level overrides (spec v0.9 §14.1 收口): kept only to
    # reject old callers with an explicit 422, never honored.
    api_key: str | None = Body(default=None, max_length=512),
    model: str | None = Body(default=None, max_length=256),
    profile_id: str | None = Body(default=None, max_length=64),
    kb_id: str | None = Body(default=None, max_length=64),
    top_k: int = Body(default=4, ge=1, le=10),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Send a message to the configured LLM and get a response."""
    if api_key or model:
        raise HTTPException(
            422,
            detail={
                "code": "LLM_REQUEST_OVERRIDE_REMOVED",
                "message": "Request-level api_key/model overrides were removed; "
                "select a profile via profile_id or configure one at "
                "/api/llm-profiles.",
            },
        )
    kb = _resolve_bound_kb(db, kb_id, current_user)
    sources: list[dict] = []
    kb_info = None
    kb_warning = None
    context = None
    if kb is not None:
        kb_info = {"id": str(kb.id), "name": kb.name}
        results = _retrieve_for_chat(db, kb, message, top_k)
        context, sources = build_rag_context(results)
        if not sources:
            kb_warning = "知识库中没有检索到相关内容，已按通用助手回答"

    try:
        config = resolve_profile(db, profile_id=profile_id, purpose="chat")
    except LLMProfileNotFoundError:
        raise HTTPException(404, detail={"code": "LLM_PROFILE_NOT_FOUND"})
    if not config.api_key:
        payload = {
            "reply": "LLM API key not configured. Please configure an LLM profile.",
            "type": "error",
        }
        if kb_info is not None:
            payload.update({"sources": sources, "kb": kb_info, "kb_warning": kb_warning})
        return payload

    try:
        reply, usage = chat_completion(
            db,
            config=config,
            messages=_assemble_messages(system_prompt, message, context, history),
            temperature=temperature,
            purpose="chat",
            actor=current_user,
            thinking_level=None if thinking_level == "off" else thinking_level,
        )
        db.commit()  # persist the gateway egress audit event
        payload = {
            "reply": reply or "",
            "type": "success" if reply else "error",
            "usage": {
                "prompt_tokens": usage.get("prompt_tokens", 0),
                "completion_tokens": usage.get("completion_tokens", 0),
            },
        }
        if kb_info is not None:
            payload.update({"sources": sources, "kb": kb_info, "kb_warning": kb_warning})
        return payload
    except Exception as e:
        payload = {"reply": f"LLM call failed: {str(e)}", "type": "error"}
        if kb_info is not None:
            payload.update({"sources": sources, "kb": kb_info, "kb_warning": kb_warning})
        return payload


@router.get("/status")
def chat_status(db: Session = Depends(get_db)):
    """Check if an LLM profile (or legacy env config) is available."""
    config = resolve_profile(db, purpose="chat")
    return {
        "configured": bool(config.api_key),
        "model": config.model_id if config.api_key else "not set",
        "api_url": config.api_url if config.api_key else "not set",
        "profile": config.profile_name,
    }


@router.post("/stream")
def chat_stream(
    message: str = Body(...),
    system_prompt: str = Body(default="You are a helpful AI assistant."),
    kb_id: str | None = Body(default=None, max_length=64),
    top_k: int = Body(default=4, ge=1, le=10),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Stream a chat response from the LLM (SSE).

    A-03：同步 def——检索段（全语料 TF-IDF）在端点体执行，async 下会冻结
    事件循环；Starlette StreamingResponse 原生支持同步生成器（线程池迭代）。

    With a bound knowledge base the first event carries the retrieved sources,
    so the UI can render citations before tokens arrive.
    """
    from fastapi.responses import StreamingResponse

    kb = _resolve_bound_kb(db, kb_id, current_user)
    sources: list[dict] = []
    context = None
    if kb is not None:
        results = _retrieve_for_chat(db, kb, message, top_k)
        context, sources = build_rag_context(results)

    config = resolve_profile(db, purpose="chat_stream")

    def event_stream():
        if sources:
            import json as _json
            yield f"data: {_json.dumps({'type': 'sources', 'sources': sources}, ensure_ascii=False)}\n\n"
        if not config.api_key:
            yield "data: {\"error\": \"LLM not configured\"}\n\n"
            return
        import httpx
        try:
            messages = _assemble_messages(system_prompt, message, context)
            # A-03/A-15：同步流式走网关共享客户端（keepalive 复用），生成器整体
            # 由 Starlette 线程池迭代，不再占用事件循环
            from app.services.llm_gateway import _HTTP_CLIENT
            with _HTTP_CLIENT.stream(
                "POST", config.api_url,
                headers={
                    "Authorization": f"Bearer {config.api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": config.model_id,
                    "messages": messages,
                    "temperature": 0.7,
                    "max_tokens": 2000,
                    "stream": True,
                },
                timeout=config.timeout_seconds,
            ) as resp:
                for line in resp.iter_lines():
                    if line.startswith("data: "):
                        yield f"{line}\n\n"
                yield "data: [DONE]\n\n"
        except Exception as e:
            yield f"data: {{\"error\": \"{str(e)}\"}}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")
