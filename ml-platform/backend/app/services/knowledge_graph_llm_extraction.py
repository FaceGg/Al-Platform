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

MAX_ENTITIES_PER_UNIT = 10
MAX_RELATIONS_PER_UNIT = 8
MAX_ATTRIBUTES_PER_ENTITY = 4
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
        "- 只抽明确出现的实体，不要推断补全；输出务必精简（输出越长越慢）\n"
        "- aliases 是同一实体的其他叫法（英文/缩写/全称），没有就给空数组\n"
        "- attributes 只收文中明确出现的数值/规格/参数，最多 4 条，逐条给 evidence 原文短句\n"
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
    """单 chunk 抽取：契约校验失败带坏输出与错误喂回修复一次，仍败则留档报错。

    attempts=1 + max_wall=120 的硬超时：出口卡流时单次尝试最长被网关流护栏
    拖到数分钟——任务循环靠「failed 单元 + 断点续抽」兜底重做，比长时间挂死
    更可控（取消请求也能在 ~2 分钟内落地）。
    """
    messages = build_messages(chunk_text, ontology)
    reply, usage, error = chat_completion_with_retry(
        db, config=config, messages=messages, temperature=0.1,
        max_tokens=settings.kg_llm_max_tokens,
        purpose=purpose, attempts=1, interval_seconds=2, max_wall_seconds=120,
        # 出口对 SSE 流式干扰严重时（LLMStreamStalled 大面积出现）改走
        # 非流式通道：一次性 POST 等完整 JSON（网关 stream=False 分支）；
        # 并禁用 web_search 工具注入（结构化批任务注入联网工具会让模型
        # 行为飘忽/输出空——2026-11-23 实测）
        stream=False,
        web_search=False,
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
            purpose=purpose, attempts=1, interval_seconds=2, max_wall_seconds=120,
            stream=False,
            web_search=False,
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

    # 任务全程使用任务级独立 engine：全局 SessionLocal 的连接池来自 celery
    # fork 前的进程，fork 后首次 checkout 会卡死在 provisioning（InvalidRequest
    # Error 实证 2026-11-20），任务行永远停在 running。独立池干净且线程安全，
    # 主流程与线程池 worker 共用它（pool 层加锁）。
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    db_url = settings.database_url
    if hasattr(db_url, "get_secret_value"):
        db_url = db_url.get_secret_value()
    job_engine = create_engine(
        str(db_url),
        pool_size=max(3, int(getattr(settings, "kg_llm_concurrency", 2)) + 2),
        max_overflow=4,
        pool_pre_ping=True,
    )
    WorkerSession = sessionmaker(bind=job_engine)
    db = WorkerSession()
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

        # 按库指定的抽取档案优先；未配置跟随平台默认档案
        config = resolve_profile(
            db,
            profile_id=getattr(kb, "kg_llm_profile_id", None),
            purpose="kg_extraction",
        )

        chunks = _select_chunks(db, kb, job.params or {})
        # force（重新提取）：忽略单元缓存重做全部分片，并清空 llm 层重建——
        # 语义=「用当前模型/词表重新生成图谱」，与断点续抽（跳过已完成）互补
        force = bool((job.params or {}).get("force"))
        if force:
            _clear_auto_layer(db, kb.id, method="llm")
            db.commit()
        done_hashes = set() if force else {
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
        # 分片任务物化为纯值（id+content）：ORM 对象传入线程后，属性访问会因
        # commit 过期触发「用主线程会话在工作线程里重载」→ Session 跨线程并发
        # （InvalidRequestError 实证 2026-11-20）。线程池只收普通值。
        todo = [
            (c.id, c.content or "")
            for c in chunks
            if _content_hash(c.content or "") not in done_hashes
        ]
        job.total_units = len(todo)
        job.done_units = 0
        db.commit()

        deadline = time.monotonic() + settings.kg_llm_time_budget_seconds
        cancelled = False
        # 失败分片重试队列（主循环收集，收尾统一重试一轮）
        retry_chunks: list = []
        # 流式构建的实体链接索引：norm 名/别名 → 实体 id，跨分片累积
        from app.services.kg_names import existing_entity_index

        entity_index = existing_entity_index(db, kb.id)

        # 线程池 worker 复用任务级独立 engine（函数开头创建的 job_engine）：
        # 与全局 SessionLocal 的 fork 池彻底隔离，pool 层加锁多线程安全

        def _work(unit_chunk):
            """线程池 worker：入参为纯值 (chunk_id, content)，零 ORM 访问。"""
            chunk_id, content = unit_chunk
            if not content.strip():
                return chunk_id, content, "empty", None, None, 0
            with WorkerSession() as worker_db:
                unit, usage, error = extract_unit(worker_db, config, content, ontology)
            if unit is None:
                return chunk_id, content, "failed", None, error, 1
            if not unit.entities and not unit.relations:
                return chunk_id, content, "empty", None, None, 1
            return chunk_id, content, "ok", unit, None, 1

        from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED

        pool = ThreadPoolExecutor(
            max_workers=max(1, int(getattr(settings, "kg_llm_concurrency", 2))),
            thread_name_prefix="kg-extract",
        )
        try:
            futures = {pool.submit(_work, c): c for c in todo}
            pending = set(futures)
            while pending:
                db.refresh(job)
                if job.cancel_requested or time.monotonic() > deadline:
                    cancelled = job.cancel_requested
                    if not job.cancel_requested:
                        job.error = (
                            "time budget exceeded; re-run to continue remaining chunks"
                        )
                    break
                # 150s 看门狗：整批无任何分片落地=LLM 出口卡死——放弃本批剩余
                # 分片（failed/未完成的靠断点续抽重做），避免任务无限挂死
                done_set, pending = wait(
                    pending, timeout=150, return_when=FIRST_COMPLETED,
                )
                if not done_set:
                    job.error = (
                        "LLM calls stalled (>150s with no chunk completed); "
                        "re-run to retry unfinished chunks"
                    )
                    break
                for future in done_set:
                    chunk_id, content, status, unit, error, calls = future.result()
                    job.llm_calls += calls
                    content_hash = _content_hash(content)
                    # upsert：failed 分片续抽重做时旧行还在（唯一约束），更新
                    # 原行而不是插入——重试成功会把 failed 行转 ok
                    unit_row = (
                        db.query(KgUnitResult)
                        .filter(
                            KgUnitResult.kb_id == kb.id,
                            KgUnitResult.chunk_id == chunk_id,
                            KgUnitResult.content_hash == content_hash,
                        )
                        .first()
                    )
                    if unit_row is None:
                        unit_row = KgUnitResult(
                            kb_id=kb.id, chunk_id=chunk_id,
                            content_hash=content_hash, status=status,
                        )
                        db.add(unit_row)
                    unit_row.status = status
                    unit_row.error = (error or "")[:2000] if status == "failed" else None
                    if status == "failed":
                        job.llm_errors += 1
                        retry_chunks.append((chunk_id, content))
                    elif status == "ok":
                        unit_row.result = unit.model_dump()
                        # 流式构建：分片结果即时并入图（画布随抽取实时成长）
                        _merge_unit_into_graph(
                            db, kb, ontology, unit.model_dump(),
                            chunk_id=chunk_id, entity_index=entity_index,
                        )
                        job.entities_found += len(unit.entities)
                        job.relations_found += len(unit.relations)
                    job.done_units += 1
                    db.commit()
        finally:
            if cancelled:
                pool.shutdown(wait=False, cancel_futures=True)
            else:
                pool.shutdown(wait=True)
            job_engine.dispose()

        # 失败分片自动重试一轮：出口故障呈间歇性（同一分片隔几分钟重跑即可
        # 成功），跨时间重试一轮能熬过多数故障窗口；仍失败的留给断点续抽。
        # 池已在 finally 收尾——重试轮用临时池。
        if retry_chunks and not cancelled and time.monotonic() < deadline:
            from concurrent.futures import ThreadPoolExecutor as _TPE

            retry_pool = _TPE(max_workers=1, thread_name_prefix="kg-retry")
            try:
                retry_futures = {retry_pool.submit(_work, c): c for c in retry_chunks}
                retry_pending = set(retry_futures)
                while retry_pending:
                    db.refresh(job)
                    if job.cancel_requested or time.monotonic() > deadline:
                        break
                    done_set, retry_pending = wait(
                        retry_pending, timeout=150, return_when=FIRST_COMPLETED,
                    )
                    for future in done_set:
                        chunk_id, content, status, unit, error, calls = future.result()
                        job.llm_calls += calls
                        unit_row = (
                            db.query(KgUnitResult)
                            .filter(
                                KgUnitResult.kb_id == kb.id,
                                KgUnitResult.chunk_id == chunk_id,
                                KgUnitResult.content_hash == _content_hash(content),
                            )
                            .first()
                        )
                        if unit_row is None:
                            unit_row = KgUnitResult(
                                kb_id=kb.id, chunk_id=chunk_id,
                                content_hash=_content_hash(content), status=status,
                            )
                            db.add(unit_row)
                        unit_row.status = status
                        unit_row.error = (error or "")[:2000] if status == "failed" else None
                        if status == "failed":
                            job.llm_errors += 1
                        elif status == "ok":
                            unit_row.result = unit.model_dump()
                            _merge_unit_into_graph(
                                db, kb, ontology, unit.model_dump(),
                                chunk_id=chunk_id, entity_index=entity_index,
                            )
                            job.entities_found += len(unit.entities)
                            job.relations_found += len(unit.relations)
                        job.done_units += 1
                        db.commit()
            finally:
                retry_pool.shutdown(wait=True)

        # 流式构建：分片结果已即时并入图（_merge_unit_into_graph），无需最后
        # 统一聚合。融合自动归并收口一次 + 投影全量重建。
        auto_fuse_after_extraction(db, kb, method="llm")
        _project_to_neo4j(db, kb)

        db.refresh(job)
        if cancelled:
            job.status = "cancelled"
        elif job.status == "running":
            job.status = "succeeded"
        job.finished_at = datetime.datetime.utcnow()
        db.commit()
    except Exception as error:  # noqa: BLE001 - 任务层兜底：失败原因进 job 行
        if job is not None:
            import datetime

            job_id = job.id
            # 原 db 会话可能已损坏（并发错误/连接中断）——用全新会话兜底写
            # 失败状态，否则任务行会永远停在 running（2026-11-20 实证）
            try:
                db.rollback()
                job.status = "failed"
                job.error = f"{type(error).__name__}: {error}"[:2000]
                job.finished_at = datetime.datetime.utcnow()
                db.commit()
            except Exception:  # noqa: BLE001 - 双保险：换新会话再写一次
                try:
                    from app.database import SessionLocal as _SL

                    with _SL() as fresh:
                        row = fresh.get(KgExtractionJob, job_id)
                        if row is not None:
                            row.status = "failed"
                            row.error = f"{type(error).__name__}: {error}"[:2000]
                            row.finished_at = datetime.datetime.utcnow()
                            fresh.commit()
                except Exception:  # noqa: BLE001
                    pass
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


# DEPRECATED：已被流式构建 _merge_unit_into_graph 取代（分片完成即时并入图，
# 画布实时成长）；保留仅供回溯，无调用方。
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


def _merge_unit_into_graph(
    db, kb, ontology: dict[str, list[str]], unit_data: dict, *,
    chunk_id, entity_index: dict,
) -> None:
    """单个分片结果即时并入图（流式成长）。

    - 实体链接：norm 名/别名命中 entity_index 时复用既有实体（freq+1、别名/
      属性并集），否则新建（紫色以外默认类型着色由前端分组处理）；
    - 关系 MERGE 式：同 (source,target,type) 已存在则 weight+1，否则插入；
    - entity_index 跨分片累积（调用方持有），保证后续分片的引用落到同一节点。
    """
    from app.services.kg_names import normalize_name

    resolved: dict[str, "uuid.UUID"] = {}
    chunk_doc_id = None
    if chunk_id is not None:
        chunk_row = db.get(Chunk, chunk_id)
        if chunk_row is not None:
            chunk_doc_id = str(chunk_row.doc_id)

    for ent in unit_data.get("entities", []):
        name = normalize_name(str(ent.get("name", "")))
        if not name:
            continue
        eid = entity_index.get(name)
        if eid is None:
            eid = uuid.uuid4()
            entity_index[name] = eid
            db.add(GraphEntity(
                id=eid, kb_id=kb.id, name=name,
                entity_type=coerce_entity_type(str(ent.get("type", "")), ontology),
                aliases=[
                    a for a in (
                        normalize_name(str(x)) for x in (ent.get("aliases") or [])
                    ) if a and a != name
                ][:8],
                properties={
                    "source": "auto", "method": "llm", "freq": 1,
                    "doc_ids": [chunk_doc_id] if chunk_doc_id else [],
                    "attributes": [
                        {
                            "name": str(a.get("name", ""))[:32],
                            "value": str(a.get("value", ""))[:128],
                            "evidence": str(a.get("evidence") or "")[:200],
                            "doc_id": chunk_doc_id,
                        }
                        for a in (ent.get("attributes") or [])[:MAX_ATTRIBUTES_PER_ENTITY]
                        if str(a.get("name", "")).strip() and str(a.get("value", "")).strip()
                    ],
                },
            ))
        else:
            row = db.get(GraphEntity, eid)
            if row is None:
                continue
            aliases = list(row.aliases or [])
            for alias in (normalize_name(str(x)) for x in (ent.get("aliases") or [])):
                if alias and alias != row.name and alias not in aliases:
                    aliases.append(alias)
            props = dict(row.properties or {})
            props["freq"] = int(props.get("freq") or 0) + 1
            doc_ids = set(props.get("doc_ids") or [])
            if chunk_doc_id:
                doc_ids.add(chunk_doc_id)
            props["doc_ids"] = sorted(doc_ids)
            attrs = list(props.get("attributes") or [])
            have = {(a.get("name"), a.get("value")) for a in attrs}
            for a in (ent.get("attributes") or [])[:MAX_ATTRIBUTES_PER_ENTITY]:
                key = (str(a.get("name", ""))[:32], str(a.get("value", ""))[:128])
                if key[0] and key[1] and key not in have:
                    attrs.append({
                        "name": key[0], "value": key[1],
                        "evidence": str(a.get("evidence") or "")[:200],
                        "doc_id": chunk_doc_id,
                    })
                    have.add(key)
            props["attributes"] = attrs[:12]
            row.properties = props
            row.aliases = aliases[:8]
        resolved[name] = eid

    for rel in unit_data.get("relations", []):
        src = normalize_name(str(rel.get("source", "")))
        dst = normalize_name(str(rel.get("target", "")))
        if not src or not dst or src == dst:
            continue
        if src not in resolved or dst not in resolved:
            continue
        rtype = coerce_relation_type(str(rel.get("type", "")), ontology)
        s_id, t_id = resolved[src], resolved[dst]
        existing = (
            db.query(GraphRelation)
            .filter(
                GraphRelation.kb_id == kb.id,
                GraphRelation.source_id == s_id,
                GraphRelation.target_id == t_id,
                GraphRelation.relation_type == rtype,
            )
            .first()
        )
        evidence = str(rel.get("evidence") or "")[:MAX_EVIDENCE_LEN]
        if existing is not None:
            props = dict(existing.properties or {})
            props["weight"] = int(props.get("weight") or 0) + 1
            if not props.get("evidence"):
                props["evidence"] = evidence
            existing.properties = props
        else:
            db.add(GraphRelation(
                kb_id=kb.id, source_id=s_id, target_id=t_id,
                relation_type=rtype,
                properties={
                    "source": "auto", "method": "llm",
                    "weight": 1, "evidence": evidence,
                },
            ))
    db.commit()
