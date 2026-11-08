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


def _validate_attachments(attachments: list[dict]) -> None:
    """附件契约：name/kind/data；图片为 data:image/* base64，文本为纯文本。"""
    for att in attachments:
        if att.get("kind") not in ("image", "text") or not att.get("data"):
            raise HTTPException(
                422,
                detail={"code": "ATTACHMENT_INVALID", "message": "附件必须为 {name, kind: image|text, data}"},
            )
        if att.get("kind") == "image":
            data = str(att.get("data"))
            if not data.startswith("data:image/"):
                raise HTTPException(
                    422,
                    detail={"code": "ATTACHMENT_INVALID", "message": "图片附件必须是 data:image/* base64 data URL"},
                )
            if len(data) > 8_000_000:
                raise HTTPException(
                    422,
                    detail={"code": "ATTACHMENT_TOO_LARGE", "message": "图片附件超过大小上限"},
                )
        elif len(str(att.get("data"))) > 80_000:
            raise HTTPException(
                422,
                detail={"code": "ATTACHMENT_TOO_LARGE", "message": "文本附件超过 80k 字符上限"},
            )


def _assemble_messages(
    system_prompt: str,
    message: str,
    context: str | None,
    history: list[dict] | None = None,
    attachments: list[dict] | None = None,
):
    """Build provider messages; KB content is data, never instructions.

    history 为客户端传来的多轮上下文（user/assistant 交替），作为数据
    拼在 system 之后、本次问题之前——内容由客户端对话产生，不作为
    指令解释（引述即数据原则同 KB）。

    attachments：本轮附件（kind=text 的内容以引述文本拼进问题；kind=image
    的 data URL 组成 OpenAI 多模态 content 数组——网关再按 provider 格式
    映射成 anthropic/responses 的图像块）。"""
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
    text_blocks = []
    image_urls = []
    for att in attachments or []:
        name = str(att.get("name") or "attachment")[:200]
        if att.get("kind") == "text":
            text_blocks.append(f"[附件 {name}]\n{str(att.get('data') or '')[:60000]}")
        elif att.get("kind") == "image":
            image_urls.append(str(att.get("data")))
    if text_blocks:
        user_content += "\n\n" + "\n\n".join(text_blocks)
    if image_urls:
        content: str | list = [
            {"type": "text", "text": user_content},
            *[{"type": "image_url", "image_url": {"url": url}} for url in image_urls],
        ]
    else:
        content = user_content
    messages.append({"role": "user", "content": content})
    return messages


@router.post("")
def chat(
    message: str = Body(...),
    system_prompt: str = Body(default="You are a helpful AI assistant for welding manufacturing."),
    temperature: float = Body(default=0.7, ge=0, le=1),
    # 多轮上下文：[{role: user|assistant, content}]，拼在本次问题前
    history: list[dict] = Body(default_factory=list, max_length=50),
    # 思考强度：默认 off/low/medium/high（anthropic→thinking.budget、
    # responses→reasoning.effort）；所选模型配置了 reasoning_levels 时可传
    # 自定义等级 token，网关按该模型 reasoning_mapping 求值应用
    thinking_level: str | None = Body(default=None, pattern="^(off|[a-z0-9_-]{1,32})$"),
    # Deprecated request-level overrides (spec v0.9 §14.1 收口): kept only to
    # reject old callers with an explicit 422, never honored.
    api_key: str | None = Body(default=None, max_length=512),
    model: str | None = Body(default=None, max_length=256),
    profile_id: str | None = Body(default=None, max_length=64),
    kb_id: str | None = Body(default=None, max_length=64),
    top_k: int = Body(default=4, ge=1, le=10),
    # 本轮附件：[{name, kind: image|text, data}]——图片 data URL 直入
    # 多模态 content，文本引述拼进问题（发送侧逐轮携带，不入 history）
    attachments: list[dict] = Body(default_factory=list, max_length=6),
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
    _validate_attachments(attachments)
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
            messages=_assemble_messages(system_prompt, message, context, history, attachments),
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


CHAT_COMPRESS_SYSTEM = (
    "你是对话压缩器。把给定的对话历史压缩为一段简洁摘要（不超过 300 字），"
    "保留关键事实、数字、结论与未决问题；不要添加评论与客套。只输出摘要文本。"
)


@router.post("/compress")
def compress_chat_history(
    messages: list[dict] = Body(..., description="待压缩的对话历史"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """上下文自动压缩：用 LLM 把旧对话历史摘要化。

    前端在容量圆圈达 100% 时调用；返回的摘要将随后续请求注入，
    旧消息原文即可安全移除（内容压缩而非窗口截断）。"""
    import json as _json

    clean = []
    for item in messages[:200]:
        role = item.get("role")
        content = str(item.get("content") or "")[:4000]
        if role in ("user", "assistant") and content:
            clean.append({"role": role, "content": content})
    if not clean:
        raise HTTPException(422, detail={"code": "COMPRESS_EMPTY"})
    config = resolve_profile(db, purpose="chat")
    if not config.api_key:
        raise HTTPException(503, detail={"code": "LLM_NOT_CONFIGURED"})
    try:
        reply, _usage = chat_completion(
            db,
            config=config,
            messages=[
                {"role": "system", "content": CHAT_COMPRESS_SYSTEM},
                {"role": "user", "content": _json.dumps(clean, ensure_ascii=False)[:60000]},
            ],
            temperature=0.2,
            max_tokens=600,
            purpose="chat_compress",
            actor=current_user,
        )
    except Exception as error:  # noqa: BLE001 - 上游失败原样透传给前端提示
        raise HTTPException(
            502,
            detail={"code": "COMPRESS_FAILED", "message": str(error)[:200]},
        ) from error
    return {"summary": (reply or "").strip()}


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
