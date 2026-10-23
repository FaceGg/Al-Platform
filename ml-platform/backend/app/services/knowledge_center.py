"""Unified knowledge center service (spec v0.9 §16, Task A6.1).

- Bindings: per-KB config layer; the system partition (平台经验) can never be
  disabled or unbound.
- Unified retrieval (§16.3): one pass over every enabled+scoped binding plus
  the experience partition, merged and truncated to the char budget, with
  traceable citations (kb/doc or exp entry id) — the ONLY retrieval path.
- Projection (§16.4): cross-domain experience entries ≥ the confidence gate
  are formatted into the system partition documents, idempotent by entry id;
  the partition body is read-only — humans act via status operations.
"""

from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from app.models.experience_entry import ExperienceEntry
from app.models.kb_binding import KBBinding
from app.models.knowledge import Document, KnowledgeBase

SYSTEM_PARTITION_NAME = "平台经验（系统分区）"


def get_or_create_binding(db: Session, kb_id, *, is_system: bool = False) -> KBBinding:
    binding = db.query(KBBinding).filter(KBBinding.kb_id == kb_id).first()
    if binding is None:
        binding = KBBinding(kb_id=kb_id, is_system=is_system)
        db.add(binding)
        db.commit()
    return binding


def update_binding(db: Session, binding: KBBinding, changes: dict) -> KBBinding:
    if binding.is_system:
        for field in ("enabled", "scope_projects", "sync_human_review"):
            if field in changes and changes[field] != getattr(binding, field):
                raise ValueError("系统分区不可关闭/解绑/改人审策略（%s）" % field)
    for field in (
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
    ):
        if field in changes:
            setattr(binding, field, changes[field])
    db.commit()
    db.refresh(binding)
    return binding


def _binding_allows(binding: KBBinding, *, channel: str, project_id) -> bool:
    if not binding.enabled:
        return False
    if channel == "chat" and not binding.scope_chat:
        return False
    if channel == "agent_s1" and not binding.scope_agent_s1:
        return False
    scopes = binding.scope_projects or []
    if scopes and "*" not in scopes:
        if project_id is None or str(project_id) not in scopes:
            return False
    return True


def get_system_partition(db: Session, admin_id) -> tuple[KnowledgeBase, KBBinding]:
    kb = (
        db.query(KnowledgeBase)
        .filter(KnowledgeBase.name == SYSTEM_PARTITION_NAME)
        .first()
    )
    created = False
    if kb is None:
        kb = KnowledgeBase(
            name=SYSTEM_PARTITION_NAME,
            description="系统自动管理的跨域经验分区（正文只读，状态操作回写真源）",
            owner_id=admin_id,
        )
        db.add(kb)
        db.commit()
        created = True
    binding = get_or_create_binding(db, kb.id, is_system=True)
    if created or not binding.sync_receive_experience:
        binding.sync_receive_experience = True
        binding.enabled = True
        db.commit()
    return kb, binding


def unified_retrieve(
    db: Session,
    *,
    query: str,
    channel: str,
    project_id=None,
    domain: str | None = None,
    total_top_k: int = 8,
    experience_min_confidence: float = 0.70,
    retrieve_fn=None,
) -> dict:
    """One retrieval pass across all bound KBs + the experience partition.

    Returns ``{"citations": [...], "context_chars": int}`` — citations carry
    their source (kb/doc or exp entry id) so the S1 report can reference them
    (§16.3 防假引用).
    """
    if retrieve_fn is None:
        from app.services.knowledge_retrieval import retrieve_chunks as retrieve_fn

    bindings = db.query(KBBinding).filter(KBBinding.enabled.is_(True)).all()
    citations: list[dict] = []
    chars = 0
    for binding in bindings:
        if not _binding_allows(binding, channel=channel, project_id=project_id):
            continue
        if binding.retrieval_trigger == "explicit":
            continue
        kb = db.get(KnowledgeBase, binding.kb_id)
        if kb is None:
            continue
        try:
            chunks = retrieve_fn(db, kb, query, top_k=binding.retrieval_top_k) or []
        except Exception:  # noqa: BLE001 - a broken KB must not break S1
            continue
        for chunk in chunks:
            content = str(chunk.get("content") or "")
            if chars + len(content) > binding.retrieval_max_total_chars:
                continue
            chars += len(content)
            citations.append(
                {
                    "source": "kb",
                    "kb": kb.name,
                    "kb_id": str(kb.id),
                    "doc": chunk.get("filename") or "",
                    "chunk": str(chunk.get("chunk_id") or ""),
                    "score": chunk.get("score"),
                    "content": content,
                }
            )

    # Experience partition: structured filtering stays authoritative (§16.1).
    from app.services.agent.experience import retrieve_for_task

    entries = retrieve_for_task(
        db,
        domain=domain or "cross-domain",
        profile_fingerprint={},
        top_k=total_top_k,
        project_id=project_id,
    )
    for entry in entries:
        if entry.confidence < experience_min_confidence:
            continue
        text = "[%s] %s → %s" % (entry.situation, entry.lesson, entry.action)
        if chars + len(text) > 4000:
            continue
        chars += len(text)
        citations.append(
            {
                "source": "exp",
                "entry": str(entry.id),
                "confidence": entry.confidence,
                "content": text,
            }
        )
        if len(citations) >= total_top_k + 4:
            break
    return {"citations": citations[: total_top_k + 4], "context_chars": chars}


def project_experience_entry(db: Session, entry: ExperienceEntry, admin_id) -> str | None:
    """正向同步（§16.4）：跨域且达门槛的条目格式化为系统分区文档。

    幂等键 = 条目 ID（文件名「经验 exp-…」）；重复蒸馏更新不重复建。
    分区正文只读：此函数是唯一写入方。"""
    if entry.generality != "cross-domain":
        return None
    confidence_gate = 0.85
    binding = (
        db.query(KBBinding).filter(KBBinding.is_system.is_(True)).first()
    )
    if binding is not None:
        confidence_gate = binding.sync_experience_min_confidence
    if float(entry.confidence) < confidence_gate:
        return None

    kb, _binding = get_system_partition(db, admin_id)
    filename = "经验 %s" % entry.id
    doc = (
        db.query(Document)
        .filter(Document.kb_id == kb.id, Document.filename == filename)
        .first()
    )
    body = (
        "情况：%s\n教训：%s\n动作：%s\n置信度：%.2f\n来源：%s"
        % (
            entry.situation,
            entry.lesson,
            entry.action,
            float(entry.confidence),
            ",".join(entry.source_tasks or []) or "-",
        )
    )
    if doc is None:
        doc = Document(kb_id=kb.id, filename=filename, content=body, doc_type="experience")
        db.add(doc)
    else:
        doc.content = body  # 同步幂等：同键更新正文（人工附注走 human_note 字段）
    db.flush()
    _reindex_document(db, doc, body)
    db.commit()
    return str(doc.id)


def _reindex_document(db: Session, doc: Document, body: str) -> None:
    """Chunk + embed the projected doc so the standard KB retrieval path can
    find it (v0.9 §16.3 统一检索的 KB 通道)。TF-IDF 向量化复用知识库既有实现。"""
    from app.api.knowledge import _compute_tfidf_embedding  # noqa: PLC0415 - 复用私有实现
    from app.models.knowledge import Chunk

    db.query(Chunk).filter(Chunk.doc_id == doc.id).delete()
    paragraphs = [p.strip() for p in body.split("\n") if p.strip()] or [body]
    embeddings = _compute_tfidf_embedding(paragraphs)
    for index, (paragraph, embedding) in enumerate(zip(paragraphs, embeddings)):
        db.add(
            Chunk(
                doc_id=doc.id,
                content=paragraph,
                chunk_index=index,
                embedding=embedding,
            )
        )
    doc.chunk_count = len(paragraphs)
