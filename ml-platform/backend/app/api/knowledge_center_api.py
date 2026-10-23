"""Knowledge center API (spec v0.9 §16, AutoML Agent Task A6.1).

Bindings configuration surface + experience partition operations (the RSI
human-review gate's formal UI backend).
"""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from app.api.auth import get_current_user
from app.api.users import get_current_admin
from app.database import get_db
from app.models.experience_entry import ExperienceEntry
from app.models.kb_binding import KBBinding
from app.models.knowledge import Document, KnowledgeBase
from app.models.user import User
from app.services.knowledge_center import (
    get_or_create_binding,
    get_system_partition,
    update_binding,
)

router = APIRouter(prefix="/api/knowledge-center", tags=["knowledge-center"])

BINDING_FIELDS = (
    "enabled",
    "scope_projects",
    "scope_agent_tasks",
    "scope_agent_task_ids",
    "scope_chat",
    "scope_agent_s1",
    "retrieval_top_k",
    "retrieval_max_total_chars",
    "retrieval_min_score",
    "retrieval_trigger",
    "sync_receive_experience",
    "sync_experience_min_confidence",
    "sync_human_review",
)


class BindingUpdate(BaseModel):
    enabled: bool | None = None
    scope_projects: list[str] | None = None
    scope_agent_tasks: str | None = None
    scope_agent_task_ids: list[str] | None = None
    scope_chat: bool | None = None
    scope_agent_s1: bool | None = None
    retrieval_top_k: int | None = None
    retrieval_max_total_chars: int | None = None
    retrieval_min_score: float | None = None
    retrieval_trigger: str | None = None
    sync_receive_experience: bool | None = None
    sync_experience_min_confidence: float | None = None
    sync_human_review: str | None = None


def _binding_out(db: Session, binding: KBBinding) -> dict:
    kb = db.get(KnowledgeBase, binding.kb_id)
    doc_count = (
        db.query(Document).filter(Document.kb_id == binding.kb_id).count()
    )
    return {
        "id": str(binding.id),
        "kb_id": str(binding.kb_id),
        "kb_name": kb.name if kb else "",
        "is_system": binding.is_system,
        "enabled": binding.enabled,
        "scope_projects": binding.scope_projects or [],
        "scope_chat": binding.scope_chat,
        "scope_agent_s1": binding.scope_agent_s1,
        "retrieval_top_k": binding.retrieval_top_k,
        "retrieval_min_score": binding.retrieval_min_score,
        "retrieval_trigger": binding.retrieval_trigger,
        "sync_receive_experience": binding.sync_receive_experience,
        "sync_experience_min_confidence": binding.sync_experience_min_confidence,
        "sync_human_review": binding.sync_human_review,
        "doc_count": doc_count,
    }


@router.get("/bindings")
def list_bindings(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # 系统分区随列表惰性创建，保证任何部署下经验分区都存在且可检索。
    get_system_partition(db, current_user.id if _is_admin(db, current_user) else _first_admin(db))
    bindings = db.query(KBBinding).order_by(KBBinding.is_system.desc()).all()
    return [_binding_out(db, binding) for binding in bindings]


@router.patch("/bindings/{binding_id}")
def patch_binding(
    binding_id: str,
    payload: BindingUpdate,
    db: Session = Depends(get_db),
    admin: User = Depends(get_current_admin),
):
    binding = db.get(KBBinding, _uuid(binding_id))
    if binding is None:
        raise HTTPException(404, detail={"code": "KB_BINDING_NOT_FOUND"})
    try:
        updated = update_binding(db, binding, payload.model_dump(exclude_none=True))
    except ValueError as error:
        raise HTTPException(409, detail={"code": "KB_BINDING_IMMUTABLE",
                                         "message": str(error)}) from error
    return _binding_out(db, updated)


@router.get("/experience")
def list_experience(
    status: str | None = None,
    domain: str | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    query = db.query(ExperienceEntry)
    if status:
        query = query.filter(ExperienceEntry.status == status)
    if domain:
        query = query.filter(
            ExperienceEntry.domain.in_([domain, "cross-domain"])
        )
    entries = query.order_by(ExperienceEntry.confidence.desc()).limit(200).all()
    return [
        {
            "id": str(entry.id),
            "domain": entry.domain,
            "situation": entry.situation,
            "lesson": entry.lesson,
            "action": entry.action,
            "confidence": entry.confidence,
            "origin": entry.origin,
            "status": entry.status,
            "hit_count": entry.hit_count,
            "human_note": entry.human_note,
            "source_tasks": entry.source_tasks or [],
        }
        for entry in entries
    ]


@router.post("/experience/{entry_id}/retire")
def retire_experience(
    entry_id: str,
    db: Session = Depends(get_db),
    admin: User = Depends(get_current_admin),
):
    from app.services.agent.experience import retire_entry

    try:
        entry = retire_entry(db, _uuid(entry_id))
    except LookupError as error:
        raise HTTPException(404, detail={"code": "EXPERIENCE_NOT_FOUND"}) from error
    return {"id": str(entry.id), "status": entry.status}


@router.post("/experience/{entry_id}/note")
def annotate_experience(
    entry_id: str,
    payload: dict,
    db: Session = Depends(get_db),
    admin: User = Depends(get_current_admin),
):
    from app.services.agent.experience import annotate_entry

    note = str((payload or {}).get("note") or "").strip()
    if not note:
        raise HTTPException(422, detail={"code": "EXPERIENCE_NOTE_REQUIRED"})
    try:
        entry = annotate_entry(db, _uuid(entry_id), note)
    except LookupError as error:
        raise HTTPException(404, detail={"code": "EXPERIENCE_NOT_FOUND"}) from error
    return {"id": str(entry.id), "human_note": entry.human_note}


def _uuid(value: str) -> UUID:
    try:
        return UUID(str(value))
    except (TypeError, ValueError, AttributeError) as error:
        raise HTTPException(422, detail={"code": "IDENTIFIER_INVALID"}) from error


def _is_admin(db: Session, user: User) -> bool:
    return user.role == "admin"


def _first_admin(db: Session):
    admin = db.query(User).filter(User.role == "admin").first()
    return admin.id if admin else None
