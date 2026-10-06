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


def _assemble_messages(system_prompt: str, message: str, context: str | None):
    """Build provider messages; KB content is data, never instructions."""
    if context:
        system_content = f"{system_prompt}\n\n{RAG_SYSTEM_APPENDIX}"
        user_content = f"参考资料：\n\n{context}\n\n问题：{message}"
    else:
        system_content = system_prompt
        user_content = message
    return [
        {"role": "system", "content": system_content},
        {"role": "user", "content": user_content},
    ]


@router.post("")
async def chat(
    message: str = Body(...),
    system_prompt: str = Body(default="You are a helpful AI assistant for welding manufacturing."),
    temperature: float = Body(default=0.7, ge=0, le=1),
    api_key: str | None = Body(default=None, max_length=512),
    model: str | None = Body(default=None, max_length=256),
    kb_id: str | None = Body(default=None, max_length=64),
    top_k: int = Body(default=4, ge=1, le=10),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Send a message to the configured LLM and get a response."""
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

    resolved_api_key = (api_key or settings.llm_api_key or "").strip()
    resolved_model = (model or settings.llm_model or "").strip()
    if not resolved_api_key:
        payload = {
            "reply": "LLM API key not configured. Please set LLM_API_KEY in environment.",
            "type": "error",
        }
        if kb_info is not None:
            payload.update({"sources": sources, "kb": kb_info, "kb_warning": kb_warning})
        return payload

    try:
        import httpx
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(
                settings.llm_api_url,
                headers={
                    "Authorization": f"Bearer {resolved_api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": resolved_model,
                    "messages": _assemble_messages(system_prompt, message, context),
                    "temperature": temperature,
                    "max_tokens": 2000,
                },
            )
            data = resp.json()
            reply = data.get("choices", [{}])[0].get("message", {}).get("content", "")
            usage = data.get("usage", {})
            payload = {
                "reply": reply,
                "type": "success",
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
def chat_status():
    """Check if LLM API is configured."""
    return {
        "configured": bool(settings.llm_api_key),
        "model": settings.llm_model if settings.llm_api_key else "not set",
        "api_url": settings.llm_api_url if settings.llm_api_key else "not set",
    }


@router.post("/stream")
async def chat_stream(
    message: str = Body(...),
    system_prompt: str = Body(default="You are a helpful AI assistant."),
    kb_id: str | None = Body(default=None, max_length=64),
    top_k: int = Body(default=4, ge=1, le=10),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Stream a chat response from the LLM (SSE).

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

    async def event_stream():
        if sources:
            import json as _json
            yield f"data: {_json.dumps({'type': 'sources', 'sources': sources}, ensure_ascii=False)}\n\n"
        if not settings.llm_api_key:
            yield "data: {\"error\": \"LLM not configured\"}\n\n"
            return
        import httpx
        try:
            messages = _assemble_messages(system_prompt, message, context)
            async with httpx.AsyncClient(timeout=120) as client:
                async with client.stream(
                    "POST", settings.llm_api_url,
                    headers={
                        "Authorization": f"Bearer {settings.llm_api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": settings.llm_model,
                        "messages": messages,
                        "temperature": 0.7,
                        "max_tokens": 2000,
                        "stream": True,
                    },
                ) as resp:
                    async for line in resp.aiter_lines():
                        if line.startswith("data: "):
                            yield f"{line}\n\n"
                    yield "data: [DONE]\n\n"
        except Exception as e:
            yield f"data: {{\"error\": \"{str(e)}\"}}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")
