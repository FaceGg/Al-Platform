# -*- coding: utf-8 -*-
"""LLM 深度知识图谱抽取（五阶段流水线，阶段 2）。

与规则层（knowledge_graph_extraction.py，jieba 统计层）并存的第二抽取通道：
按 chunk 分片调用平台 LLM 网关，按「按库可配本体」约束实体/关系类型，输出经
pydantic 契约校验 + 单轮修复回路（坏输出喂回模型重试，raw 留档）。

设计要点：
- 结果写 properties.method="llm"（规则层是 "rules"），两层并存、重建互不影响；
- 单元结果缓存于 kg_unit_results（幂等键 kb_id+chunk_id+content_hash），
  任务中断/重跑天然断点续抽；
- 聚合落库前先清同 method 层；落库后跑融合自动归并 + Neo4j 投影（尽力而为）。
"""
import hashlib
import time
import uuid
from collections import Counter

from pydantic import BaseModel, Field

from app.config import settings
from app.database import SessionLocal
from app.models.knowledge import (
    Chunk,
    Document,
    GraphEntity,
    GraphRelation,
    KgExtractionJob,
    KgUnitResult,
)
from app.services.agent.contracts import (
    AgentContractError,
    parse_llm_json,
    validate_contract,
)
from app.services.agent.llm_client import chat_completion_with_retry
from app.services.kg_ontology import (
    FALLBACK_ENTITY_TYPE,
    FALLBACK_RELATION_TYPE,
    coerce_entity_type,
    coerce_relation_type,
    resolve_ontology,
)
from app.services.knowledge_graph_extraction import (
    _clear_auto_layer,
    _normalize_name,
)

MAX_ENTITIES_PER_UNIT = 20
MAX_RELATIONS_PER_UNIT = 15
MAX_ATTRIBUTES_PER_ENTITY = 8
MAX_EVIDENCE_LEN = 120

_OUTPUT_SKELETON = (
    '{"entities": [{"name": "示例实体", "type": "工艺", "aliases": ["别名"], '
    '"attributes": [{"name": "参数", "value": "10kN", "evidence": "原文短句"}]}], '
    '"relations": [{"source": "示例实体", "target": "另一实体", '
    '"type": "相关", "evidence": "原文短句"}]}'
)


class KgAttribute(BaseModel):
    name: str = Field(min_length=1, max_length=32)
    value: str = Field(min_length=1, max_length=128)
    evidence: str | None = None


class KgEntityOut(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    type: str = Field(default=FALLBACK_ENTITY_TYPE, max_length=32)
    aliases: list[str] = Field(default_factory=list)
    attributes: list[KgAttribute] = Field(default_factory=list)


class KgRelationOut(BaseModel):
    source: str = Field(min_length=1, max_length=64)
    target: str = Field(min_length=1, max_length=64)
    type: str = Field(default=FALLBACK_RELATION_TYPE, max_length=32)
    evidence: str | None = None


class KgUnitExtraction(BaseModel):
    entities: list[KgEntityOut] = Field(default_factory=list)
    relations: list[KgRelationOut] = Field(default_factory=list)


def _parse_unit(reply: str) -> KgUnitExtraction:
    return validate_contract(KgUnitExtraction, parse_llm_json(reply))


def build_messages(chunk_text: str, ontology: dict[str, list[str]]) -> list[dict]:
    entity_types = "、".join(ontology["entity_types"])
    relation_types = "、".join(ontology["relation_types"])
    system = (
        "你是工业知识图谱抽取引擎。从给定文本中抽取实体与实体间关系，"
        "只输出一个 JSON 对象，不要输出 JSON 以外的任何文字。\n"
        f"- 实体 type 必须逐字取自：{entity_types}；映射不上就用「{FALLBACK_ENTITY_TYPE}」\n"
        f"- 关系 type 必须逐字取自：{relation_types}；映射不上就用「{FALLBACK_RELATION_TYPE}」\n"
        f"- 实体最多 {MAX_ENTITIES_PER_UNIT} 个，关系最多 {MAX_RELATIONS_PER_UNIT} 个；"
        "实体 name 用文中原词（不含代词/虚词），source/target 必须引用 entities 里的 name；"
        "不在 entities 里的 name 一律丢弃\n"
        "- aliases 是同一实体的其他叫法（英文/缩写/全称），没有就给空数组\n"
        "- attributes 只收文中明确出现的属性（参数/规格/数值），逐条给 evidence 原文短句\n"
        "- 字段名必须与下面的骨架逐字一致，漏字段或改字段名会被拒收：\n"
        f"{_OUTPUT_SKELETON}"
    )
    user = (
        "【待抽取文本开始】\n"
        f"{chunk_text[: settings.kg_llm_batch_chars]}\n"
        "【待抽取文本结束】\n"
        "请输出 JSON。"
    )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


def _content_hash(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


def extract_unit(
    db,
    config,
    chunk_text: str,
    ontology: dict[str, list[str]],
    *,
    purpose: str = "kg_extraction",
) -> tuple[KgUnitExtraction | None, dict, str | None]:
    """单 chunk 抽取：契约校验失败带坏输出与错误喂回修复一次，仍败则留档报错。"""
    messages = build_messages(chunk_text, ontology)
    reply, usage, error = chat_completion_with_retry(
        db, config=config, messages=messages, temperature=0.1,
        max_tokens=settings.kg_llm_max_tokens,
        purpose=purpose, attempts=2, interval_seconds=2, max_wall_seconds=180,
    )
    if error:
        return None, usage, error
    try:
        return _parse_unit(reply), usage, None
    except AgentContractError as first_error:
        repair_messages = messages + [
            {"role": "assistant", "content": (reply or "")[:1500]},
            {
                "role": "user",
                "content": (
                    "上面的输出未通过契约校验。请严格按骨架重新输出 JSON，"
                    "不要输出任何解释文字。校验错误："
                    f"{str(first_error)[:800]}"
                ),
            },
        ]
        reply2, usage2, error2 = chat_completion_with_retry(
            db, config=config, messages=repair_messages, temperature=0.2,
            max_tokens=settings.kg_llm_max_tokens,
            purpose=purpose, attempts=2, interval_seconds=2, max_wall_seconds=180,
        )
        if error2:
            return None, {**(usage or {}), **(usage2 or {})}, error2
        try:
            return _parse_unit(reply2), usage2, None
        except AgentContractError:
            return None, usage2, (
                "kg_contract_failed after repair, raw evidence — "
                f"raw_first(截断): {(reply or '')[:1500]}; "
                f"raw_retry(截断): {(reply2 or '')[:1500]}; "
                f"error: {str(first_error)[:500]}"
            )


def _select_chunks(db, kb, params: dict) -> list[Chunk]:
    doc_ids = params.get("doc_ids") or None
    query = (
        db.query(Chunk)
        .join(Document, Chunk.document)
        .filter(Document.kb_id == kb.id)
    )
    if doc_ids:
        wanted = set(str(x) for x in doc_ids)
        query = query.filter(Document.id.in_(wanted))
    query = query.order_by(Document.created_at.asc(), Chunk.chunk_index.asc())
    chunks = query.all()
    cap = settings.kg_llm_max_chunks
    override = params.get("max_chunks")
    if isinstance(override, int) and override > 0:
        cap = min(cap, override)
    return chunks[:cap]


def run_kg_extraction_job(job_id: str) -> None:
    """任务主体：分片调 LLM → 聚合落库 → 融合自动归并 → Neo4j 投影。"""
    import datetime

    from app.services.kg_fusion import auto_fuse_after_extraction

    db = SessionLocal()
    job = None
    try:
        job = db.get(KgExtractionJob, uuid.UUID(job_id))
        if job is None or job.status not in ("pending", "running"):
            return
        kb = job.knowledge_base
        if kb is None:
            job.status = "failed"
            job.error = "knowledge base deleted"
            job.finished_at = datetime.datetime.utcnow()
            db.commit()
            return
        job.status = "running"
        job.started_at = datetime.datetime.utcnow()
        db.commit()

        ontology = resolve_ontology(kb)
        from app.services.llm_gateway import resolve_profile

        config = resolve_profile(db, purpose="kg_extraction")

        chunks = _select_chunks(db, kb, job.params or {})
        done_hashes = {
            row[0]
            for row in (
                db.query(KgUnitResult.content_hash)
                .join(Chunk, KgUnitResult.chunk_id == Chunk.id)
                .filter(
                    KgUnitResult.kb_id == kb.id,
                    KgUnitResult.status.in_(("ok", "empty")),
                )
                .all()
            )
        }
        todo = [c for c in chunks if _content_hash(c.content or "") not in done_hashes]
        job.total_units = len(todo)
        job.done_units = 0
        db.commit()

        deadline = time.monotonic() + settings.kg_llm_time_budget_seconds
        cancelled = False
        for chunk in todo:
            db.refresh(job)
            if job.cancel_requested:
                cancelled = True
                break
            if time.monotonic() > deadline:
                job.error = "time budget exceeded; re-run to continue remaining chunks"
                break
            content = chunk.content or ""
            if not content.strip():
                db.add(KgUnitResult(
                    kb_id=kb.id, chunk_id=chunk.id,
                    content_hash=_content_hash(content), status="empty",
                ))
                job.done_units += 1
                db.commit()
                continue
            unit, usage, error = extract_unit(db, config, content, ontology)
            job.llm_calls += 1
            if unit is None:
                job.llm_errors += 1
                db.add(KgUnitResult(
                    kb_id=kb.id, chunk_id=chunk.id,
                    content_hash=_content_hash(content), status="failed",
                    error=(error or "")[:2000],
                ))
            else:
                if not unit.entities and not unit.relations:
                    db.add(KgUnitResult(
                        kb_id=kb.id, chunk_id=chunk.id,
                        content_hash=_content_hash(content), status="empty",
                    ))
                else:
                    db.add(KgUnitResult(
                        kb_id=kb.id, chunk_id=chunk.id,
                        content_hash=_content_hash(content), status="ok",
                        result=unit.model_dump(),
                    ))
                job.entities_found += len(unit.entities)
                job.relations_found += len(unit.relations)
            job.done_units += 1
            db.commit()

        fused = _aggregate_and_persist(db, kb, ontology)
        auto_fuse_after_extraction(db, kb, method="llm")
        _project_to_neo4j(db, kb)

        db.refresh(job)
        job.entities_found = fused["entities"]
        job.relations_found = fused["relations"]
        if cancelled:
            job.status = "cancelled"
        elif job.status == "running":
            job.status = "succeeded"
        job.finished_at = datetime.datetime.utcnow()
        db.commit()
    except Exception as error:  # noqa: BLE001 - 任务层兜底：失败原因进 job 行
        if job is not None:
            import datetime

            job.status = "failed"
            job.error = f"{type(error).__name__}: {error}"[:2000]
            job.finished_at = datetime.datetime.utcnow()
        raise
    finally:
        db.close()


def _project_to_neo4j(db, kb) -> None:
    """投影失败不阻断抽取主链路（图查询有 PG 兜底）。"""
    try:
        from app.services.kg_projection import get_projection

        get_projection().resync_kb(db, kb.id)
    except Exception:  # noqa: BLE001
        pass


def _aggregate_and_persist(db, kb, ontology: dict[str, list[str]]) -> dict:
    """聚合全部 ok 单元结果 → 清 method=llm 层 → 批量落实体与关系。

    聚合范围是该库的全部 ok 结果（跨任务累积），文档重传导致旧 chunk 被级联
    删除时，其单元结果也随 FK CASCADE 清掉，不会留下陈旧贡献。
    """
    rows = (
        db.query(KgUnitResult)
        .filter(KgUnitResult.kb_id == kb.id, KgUnitResult.status == "ok")
        .all()
    )
    # chunk -> document 的映射：同一 chunk 只属一个文档
    chunk_pairs = (
        db.query(Chunk.id, Chunk.doc_id)
        .join(Document, Chunk.document)
        .filter(Document.kb_id == kb.id)
        .all()
    )
    chunk_doc = {str(cid): str(did) for cid, did in chunk_pairs}

    entities: dict[str, dict] = {}
    relations: dict[tuple[str, str, str], dict] = {}

    for row in rows:
        data = row.result or {}
        doc_id = chunk_doc.get(str(row.chunk_id)) if row.chunk_id else None
        for ent in data.get("entities", []):
            name = _normalize_name(str(ent.get("name", "")))
            if not name:
                continue
            record = entities.get(name)
            if record is None:
                record = {
                    "name": name,
                    "type": Counter(),
                    "aliases": [],
                    "aliases_set": set(),
                    "attributes": [],
                    "attributes_set": set(),
                    "freq": 0,
                    "doc_ids": set(),
                }
                entities[name] = record
            record["type"][coerce_entity_type(str(ent.get("type", "")), ontology)] += 1
            record["freq"] += 1
            if doc_id:
                record["doc_ids"].add(doc_id)
            for alias in ent.get("aliases") or []:
                alias_name = _normalize_name(str(alias))
                if alias_name and alias_name != name and alias_name not in record["aliases_set"]:
                    record["aliases"].append(alias_name)
                    record["aliases_set"].add(alias_name)
            for attr in ent.get("attributes") or []:
                item = {
                    "name": str(attr.get("name", ""))[:32],
                    "value": str(attr.get("value", ""))[:128],
                    "evidence": str(attr.get("evidence") or "")[:200],
                    "doc_id": doc_id,
                }
                if not item["name"] or not item["value"]:
                    continue
                dedup_key = (item["name"], item["value"])
                if dedup_key not in record["attributes_set"]:
                    record["attributes_set"].add(dedup_key)
                    record["attributes"].append(item)

        for rel in data.get("relations", []):
            src = _normalize_name(str(rel.get("source", "")))
            dst = _normalize_name(str(rel.get("target", "")))
            if not src or not dst or src == dst:
                continue
            if src not in entities or dst not in entities:
                continue
            rtype = coerce_relation_type(str(rel.get("type", "")), ontology)
            key = (src, dst, rtype)
            record = relations.get(key)
            if record is None:
                record = {"weight": 0, "evidence": ""}
                relations[key] = record
            record["weight"] += 1
            if not record["evidence"]:
                record["evidence"] = str(rel.get("evidence") or "")[:MAX_EVIDENCE_LEN]

    _clear_auto_layer(db, kb.id, method="llm")
    # 实体链接（基础层）：与存活实体（manual/rules 层）归一化同名/别名命中时
    # 复用其 id 不新建节点——同名唯一索引不允许重复，这也是消歧的正确语义。
    from app.services.kg_names import existing_entity_index

    existing_index = existing_entity_index(db, kb.id)

    entity_objects: list[GraphEntity] = []
    entity_ids: dict[str, uuid.UUID] = {}
    for name, record in entities.items():
        reused = existing_index.get(name)
        if reused is not None:
            entity_ids[name] = reused
            continue
        eid = uuid.uuid4()
        entity_ids[name] = eid
        top_type = record["type"].most_common(1)
        entity_objects.append(GraphEntity(
            id=eid,
            kb_id=kb.id,
            name=name,
            entity_type=top_type[0][0] if top_type else FALLBACK_ENTITY_TYPE,
            aliases=record["aliases"][:8],
            properties={
                "source": "auto",
                "method": "llm",
                "freq": record["freq"],
                "doc_ids": sorted(record["doc_ids"]),
                "attributes": record["attributes"][:MAX_ATTRIBUTES_PER_ENTITY],
            },
        ))
    db.add_all(entity_objects)
    db.flush()

    relation_objects: list[GraphRelation] = []
    for (src, dst, rtype), record in relations.items():
        relation_objects.append(GraphRelation(
            kb_id=kb.id,
            source_id=entity_ids[src],
            target_id=entity_ids[dst],
            relation_type=rtype,
            properties={
                "source": "auto",
                "method": "llm",
                "weight": record["weight"],
                "evidence": record["evidence"],
            },
        ))
    db.add_all(relation_objects)
    db.commit()
    return {"entities": len(entity_objects), "relations": len(relation_objects)}
