# -*- coding: utf-8 -*-
"""Knowledge-graph fusion: alignment, disambiguation, conflict resolution.

五阶段流水线的阶段 3。策略=「确定性归并自动执行 + 模糊/冲突进人工审核」：

- Pass 1 同名归并：同库归一化同名（或别名互命中）的存活实体自动合并，
  记 accepted 建议留痕；
- Pass 2 属性冲突：同实体同属性不同值（跨文档）→ pending 冲突建议，
  人工裁决取哪个值；
- Pass 3 模糊对齐：difflib 高相似候选 → LLM 批量仲裁 → pending 合并建议，
  人工确认才真正合并。

合并执行是事务性的：重指关系 → 合并别名/属性 → loser 置 merged_into；
apply_record 留审计快照。所有数字均小规模（单库实体 ≤ 万级），全内存处理。
"""
import datetime
import difflib
import uuid

from app.models.knowledge import (
    GraphEntity,
    GraphRelation,
    KgMergeSuggestion,
)
from app.services.kg_names import normalize_name as _normalize_name

MAX_FUZZY_PAIRS_PER_RUN = 60
MAX_AUTO_MERGES_PER_RUN = 200


# ---------------------------------------------------------------- 归并执行


def merge_entities(db, kb, winner: GraphEntity, loser: GraphEntity,
                   *, method: str = "auto", reason: str = "",
                   decided_by=None) -> KgMergeSuggestion:
    """把 loser 并入 winner：重指关系 → 合并别名/属性 → loser 置 merged_into。"""
    if winner.id == loser.id:
        raise ValueError("cannot merge an entity into itself")
    if loser.merged_into is not None:
        raise ValueError("loser already merged")
    # 环保护（celery acks_late 重投/并发审核下可能出现交错合并）：winner 自己
    # 也已被合并时，先解析到最终存活者再执行，否则会写出 A→B→A 环
    if winner.merged_into is not None:
        winner = resolve_merged(db, winner.id)
        if winner.id == loser.id or winner.merged_into is not None:
            raise ValueError("winner resolved into the loser chain; skip merge")

    relations_repointed = 0
    for rel in db.query(GraphRelation).filter(
        GraphRelation.kb_id == kb.id,
        (GraphRelation.source_id == loser.id) | (GraphRelation.target_id == loser.id),
    ).all():
        if rel.source_id == loser.id:
            rel.source_id = winner.id
            relations_repointed += 1
        if rel.target_id == loser.id:
            rel.target_id = winner.id
            relations_repointed += 1
    _dedupe_winner_relations(db, winner)

    aliases_added = []
    loser_aliases = loser.aliases or []
    for alias in [loser.name, *loser_aliases]:
        if alias != winner.name and alias not in (winner.aliases or []):
            winner.aliases = list(winner.aliases or []) + [alias]
            aliases_added.append(alias)

    attributes_merged = _merge_attributes(winner, loser)
    props = dict(winner.properties or {})
    loser_props = loser.properties or {}
    props["freq"] = int(props.get("freq") or 0) + int(loser_props.get("freq") or 0)
    props["doc_ids"] = sorted(set(props.get("doc_ids") or []) | set(loser_props.get("doc_ids") or []))
    winner.properties = props

    loser.merged_into = winner.id

    suggestion = KgMergeSuggestion(
        kb_id=kb.id,
        type="merge_entity",
        status="accepted",
        method=method,
        entity_a_id=winner.id,
        entity_b_id=loser.id,
        canonical_name=winner.name,
        payload={"reason": reason[:500]},
        apply_record={
            "relations_repointed": relations_repointed,
            "aliases_added": aliases_added,
            "attributes_merged": attributes_merged,
        },
        decided_at=datetime.datetime.utcnow(),
        decided_by=decided_by,
    )
    db.add(suggestion)
    db.commit()
    # 引用 loser 的历史 pending 建议一并作废
    _invalidate_pending_for(db, [winner.id, loser.id])
    return suggestion


def _dedupe_winner_relations(db, winner: GraphEntity) -> int:
    """重指后 (source,target,type) 可能重复：保留 weight 最高的一组，删其余。"""
    rels = db.query(GraphRelation).filter(
        (GraphRelation.source_id == winner.id) | (GraphRelation.target_id == winner.id),
    ).all()
    seen: dict[tuple, GraphRelation] = {}
    removed = 0
    for rel in rels:
        key = (rel.source_id, rel.target_id, rel.relation_type)
        keep = seen.get(key)
        if keep is None:
            seen[key] = rel
            continue
        if int((rel.properties or {}).get("weight") or 0) > int((keep.properties or {}).get("weight") or 0):
            db.delete(keep)
            seen[key] = rel
        else:
            db.delete(rel)
        removed += 1
    return removed


def _merge_attributes(winner: GraphEntity, loser: GraphEntity) -> int:
    props = dict(winner.properties or {})
    attrs = list(props.get("attributes") or [])
    existing_keys = {(a.get("name"), a.get("value")) for a in attrs}
    merged = 0
    for attr in (loser.properties or {}).get("attributes") or []:
        key = (attr.get("name"), attr.get("value"))
        if key in existing_keys:
            continue
        attrs.append(attr)
        existing_keys.add(key)
        merged += 1
    props["attributes"] = attrs[:16]
    winner.properties = props
    return merged


def _invalidate_pending_for(db, entity_ids: list) -> None:
    """实体被合并/变动后，引用它的 pending 建议一并作废（避免陈旧审核）。"""
    db.query(KgMergeSuggestion).filter(
        KgMergeSuggestion.status == "pending",
        (KgMergeSuggestion.entity_a_id.in_(entity_ids)) | (KgMergeSuggestion.entity_b_id.in_(entity_ids)),
    ).update(
        {"status": "rejected"},
        synchronize_session=False,
    )


def resolve_merged(db, entity_id) -> GraphEntity:
    """跟随 merged_into 链到存活实体（防环：最多跟 8 跳）。"""
    seen = set()
    current_id = entity_id
    for _ in range(8):
        if current_id in seen:
            break
        seen.add(current_id)
        entity = db.get(GraphEntity, current_id)
        if entity is None or entity.merged_into is None:
            return entity
        current_id = entity.merged_into
    return db.get(GraphEntity, current_id)


# ---------------------------------------------------------------- 自动融合


def auto_fuse_after_extraction(db, kb, *, method: str = "llm") -> dict:
    """抽取落库后自动跑：同名/别名归并（自动）+ 冲突与模糊候选（进审核队列）。"""
    report = {"auto_merged": 0, "conflicts": 0, "fuzzy_pending": 0}
    report["auto_merged"] = _exact_and_alias_merges(db, kb, max_merges=MAX_AUTO_MERGES_PER_RUN)
    report["conflicts"] = _detect_attribute_conflicts(db, kb)
    report["fuzzy_pending"] = _fuzzy_alignment(db, kb, method=method)
    return report


def _live_entities(db, kb):
    return (
        db.query(GraphEntity)
        .filter(GraphEntity.kb_id == kb.id, GraphEntity.merged_into.is_(None))
        .all()
    )


def _exact_and_alias_merges(db, kb, *, max_merges: int) -> int:
    """同名（归一化后）与别名互命中的存活实体自动合并，记 accepted 留痕。"""
    entities = _live_entities(db, kb)
    by_norm: dict[str, GraphEntity] = {}
    alias_index: dict[str, GraphEntity] = {}
    for entity in entities:
        norm = _normalize_name(entity.name)
        if norm and norm not in by_norm:
            by_norm[norm] = entity
        for alias in entity.aliases or []:
            alias_norm = _normalize_name(str(alias))
            if alias_norm and alias_norm not in alias_index:
                alias_index[alias_norm] = entity

    merged = 0
    for entity in list(entities):
        if merged >= max_merges:
            break
        if entity.merged_into is not None:
            continue
        norm = _normalize_name(entity.name)
        target = by_norm.get(norm)
        if target is None or target.id == entity.id:
            # 名字本身没撞上时再看别名索引（别人的别名=自己的规范名候选）
            target = alias_index.get(norm)
        if target is None or target.id == entity.id:
            continue
        # 两个索引都是本轮开始时的快照：对方可能已在本轮里被合并（含已并入
        # 当前实体——互为别名的一对，反方向不必再合并）。先解析到最终存活者；
        # 不解析的话 merge_entities 会按防环分支抛异常，整个抽取任务被判失败
        # （缓存回放建的图所有实体同一秒创建，稳定触发——2026-11-24 实测）
        target = resolve_merged(db, target.id)
        if target is None or target.id == entity.id or target.merged_into is not None:
            continue
        if target.created_at and entity.created_at and entity.created_at < target.created_at:
            target, entity = entity, target
        if entity.merged_into is not None or entity.id == target.id:
            continue
        merge_entities(db, kb, target, entity, method="auto", reason="归一化同名自动归并")
        merged += 1
    return merged


def _detect_attribute_conflicts(db, kb) -> int:
    """同实体同属性不同值（跨文档）→ pending 冲突建议（幂等：已有 pending 不重复建）。"""
    created = 0
    entities = _live_entities(db, kb)
    existing_keys = {
        (s.entity_a_id, (s.payload or {}).get("attribute"))
        for s in db.query(KgMergeSuggestion)
        .filter(KgMergeSuggestion.kb_id == kb.id, KgMergeSuggestion.status == "pending",
                KgMergeSuggestion.type == "attribute_conflict")
        .all()
    }
    for entity in entities:
        attrs = (entity.properties or {}).get("attributes") or []
        by_name: dict[str, list[dict]] = {}
        for attr in attrs:
            name = str(attr.get("name") or "").strip()
            value = str(attr.get("value") or "").strip()
            if name and value:
                by_name.setdefault(name, []).append(attr)
        for name, items in by_name.items():
            values = {_norm_value(item.get("value")) for item in items}
            if len(values) <= 1:
                continue
            if (entity.id, name) in existing_keys:
                continue
            db.add(KgMergeSuggestion(
                kb_id=kb.id,
                type="attribute_conflict",
                status="pending",
                method="auto",
                entity_a_id=entity.id,
                payload={
                    "attribute": name,
                    "values": [
                        {"value": item.get("value"),
                         "doc_ids": [item.get("doc_id")] if item.get("doc_id") else [],
                         "evidence": item.get("evidence") or ""}
                        for item in items[:6]
                    ],
                },
            ))
            created += 1
    db.commit()
    return created


def _norm_value(value) -> str:
    return str(value or "").strip().lower()


def _fuzzy_alignment(db, kb, *, method: str) -> int:
    """difflib 高相似 + 类型相容的候选对 → LLM 仲裁 → pending 合并建议。"""
    threshold = _fuzzy_threshold()
    entities = _live_entities(db, kb)
    existing_pairs = {
        frozenset(filter(None, (s.entity_a_id, s.entity_b_id)))
        for s in db.query(KgMergeSuggestion)
        .filter(KgMergeSuggestion.kb_id == kb.id, KgMergeSuggestion.type == "merge_entity")
        .all()
        if s.entity_a_id or s.entity_b_id
    }
    candidates: list[tuple[GraphEntity, GraphEntity, float]] = []
    for i in range(len(entities)):
        for j in range(i + 1, len(entities)):
            a, b = entities[i], entities[j]
            if frozenset((a.id, b.id)) in existing_pairs:
                continue
            if a.entity_type != b.entity_type and "概念" not in (a.entity_type, b.entity_type):
                continue
            ratio = difflib.SequenceMatcher(None, a.name, b.name).ratio()
            if ratio >= threshold:
                candidates.append((a, b, ratio))
    candidates.sort(key=lambda item: -item[2])
    candidates = candidates[:MAX_FUZZY_PAIRS_PER_RUN]
    if not candidates:
        return 0

    verdicts = _llm_arbitrate(db, kb, [(a.name, b.name) for a, b, _ in candidates])
    created = 0
    for index, (a, b, ratio) in enumerate(candidates):
        same = True
        canonical = None
        reason = "LLM 仲裁不可用，按高相似度默认进人工队列"
        if verdicts is not None and index < len(verdicts):
            item = verdicts[index]
            same = bool(item.get("same", True))
            canonical = item.get("canonical") or None
            reason = item.get("reason") or reason
        if not same:
            continue
        winner, loser = (a, b) if (a.created_at or 0) <= (b.created_at or 0) else (b, a)
        db.add(KgMergeSuggestion(
            kb_id=kb.id,
            type="merge_entity",
            status="pending",
            method=method if verdicts is not None else "auto",
            entity_a_id=winner.id,
            entity_b_id=loser.id,
            canonical_name=canonical,
            similarity=round(ratio, 4),
            payload={"reason": reason[:500]},
        ))
        created += 1
    db.commit()
    return created


def _fuzzy_threshold() -> float:
    from app.config import settings

    return float(getattr(settings, "kg_fusion_fuzzy_threshold", 0.92))


def _llm_arbitrate(db, kb, pairs: list[tuple[str, str]]) -> list[dict] | None:
    """批量仲裁实体对是否同一实体；LLM 不可用返回 None（全部进人工队列）。"""
    try:
        from app.services.llm_gateway import resolve_profile
        from app.services.agent.llm_client import chat_completion_with_retry
        from app.services.agent.contracts import parse_llm_json, validate_contract
        from pydantic import BaseModel, Field

        class ArbitrationItem(BaseModel):
            index: int
            same: bool
            canonical: str | None = None
            reason: str | None = None

        class Arbitration(BaseModel):
            pairs: list[ArbitrationItem] = Field(default_factory=list)

        listing = "\n".join(f"{i + 1}. {a} | {b}" for i, (a, b) in enumerate(pairs))
        system = (
            "你是知识图谱实体对齐仲裁器。判断每对实体名是否指同一事物（同义/别名/"
            "译名算同一；同形异义算不同）。只输出 JSON，不要任何解释文字。骨架：\n"
            '{"pairs": [{"index": 1, "same": true, "canonical": "规范名", '
            '"reason": "简短理由"}]}'
        )
        user = (
            f"共 {len(pairs)} 对实体：\n{listing}\n"
            "index 从 1 开始且必须覆盖全部条目。"
        )
        config = resolve_profile(
            db,
            profile_id=getattr(kb, "kg_llm_profile_id", None),
            purpose="kg_fusion",
        )
        reply, _usage, error = chat_completion_with_retry(
            db, config=config,
            messages=[{"role": "system", "content": system},
                      {"role": "user", "content": user}],
            temperature=0.1, max_tokens=2000,
            purpose="kg_fusion", attempts=2, interval_seconds=2, max_wall_seconds=120,
            stream=False,
        )
        if error:
            return None
        data = validate_contract(Arbitration, parse_llm_json(reply))
        return [item.model_dump() for item in data.pairs]
    except Exception:  # noqa: BLE001 - 仲裁失败退化为「默认进人工队列」
        return None


# ---------------------------------------------------------------- 审核执行


def accept_suggestion(db, kb, suggestion, decided_by=None) -> dict:
    if suggestion.type == "merge_entity":
        winner = db.get(GraphEntity, suggestion.entity_a_id)
        loser = db.get(GraphEntity, suggestion.entity_b_id)
        if winner is None or loser is None:
            suggestion.status = "rejected"
            suggestion.apply_record = {"error": "entity missing"}
            db.commit()
            return {"status": "rejected", "reason": "entity missing"}
        if loser.merged_into is not None:
            suggestion.status = "rejected"
            suggestion.apply_record = {"error": "loser already merged"}
            db.commit()
            return {"status": "rejected", "reason": "loser already merged"}
        if suggestion.canonical_name and suggestion.canonical_name != winner.name:
            winner.aliases = list(winner.aliases or []) + [winner.name]
            winner.name = suggestion.canonical_name[:256]
        record = merge_entities(db, kb, winner, loser,
                                method=suggestion.method, reason="人工审核通过")
        suggestion.apply_record = record.apply_record
        return {"status": "accepted", "apply_record": record.apply_record}

    # attribute_conflict：采纳 payload 里选中的值（resolved 优先，否则首个）
    entity = db.get(GraphEntity, suggestion.entity_a_id)
    if entity is None:
        suggestion.status = "rejected"
        db.commit()
        return {"status": "rejected", "reason": "entity missing"}
    props = dict(entity.properties or {})
    attrs = list(props.get("attributes") or [])
    conflict_attr = (suggestion.payload or {}).get("attribute")
    values = (suggestion.payload or {}).get("values") or []
    chosen = (suggestion.payload or {}).get("resolved") or (values[0] if values else None)
    chosen_value = str((chosen or {}).get("value", "")).strip()
    attrs = [a for a in attrs if not (a.get("name") == conflict_attr and a.get("value") == chosen_value)]
    kept = [a for a in attrs if a.get("name") != conflict_attr]
    if chosen_value:
        kept.append({"name": conflict_attr, "value": chosen_value,
                     "evidence": (chosen or {}).get("evidence") or "",
                     "doc_id": ((chosen or {}).get("doc_ids") or [None])[0]})
    props["attributes"] = kept
    entity.properties = props
    suggestion.status = "accepted"
    suggestion.apply_record = {"attribute": conflict_attr, "resolved_value": chosen_value}
    now = datetime.datetime.utcnow()
    suggestion.decided_at = now
    suggestion.decided_by = decided_by
    db.commit()
    return {"status": "accepted", "apply_record": suggestion.apply_record}


def reject_suggestion(db, suggestion, decided_by=None) -> None:
    suggestion.status = "rejected"
    suggestion.decided_at = datetime.datetime.utcnow()
    suggestion.decided_by = decided_by
    db.commit()
