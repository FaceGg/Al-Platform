"""LLM Chat API - standalone AI chat endpoint."""
from fastapi import APIRouter, Depends, Body
from app.config import settings
from app.models.user import User
from app.api.auth import get_current_user

router = APIRouter(prefix="/api/chat", tags=["chat"])


@router.post("")
async def chat(
    message: str = Body(...),
    system_prompt: str = Body(default="You are a helpful AI assistant for welding manufacturing."),
    current_user: User = Depends(get_current_user),
):
    """Send a message to the configured LLM and get a response."""
    if not settings.llm_api_key:
        return {"reply": "LLM API key not configured. Please set LLM_API_KEY in environment.", "type": "error"}

    try:
        import httpx
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(
                settings.llm_api_url,
                headers={
                    "Authorization": f"Bearer {settings.llm_api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": settings.llm_model,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": message},
                    ],
                    "temperature": 0.7,
                    "max_tokens": 2000,
                },
            )
            data = resp.json()
            reply = data.get("choices", [{}])[0].get("message", {}).get("content", "")
            usage = data.get("usage", {})
            return {
                "reply": reply,
                "type": "success",
                "usage": {
                    "prompt_tokens": usage.get("prompt_tokens", 0),
                    "completion_tokens": usage.get("completion_tokens", 0),
                },
            }
    except Exception as e:
        return {"reply": f"LLM call failed: {str(e)}", "type": "error"}


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
    current_user: User = Depends(get_current_user),
):
    """Stream a chat response from the LLM (SSE)."""
    if not settings.llm_api_key:
        from fastapi.responses import StreamingResponse
        async def error_stream():
            yield "data: {\"error\": \"LLM not configured\"}\n\n"
        return StreamingResponse(error_stream(), media_type="text/event-stream")

    from fastapi.responses import StreamingResponse
    import httpx

    async def stream_response():
        try:
            async with httpx.AsyncClient(timeout=120) as client:
                async with client.stream(
                    "POST", settings.llm_api_url,
                    headers={
                        "Authorization": f"Bearer {settings.llm_api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": settings.llm_model,
                        "messages": [
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": message},
                        ],
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

    return StreamingResponse(stream_response(), media_type="text/event-stream")
