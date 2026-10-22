"""Experience store service (spec v0.9 §10.2/§16.5).

Distilled entries start in ``shadow`` — retrieval counts their hits but never
injects them — and promote to ``active`` after two recorded hits (the
one-task-cycle cooldown, deterministic form). Human-sourced entries
(chat save_insight with user confirmation) are directly active at 0.75.
Retirement/supersession filters immediately.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.orm import Session

from app.models.experience_entry import ExperienceEntry

MIN_INJECT_CONFIDENCE = 0.70
PROMOTE_HITS = 2
HUMAN_DEFAULT_CONFIDENCE = 0.75


class ExperienceEvidenceRequired(ValueError):
    """Distilled entries must carry a non-empty evidence chain."""


def record_experience(
    db: Session,
    *,
    domain: str,
    situation: str,
    lesson: str,
    action: str,
    evidence: dict,
    generality: str = "domain",
    confidence: float = 0.5,
    origin: str = "distilled",
    scope_project_ids: list | None = None,
    source_tasks: list | None = None,
    created_by: UUID | None = None,
) -> ExperienceEntry:
    if origin == "distilled":
        source_tasks = source_tasks or (evidence or {}).get("source_tasks") or []
        if not source_tasks:
            raise ExperienceEvidenceRequired(
                "distilled entries require non-empty evidence.source_tasks"
            )
        status = "shadow"
    else:
        status = "active"
        if confidence is None or confidence < HUMAN_DEFAULT_CONFIDENCE:
            confidence = HUMAN_DEFAULT_CONFIDENCE
    entry = ExperienceEntry(
        domain=domain or "cross-domain",
        situation=situation,
        lesson=lesson,
        action=action,
        evidence_json=evidence or {},
        generality=generality,
        confidence=float(confidence),
        origin=origin,
        status=status,
        scope_project_ids=scope_project_ids or [],
        source_tasks=source_tasks or [],
        created_by=created_by,
    )
    db.add(entry)
    db.commit()
    return entry


def retrieve_for_task(
    db: Session,
    *,
    domain: str,
    profile_fingerprint: dict,
    top_k: int = 5,
    project_id: UUID | None = None,
) -> list[ExperienceEntry]:
    """Top-k injectable entries for a new task's S1.

    Active entries matching the domain (plus cross-domain) with
    ``confidence >= 0.70``, ranked by confidence then hit count. Shadow
    entries are NOT returned but their hit count increments (the cooldown
    counter); the fingerprint parameter is reserved for vector similarity in
    the knowledge-center milestone (P6).
    """
    db.flush()  # sessions run with autoflush off — see the caller's pending state
    candidates = (
        db.query(ExperienceEntry)
        .filter(
            ExperienceEntry.status == "active",
            ExperienceEntry.confidence >= MIN_INJECT_CONFIDENCE,
            ExperienceEntry.domain.in_([domain, "cross-domain"]),
        )
        .order_by(
            ExperienceEntry.confidence.desc(), ExperienceEntry.hit_count.desc()
        )
        .all()
    )
    if project_id is not None:
        candidates = [
            entry
            for entry in candidates
            if not entry.scope_project_ids or str(project_id) in entry.scope_project_ids
        ]
    selected = candidates[:top_k]

    # Shadow cooldown: every shadow entry that WOULD have matched this task
    # (same domain filter) counts the hit, regardless of the top-k cut.
    shadow = (
        db.query(ExperienceEntry)
        .filter(
            ExperienceEntry.status == "shadow",
            ExperienceEntry.confidence >= MIN_INJECT_CONFIDENCE,
            ExperienceEntry.domain.in_([domain, "cross-domain"]),
        )
        .all()
    )
    for entry in shadow:
        entry.hit_count = (entry.hit_count or 0) + 1
    if shadow:
        db.commit()
    return selected


def promote_shadow_entries(db: Session) -> list[UUID]:
    """Shadow → active once an entry has accumulated PROMOTE_HITS matches."""
    entries = (
        db.query(ExperienceEntry)
        .filter(
            ExperienceEntry.status == "shadow",
            ExperienceEntry.hit_count >= PROMOTE_HITS,
        )
        .all()
    )
    for entry in entries:
        entry.status = "active"
    if entries:
        db.commit()
    return [entry.id for entry in entries]


def retire_entry(db: Session, entry_id: UUID) -> ExperienceEntry:
    entry = db.get(ExperienceEntry, entry_id)
    if entry is None:
        raise LookupError(f"experience entry not found: {entry_id}")
    entry.status = "retired"
    db.commit()
    return entry


def supersede_entry(db: Session, entry_id: UUID) -> ExperienceEntry:
    entry = db.get(ExperienceEntry, entry_id)
    if entry is None:
        raise LookupError(f"experience entry not found: {entry_id}")
    entry.status = "superseded"
    db.commit()
    return entry


def annotate_entry(db: Session, entry_id: UUID, human_note: str) -> ExperienceEntry:
    """Human note attached from the knowledge center (16.4: 正文只读，意见走附注)."""
    entry = db.get(ExperienceEntry, entry_id)
    if entry is None:
        raise LookupError(f"experience entry not found: {entry_id}")
    entry.human_note = human_note
    db.commit()
    return entry
