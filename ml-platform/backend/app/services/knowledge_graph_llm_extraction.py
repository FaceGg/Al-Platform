# -*- coding: utf-8 -*-
"""LLM 深度知识图谱抽取（五阶段流水线，阶段 2）。

按 chunk 分片调用平台 LLM 网关，按「按库可配本体」约束实体/关系类型，输出经
pydantic 契约校验 + 单轮修复回路（坏输出喂回模型重试，raw 留档）。

设计要点：
- 结果写 properties.method="llm"。快速抽取（knowledge_graph_extraction.py，jieba
  统计层）与深度抽取**不并存，以最后一次抽取为主**：谁后跑，库内就只留谁的结果
  （见 clear_extraction_results / current_layer）；
- 单元结果缓存于 kg_unit_results（幂等键 kb_id+chunk_id+content_hash），是「每个
  分片最近一次大模型抽取的结果」：任务中断/新增文档后续抽只做没抽过的分片；
  被快速抽取替换后再切回深度抽取，抽过的分片直接按缓存重建、不再调用大模型；
  force（全部重新抽取）则作废缓存、清空图谱重做全部分片；
- 流式构建：每个分片完成即并入图（画布实时成长）；任务的「实体 N · 关系 M」
  按库内存活实体/关系去重计数（graph_ids），与画布标题栏同口径；
- 任务收尾跑融合自动归并 + Neo4j 投影（尽力而为）。
"""
import hashlib
import time
import uuid
# 模块级导入：测试可 patch wait 来确定性地模拟「看门狗窗口内无分片落地」
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait

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
from app.services.knowledge_graph_extraction import _clear_auto_layer

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


def current_layer(db, kb_id) -> str | None:
    """库内当前抽取结果的来源："rules" / "llm" / "mixed" / None（未抽取）。

    「以最后一次抽取为主」（2026-11-24 用户指示）：快速抽取与深度抽取不并存，
    一个库的抽取结果只有一种来源。mixed 只出现在该规则上线前的存量数据上
    （两层并存时期的库），下一次抽取——无论哪一种——会整体重建。
    """
    methods = {
        row[0]
        for row in db.query(GraphEntity.properties["method"].as_string())
        .filter(
            GraphEntity.kb_id == kb_id,
            GraphEntity.merged_into.is_(None),
            GraphEntity.properties["source"].as_string() == "auto",
        )
        .distinct()
        .all()
    }
    if not methods:
        return None
    return next(iter(methods)) if len(methods) == 1 else "mixed"


def clear_extraction_results(db, kb_id) -> None:
    """清空库内全部抽取结果（快速抽取 + 深度抽取），手工行保留；不提交事务。

    两种方法各走既有的层清理（连带删除触及这些实体的关系）；两端都落在手工
    实体上的抽取关系不经过抽取实体，按来源标记单独删。
    """
    _clear_auto_layer(db, kb_id, method="rules")
    _clear_auto_layer(db, kb_id, method="llm")
    db.query(GraphRelation).filter(
        GraphRelation.kb_id == kb_id,
        GraphRelation.properties["source"].as_string() == "auto",
    ).delete(synchronize_session=False)


def graph_ids(db, kb_id) -> tuple[set, set]:
    """库内图谱规模的 id 集：(存活实体, 端点都存活的关系)——与 GET /graph 同口径。

    任务进度里的「实体 N · 关系 M」与画布标题栏的数字都按它计，两边逐项相等。
    """
    entity_ids = {
        row[0]
        for row in db.query(GraphEntity.id)
        .filter(GraphEntity.kb_id == kb_id, GraphEntity.merged_into.is_(None))
        .all()
    }
    relation_ids = {
        row[0]
        for row in db.query(
            GraphRelation.id, GraphRelation.source_id, GraphRelation.target_id,
        ).filter(GraphRelation.kb_id == kb_id).all()
        if row[1] in entity_ids and row[2] in entity_ids
    }
    return entity_ids, relation_ids


def graph_totals(db, kb_id) -> tuple[int, int]:
    """库内图谱规模：(存活实体数, 端点都存活的关系数)——与 GET /graph 同口径。

    状态标注里的「实体 N · 关系 M」用这组数。子查询计数，不把关系行读进内存
    （大库的关系表有几十万行，摘要接口每次选中知识库都会调）。
    """
    from sqlalchemy import func

    live = (
        db.query(GraphEntity.id)
        .filter(GraphEntity.kb_id == kb_id, GraphEntity.merged_into.is_(None))
        .subquery()
    )
    entities = db.query(func.count()).select_from(live).scalar() or 0
    relations = (
        db.query(func.count(GraphRelation.id))
        .filter(
            GraphRelation.kb_id == kb_id,
            GraphRelation.source_id.in_(db.query(live.c.id)),
            GraphRelation.target_id.in_(db.query(live.c.id)),
        )
        .scalar() or 0
    )
    return int(entities), int(relations)


def _drop_unit_cache(db, kb_id) -> None:
    """「全部重新抽取」时作废分片缓存（不提交事务）。

    缓存记的是每个分片最近一次大模型抽取的结果：保留它，重抽中断后剩余分片
    会被旧结果顶替，「重新抽取」名不副实；作废后剩余分片如实算作待抽
    （2026-11-24 实测：重抽 3/18 片中断，缓存仍是 18 片全部完成，界面显示
    待抽 0 片、没有「继续抽取」入口）。
    """
    db.query(KgUnitResult).filter(KgUnitResult.kb_id == kb_id).delete(
        synchronize_session=False,
    )


def extract_unit(
    db,
    config,
    chunk_text: str,
    ontology: dict[str, list[str]],
    *,
    purpose: str = "kg_extraction",
    stream: bool | None = None,
) -> tuple[KgUnitExtraction | None, dict, str | None]:
    """单 chunk 抽取：契约校验失败带坏输出与错误喂回修复一次，仍败则留档报错。

    attempts=1 + max_wall=120 的硬超时：出口卡流时单次尝试最长被网关流护栏
    拖到数分钟——任务循环靠「failed 单元 + 断点续抽」兜底重做，比长时间挂死
    更可控（取消请求也能在 ~2 分钟内落地）。
    """
    messages = build_messages(chunk_text, ontology)
    # stream 缺省时按 kg_llm_use_nonstream 配置（True=非流式通道）；
    # 显式传入则覆盖（测试/特殊调用）
    use_stream = (not getattr(settings, "kg_llm_use_nonstream", True)) if stream is None else stream
    reply, usage, error = chat_completion_with_retry(
        db, config=config, messages=messages, temperature=0.1,
        max_tokens=settings.kg_llm_max_tokens,
        purpose=purpose, attempts=1, interval_seconds=2, max_wall_seconds=120,
        # 出口对 SSE 流式干扰严重时（LLMStreamStalled 大面积出现）改走
        # 非流式通道：一次性 POST 等完整 JSON（网关 stream=False 分支）；
        # 并禁用 web_search 工具注入（结构化批任务注入联网工具会让模型
        # 行为飘忽/输出空——2026-11-23 实测）
        stream=use_stream,
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
            stream=stream,
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
        # force（全部重新抽取）：作废单元缓存，清空图谱重做全部分片——语义=
        # 「用当前模型/词表重新生成图谱」
        force = bool((job.params or {}).get("force"))
        # 以最后一次抽取为主：当前图谱不是纯深度抽取结果（快速抽取生成的，或
        # 两层并存时期留下的混杂数据）时，先整体清空再重建；已是深度抽取结果
        # 则在原结果上续建（断点续抽 / 新增文档），已有的产出不动
        rebuild = force or current_layer(db, kb.id) != "llm"
        if rebuild:
            clear_extraction_results(db, kb.id)
        if force:
            _drop_unit_cache(db, kb.id)
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
        # 回放缓存：图谱整体重建时，抽过的分片直接按缓存并入，不再调用大模型
        # （force 已作废缓存，无缓存可回放）。按文档顺序回放，实体链接结果与
        # 首次抽取一致
        replay: list = []
        if rebuild:
            order = {c.id: index for index, c in enumerate(chunks)}
            replay = sorted(
                (
                    row for row in db.query(KgUnitResult).filter(
                        KgUnitResult.kb_id == kb.id,
                        KgUnitResult.status == "ok",
                        KgUnitResult.chunk_id.in_(list(order)),
                    ).all()
                    if row.result
                ),
                key=lambda row: order[row.chunk_id],
            )
        job.total_units = len(replay) + len(todo)
        job.done_units = 0
        db.commit()

        deadline = time.monotonic() + settings.kg_llm_time_budget_seconds
        cancelled = False
        # 失败分片重试队列（主循环收集，收尾统一重试一轮）
        retry_chunks: list = []
        # 流式构建的实体链接索引：norm 名/别名 → 实体 id，跨分片累积
        from app.services.kg_names import existing_entity_index

        entity_index = existing_entity_index(db, kb.id)
        # 进度口径「实体 N · 关系 M」= 库内图谱规模（去重后的存活实体/关系数，
        # 与画布标题栏同口径），不是各分片结果的累加——同一实体在多个分片出现
        # 只算一个。从当前图谱起算：续抽时已有的产出仍算数；worker 重启/任务
        # 重投后计数也不丢。
        job_entity_ids, job_relation_ids = graph_ids(db, kb.id)
        failed_chunk_ids: set = set()
        ok_chunk_ids: set = set()
        chunk_errors: dict = {}
        for row in replay:
            touched_entities, touched_relations = _merge_unit_into_graph(
                db, kb, ontology, row.result,
                chunk_id=row.chunk_id, entity_index=entity_index,
            )
            job_entity_ids.update(touched_entities)
            job_relation_ids.update(touched_relations)
            job.done_units += 1
        job.entities_found = len(job_entity_ids)
        job.relations_found = len(job_relation_ids)
        db.commit()

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

        def _record(chunk_id, content, status, unit, error, calls) -> None:
            """落地一个分片的结果（单元结果 upsert；成功则即时并入图），单事务提交。"""
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
                failed_chunk_ids.add(chunk_id)
                ok_chunk_ids.discard(chunk_id)
                if error:
                    chunk_errors[chunk_id] = error
                retry_chunks.append((chunk_id, content))
            elif status == "ok":
                unit_row.result = unit.model_dump()
                # 流式构建：分片结果即时并入图（画布随抽取实时成长）
                touched_entities, touched_relations = _merge_unit_into_graph(
                    db, kb, ontology, unit.model_dump(),
                    chunk_id=chunk_id, entity_index=entity_index,
                )
                job_entity_ids.update(touched_entities)
                job_relation_ids.update(touched_relations)
                ok_chunk_ids.add(chunk_id)
                failed_chunk_ids.discard(chunk_id)
            job.entities_found = len(job_entity_ids)
            job.relations_found = len(job_relation_ids)
            # 失败片数按「最终仍失败的分片」计（重试成功的不算），重试不会翻倍
            job.llm_errors = len(failed_chunk_ids)
            job.done_units += 1
            db.commit()

        def _run_batch(executor, batch) -> bool:
            """提交一批分片并逐个落地；返回 True=整批处理完毕。

            取消 / 时间预算耗尽 / 整批卡死（看门狗窗口内无任何分片落地）时
            提前返回 False，未落地的分片留给断点续抽。
            """
            nonlocal cancelled
            pending = {executor.submit(_work, c): c for c in batch}
            while pending:
                db.refresh(job)
                if job.cancel_requested or time.monotonic() > deadline:
                    cancelled = job.cancel_requested
                    if not job.cancel_requested:
                        job.error = (
                            "time budget exceeded; re-run to continue remaining chunks"
                        )
                        db.commit()
                    return False
                # 看门狗：整批无任何分片落地=LLM 出口卡死——放弃本批剩余分片。
                # 阈值必须大于单次调用的最长合法耗时：非流式通道单次 HTTP 上限
                # 240s → 300s；流式通道出字后 60s 无数据即报 stalled → 150s。
                # （此前三元表达式写反：非流式拿到 150s，慢但正常的分片被当成
                # 卡死，任务 3/18 片就提前结束——2026-11-24 实测）
                watchdog = 300 if getattr(settings, "kg_llm_use_nonstream", True) else 150
                done_set, pending = wait(
                    pending, timeout=watchdog, return_when=FIRST_COMPLETED,
                )
                if not done_set:
                    job.error = (
                        f"LLM calls stalled (>{watchdog}s with no chunk completed); "
                        "re-run to retry unfinished chunks"
                    )
                    db.commit()
                    return False
                for future in done_set:
                    _record(*future.result())
            return True

        pool = ThreadPoolExecutor(
            max_workers=max(1, int(getattr(settings, "kg_llm_concurrency", 2))),
            thread_name_prefix="kg-extract",
        )
        # 主批次是否整批处理完（看门狗/时间预算/取消会让它提前结束）
        completed = False
        try:
            completed = _run_batch(pool, todo)
            if completed:
                # 失败分片自动重试一轮：出口故障呈间歇性（同一分片隔几分钟重跑
                # 即可成功），跨时间重试一轮能熬过多数故障窗口；仍失败的留给断点
                # 续抽。重试片计入 total_units（否则进度会出现 36/18）。
                if retry_chunks and time.monotonic() < deadline:
                    retry_batch = list(dict.fromkeys(retry_chunks))
                    retry_chunks.clear()  # 重试轮内再失败不入队：只重试一轮
                    job.total_units += len(retry_batch)
                    db.commit()
                    _run_batch(pool, retry_batch)
        finally:
            if cancelled:
                pool.shutdown(wait=False, cancel_futures=True)
            else:
                pool.shutdown(wait=True)
            job_engine.dispose()

        # 流式构建：分片结果已即时并入图（_merge_unit_into_graph），无需最后
        # 统一聚合。融合自动归并收口一次 + 投影全量重建。
        auto_fuse_after_extraction(db, kb, method="llm")
        _project_to_neo4j(db, kb)

        # 融合归并可能合并掉部分实体：收尾按图重算，保证进度里的
        # 「实体 N · 关系 M」与画布标题栏（同一口径 graph_ids）逐项相等
        final_entity_ids, final_relation_ids = graph_ids(db, kb.id)
        db.refresh(job)
        job.entities_found = len(final_entity_ids)
        job.relations_found = len(final_relation_ids)
        if cancelled:
            job.status = "cancelled"
        elif job.status == "running":
            if not completed:
                # 看门狗/时间预算让分片没跑完：不能算「已完成」——实测 3/18 片
                # 提前结束后界面仍显示绿色完成标注，剩余分片无人续抽
                job.status = "failed"
                job.error = (
                    f"interrupted before finishing ({job.done_units}/{job.total_units} "
                    f"chunk attempts done): {job.error or 'unknown reason'}"
                )
            elif failed_chunk_ids and not ok_chunk_ids:
                # 一个分片都没抽出来：不能标「已完成」——否则界面显示绿色完成
                # 标签而实体为 0，用户无从判断出了什么问题
                first_error = next(iter(chunk_errors.values()), "")
                job.status = "failed"
                job.error = (
                    f"all {len(failed_chunk_ids)} chunk(s) failed to extract"
                    + (f": {first_error[:300]}" if first_error else "")
                    + "; re-run to retry"
                )
            else:
                job.status = "succeeded"
                if failed_chunk_ids:
                    job.error = (
                        f"{len(failed_chunk_ids)} chunk(s) failed; "
                        "re-run deep extraction to retry them"
                    )
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


def _merge_unit_into_graph(
    db, kb, ontology: dict[str, list[str]], unit_data: dict, *,
    chunk_id, entity_index: dict,
) -> tuple[list, list]:
    """单个分片结果并入图（流式成长 / 缓存回放共用），返回 (触及的实体 id, 关系 id)。

    不提交事务——由调用方与分片结果、任务计数一起单事务提交。

    - 实体链接：norm 名/别名命中 entity_index 时复用既有实体（freq+1、别名/
      属性并集，类型保持原样——复用到的只会是手工实体：快速抽取与深度抽取
      不并存，任务启动时上一轮抽取结果已整体清空），否则新建；
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
        llm_type = coerce_entity_type(str(ent.get("type", "")), ontology)
        eid = entity_index.get(name)
        if eid is None:
            eid = uuid.uuid4()
            entity_index[name] = eid
            db.add(GraphEntity(
                id=eid, kb_id=kb.id, name=name,
                entity_type=llm_type,
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

    relation_ids: list = []
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
            relation_ids.append(existing.id)
        else:
            relation = GraphRelation(
                id=uuid.uuid4(),
                kb_id=kb.id, source_id=s_id, target_id=t_id,
                relation_type=rtype,
                properties={
                    "source": "auto", "method": "llm",
                    "weight": 1, "evidence": evidence,
                },
            )
            db.add(relation)
            relation_ids.append(relation.id)
    return list(resolved.values()), relation_ids
