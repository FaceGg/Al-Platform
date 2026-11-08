"""AI 对话多会话 API（按用户隔离，KV 存储）。

会话列表/消息持久化在 platform_options KV（key=chat_sessions:{user_id}），
value 为会话数组——轻量方案，无需新表。支持新建/删除/重命名/清空消息。
"""

from fastapi import APIRouter, Body, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.auth import get_current_user
from app.database import get_db
from app.models.platform_option import get_option, set_option
from app.models.user import User

router = APIRouter(prefix="/api/chat-sessions", tags=["chat-sessions"])


def _key(user_id) -> str:
    return f"chat_sessions:{user_id}"


def _sessions(db: Session, user_id) -> list[dict]:
    return get_option(db, _key(user_id), []) or []


class ChatSessionCreate(BaseModel):
    title: str = Field(default="新对话", max_length=120)


class ChatSessionUpdate(BaseModel):
    title: str | None = Field(default=None, max_length=120)
    messages: list[dict] | None = None
    pinned: bool | None = None


@router.get("")
def list_chat_sessions(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # 置顶优先（其余保持原顺序：最新在前）；stable sorted 保序
    sessions = _sessions(db, current_user.id)
    return sorted(sessions, key=lambda s: not bool(s.get("pinned")))


@router.post("", status_code=201)
def create_chat_session(
    payload: ChatSessionCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    import uuid as _uuid

    from app.tasks.time_utils import utcnow

    key = _key(current_user.id)
    sessions = _sessions(db, current_user.id)
    session = {
        "id": str(_uuid.uuid4()),
        "title": payload.title or "新对话",
        "messages": [],
        "created_at": utcnow().isoformat(),
        "updated_at": utcnow().isoformat(),
    }
    sessions.insert(0, session)
    set_option(db, key, sessions[:100])  # 上限 100 个会话
    return session


@router.put("/{session_id}")
def update_chat_session(
    session_id: str,
    payload: ChatSessionUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    key = _key(current_user.id)
    sessions = _sessions(db, current_user.id)
    target = next((s for s in sessions if s.get("id") == session_id), None)
    if target is None:
        raise HTTPException(404, detail={"code": "CHAT_SESSION_NOT_FOUND"})
    if payload.title is not None:
        target["title"] = payload.title[:120] or target["title"]
    if payload.messages is not None:
        target["messages"] = payload.messages
    if payload.pinned is not None:
        target["pinned"] = payload.pinned
    from app.tasks.time_utils import utcnow

    target["updated_at"] = utcnow().isoformat()
    set_option(db, key, sessions)
    return target


@router.delete("/{session_id}", status_code=204)
def delete_chat_session(
    session_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    key = _key(current_user.id)
    sessions = _sessions(db, current_user.id)
    remaining = [s for s in sessions if s.get("id") != session_id]
    if len(remaining) == len(sessions):
        raise HTTPException(404, detail={"code": "CHAT_SESSION_NOT_FOUND"})
    set_option(db, key, remaining)
    return None
