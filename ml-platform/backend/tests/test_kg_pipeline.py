# -*- coding: utf-8 -*-
"""Five-stage KG pipeline tests: ontology / LLM extraction / fusion / projection / API.

LLM 调用一律 monkeypatch（CI 无外网无 Key）；Neo4j 用 fake driver；投影的
PG 兜底查真实 sqlite 表。运行入口：backend/.venv pytest tests/test_kg_pipeline.py
"""
import json
import unittest
import uuid
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.database import Base, SessionLocal, engine
from app.main import app
from app.models.knowledge import (
    Chunk,
    Document,
    GraphEntity,
    GraphRelation,
    KgExtractionJob,
    KgMergeSuggestion,
)
from app.models.user import User
from tests.auth_test_support import ensure_admin
from app.services.security import rate_limiter

Base.metadata.create_all(bind=engine)
client = TestClient(app)
ensure_admin()


def login_headers():
    rate_limiter().clear()
    r = client.post("/api/auth/login", data={"username": "admin", "password": "admin123"})
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _admin_id():
    with SessionLocal() as db:
        user = db.query(User).filter(User.username == "admin").first()
        return user.id


def _seed_kb(name: str) -> str:
    with SessionLocal() as db:
        owner = db.query(User).filter(User.username == "admin").first()
        from app.models.knowledge import KnowledgeBase

        kb = KnowledgeBase(name=name, description="kg pipeline tests", owner_id=owner.id)
        db.add(kb)
        db.commit()
        return str(kb.id)


def _seed_doc(kb_id: str, filename: str, chunks: list[str]) -> str:
    with SessionLocal() as db:
        doc = Document(kb_id=uuid.UUID(kb_id), filename=filename, content="\n".join(chunks))
        db.add(doc)
        db.flush()
        for index, text in enumerate(chunks):
            db.add(Chunk(doc_id=doc.id, content=text, chunk_index=index))
        db.commit()
        return str(doc.id)


def _seed_entity(kb_id: str, name: str, entity_type: str = "概念",
                 aliases=None, attributes=None, freq: int = 1):
    with SessionLocal() as db:
        entity = GraphEntity(
            kb_id=uuid.UUID(kb_id), name=name, entity_type=entity_type,
            aliases=aliases or [],
            properties={"source": "auto", "method": "llm", "freq": freq,
                        "doc_ids": [], "attributes": attributes or []},
        )
        db.add(entity)
        db.commit()
        return str(entity.id)


def _seed_relation(kb_id: str, source_id: str, target_id: str,
                   relation_type: str = "相关", weight: int = 2):
    with SessionLocal() as db:
        rel = GraphRelation(
            kb_id=uuid.UUID(kb_id),
            source_id=uuid.UUID(source_id), target_id=uuid.UUID(target_id),
            relation_type=relation_type,
            properties={"source": "auto", "method": "llm", "weight": weight},
        )
        db.add(rel)
        db.commit()
        return str(rel.id)


_GOOD_UNIT = json.dumps({
    "entities": [
        {"name": "点焊", "type": "工艺", "aliases": ["spot welding"],
         "attributes": [{"name": "电流", "value": "8kA", "evidence": "点焊电流8kA"}]},
        {"name": "飞溅", "type": "缺陷", "aliases": [], "attributes": []},
    ],
    "relations": [
        {"source": "点焊", "target": "飞溅", "type": "导致缺陷",
         "evidence": "电流过大会引起飞溅"},
    ],
}, ensure_ascii=False)


class TestKgOntology(unittest.TestCase):
    def test_default_and_custom_and_fallback(self):
        from app.services.kg_ontology import (
            coerce_entity_type,
            normalize_ontology,
            resolve_ontology,
        )

        class FakeKb:
            kg_ontology = None

        resolved = resolve_ontology(FakeKb())
        self.assertIn("工艺", resolved["entity_types"])

        class CustomKb:
            kg_ontology = {"entity_types": ["零件"], "relation_types": ["装配"]}

        custom = resolve_ontology(CustomKb())
        self.assertEqual(custom["entity_types"], ["零件"])
        self.assertEqual(custom["relation_types"], ["装配"])

        self.assertEqual(coerce_entity_type("不存在", resolved), "概念")
        normalized = normalize_ontology({"entity_types": [" a ", "a", 3], "relation_types": ["b"]})
        self.assertEqual(normalized["entity_types"], ["a"])
        with self.assertRaises(ValueError):
            normalize_ontology({"entity_types": []})


class TestKgContractAndUnitExtraction(unittest.TestCase):
    def test_contract_parse_and_type_coercion(self):
        from app.services.kg_ontology import resolve_ontology
        from app.services.knowledge_graph_llm_extraction import KgUnitExtraction
        from app.services.agent.contracts import parse_llm_json

        unit = KgUnitExtraction.model_validate(parse_llm_json(_GOOD_UNIT))
        self.assertEqual(len(unit.entities), 2)
        self.assertEqual(unit.relations[0].type, "导致缺陷")
        ontology = resolve_ontology(type("K", (), {"kg_ontology": None})())
        self.assertEqual(len(ontology["entity_types"]), 10)

    def test_extract_unit_success_and_repair(self):
        from app.services import knowledge_graph_llm_extraction as module
        from app.services.agent.contracts import AgentContractError

        config = object()
        ontology = {"entity_types": ["工艺", "缺陷"], "relation_types": ["相关", "导致缺陷"]}

        with patch.object(module, "chat_completion_with_retry") as fake_llm:
            fake_llm.return_value = (_GOOD_UNIT, {}, None)
            unit, usage, error = module.extract_unit(None, config, "点焊电流8kA", ontology)
            self.assertIsNone(error)
            self.assertEqual(unit.entities[0].name, "点焊")
            self.assertEqual(fake_llm.call_count, 1)

        with patch.object(module, "chat_completion_with_retry") as fake_llm:
            fake_llm.side_effect = [
                ("不是JSON", {}, None),
                (_GOOD_UNIT, {}, None),
            ]
            unit, usage, error = module.extract_unit(None, config, "文本", ontology)
            self.assertIsNone(error)
            self.assertEqual(len(unit.entities), 2)
            self.assertEqual(fake_llm.call_count, 2)  # 首次 + 修复重喂

        with patch.object(module, "chat_completion_with_retry") as fake_llm:
            fake_llm.side_effect = [
                ("还是坏输出", {}, None),
                ("依然坏输出", {}, None),
            ]
            unit, usage, error = module.extract_unit(None, config, "文本", ontology)
            self.assertIsNone(unit)
            self.assertIn("raw_first", error)
            self.assertIn("raw_retry", error)


class TestKgExtractionJob(unittest.TestCase):
    def test_job_runs_llm_layer_and_resume_skips_done_chunks(self):
        kb_id = _seed_kb("kg-job-db")
        _seed_doc(kb_id, "a.txt", ["点焊电流8kA会引起飞溅。", "点焊属于电阻焊工艺。"])
        with SessionLocal() as db:
            job = KgExtractionJob(kb_id=uuid.UUID(kb_id), mode="llm", status="pending", params={})
            db.add(job)
            db.commit()
            job_id = str(job.id)

        from app.services import knowledge_graph_llm_extraction as module

        calls = {"n": 0}

        def fake_llm(db, *, config, messages, temperature, max_tokens,
                     purpose, attempts, interval_seconds, max_wall_seconds, **kwargs):
            calls["n"] += 1
            return _GOOD_UNIT, {}, None

        with patch.object(module, "chat_completion_with_retry", side_effect=fake_llm):
            module.run_kg_extraction_job(job_id)

        with SessionLocal() as db:
            job = db.get(KgExtractionJob, uuid.UUID(job_id))
            self.assertEqual(job.status, "succeeded")
            self.assertEqual(job.done_units, 2)
            self.assertGreaterEqual(job.entities_found, 2)
            entities = db.query(GraphEntity).filter(GraphEntity.kb_id == uuid.UUID(kb_id)).all()
            types = {e.name: (e.entity_type, (e.properties or {}).get("method")) for e in entities}
            self.assertIn("点焊", types)
            self.assertEqual(types["点焊"][1], "llm")
            relations = db.query(GraphRelation).filter(GraphRelation.kb_id == uuid.UUID(kb_id)).all()
            self.assertGreaterEqual(len(relations), 1)
            self.assertEqual(relations[0].relation_type, "导致缺陷")

        # 断点续抽：内容未变时重跑不再调 LLM，直接复用单元缓存聚合
        with SessionLocal() as db:
            job2 = KgExtractionJob(kb_id=uuid.UUID(kb_id), mode="llm", status="pending", params={})
            db.add(job2)
            db.commit()
            job2_id = str(job2.id)
        calls["n"] = 0
        with patch.object(module, "chat_completion_with_retry", side_effect=fake_llm):
            module.run_kg_extraction_job(job2_id)
        self.assertEqual(calls["n"], 0)  # 全部命中单元缓存
        with SessionLocal() as db:
            job2 = db.get(KgExtractionJob, uuid.UUID(job2_id))
            self.assertEqual(job2.status, "succeeded")
            self.assertEqual(job2.total_units, 0)

    def test_force_reextract_ignores_cache_and_rebuilds(self):
        kb_id = _seed_kb("kg-job-force")
        _seed_doc(kb_id, "a.txt", ["点焊电流8kA会引起飞溅。"])
        with SessionLocal() as db:
            job = KgExtractionJob(
                kb_id=uuid.UUID(kb_id), mode="llm", status="pending",
                params={"force": True},
            )
            db.add(job)
            db.commit()
            job_id = str(job.id)

        from app.services import knowledge_graph_llm_extraction as module

        calls = {"n": 0}

        def fake_llm(db, *, config, messages, temperature, max_tokens,
                     purpose, attempts, interval_seconds, max_wall_seconds, **kwargs):
            calls["n"] += 1
            return _GOOD_UNIT, {}, None

        with patch.object(module, "chat_completion_with_retry", side_effect=fake_llm):
            module.run_kg_extraction_job(job_id)

        # 首次抽取：1 次调用成功
        self.assertEqual(calls["n"], 1)
        # force 续跑：忽略缓存重做（调用次数再次增加），实体走链接复用不重复
        with patch.object(module, "chat_completion_with_retry", side_effect=fake_llm):
            with SessionLocal() as db:
                job2 = KgExtractionJob(
                    kb_id=uuid.UUID(kb_id), mode="llm", status="pending",
                    params={"force": True},
                )
                db.add(job2)
                db.commit()
                job2_id = str(job2.id)
        calls["n"] = 0
        with patch.object(module, "chat_completion_with_retry", side_effect=fake_llm):
            module.run_kg_extraction_job(job2_id)
        self.assertEqual(calls["n"], 1)  # force 忽略缓存重做
        with SessionLocal() as db:
            job2 = db.get(KgExtractionJob, uuid.UUID(job2_id))
            self.assertEqual(job2.status, "succeeded")
            # 同名实体走链接复用，不产生重复节点
            entities = db.query(GraphEntity).filter(
                GraphEntity.kb_id == uuid.UUID(kb_id),
                GraphEntity.merged_into.is_(None),
            ).all()
            names = [e.name for e in entities]
            self.assertEqual(len(names), len(set(names)))

    def test_deep_extraction_replaces_quick_results_and_counts_match_graph(self):
        # 快速抽取与深度抽取不并存、以最后一次为主：规则层已有的实体与关系在
        # 深度抽取时整体清掉，只留大模型抽出来的。进度里的「实体 N · 关系 M」
        # 是库内图谱规模（去重后的存活实体/关系数，不是各分片结果的累加），
        # 与画布 GET /graph 同源
        kb_id = _seed_kb("kg-job-replace")
        _seed_doc(kb_id, "a.txt", ["点焊电流8kA会引起飞溅。", "点焊电流过大会导致飞溅。"])
        with SessionLocal() as db:
            # 规则层已有「飞溅」（jieba 词性桶类型）、一个规则层独有实体及一条关系
            splash = GraphEntity(
                kb_id=uuid.UUID(kb_id), name="飞溅", entity_type="concept",
                properties={"source": "auto", "method": "rules", "freq": 5},
            )
            db.add(splash)
            db.flush()
            other = GraphEntity(
                kb_id=uuid.UUID(kb_id), name="规则层独有实体", entity_type="concept",
                properties={"source": "auto", "method": "rules", "freq": 3},
            )
            db.add(other)
            db.flush()
            db.add(GraphRelation(
                kb_id=uuid.UUID(kb_id), source_id=splash.id, target_id=other.id,
                relation_type="co_occurs_with",
                properties={"source": "auto", "method": "rules", "weight": 2},
            ))
            job = KgExtractionJob(kb_id=uuid.UUID(kb_id), mode="llm", status="pending", params={})
            db.add(job)
            db.commit()
            job_id = str(job.id)

        from app.services import knowledge_graph_llm_extraction as module

        with patch.object(module, "chat_completion_with_retry", return_value=(_GOOD_UNIT, {}, None)):
            module.run_kg_extraction_job(job_id)

        h = login_headers()
        with SessionLocal() as db:
            job = db.get(KgExtractionJob, uuid.UUID(job_id))
            self.assertEqual(job.status, "succeeded")
            # 2 片 × (2 实体/1 关系) 的相同结果 → 去重后仍是 2/1，不是 4/2
            self.assertEqual((job.entities_found, job.relations_found), (2, 1))
            live = {
                (e.name, e.entity_type, e.properties["method"])
                for e in db.query(GraphEntity).filter(
                    GraphEntity.kb_id == uuid.UUID(kb_id),
                    GraphEntity.merged_into.is_(None),
                ).all()
            }
            # 规则层结果被整体替换：「飞溅」是大模型新建的实体（领域类型），规则层独有实体不在了
            self.assertEqual(live, {("点焊", "工艺", "llm"), ("飞溅", "缺陷", "llm")})

        graph = client.get(f"/api/knowledge/bases/{kb_id}/graph", headers=h).json()
        self.assertEqual(sorted(n["name"] for n in graph["nodes"]), ["点焊", "飞溅"])
        self.assertEqual([e["relation_type"] for e in graph["edges"]], ["导致缺陷"])
        # 状态标注的数字与画布逐项相等
        status = client.get(
            f"/api/knowledge/bases/{kb_id}/graph/extract/jobs/{job_id}", headers=h,
        ).json()
        self.assertEqual(len(graph["nodes"]), status["entities_found"])
        self.assertEqual(len(graph["edges"]), status["relations_found"])
        summary = client.get(
            f"/api/knowledge/bases/{kb_id}/graph/extract/summary", headers=h,
        ).json()
        self.assertEqual(summary["current"], "llm")
        # 摘要里的图谱规模（状态标注用）与画布 GET /graph 同口径
        self.assertEqual(
            summary["graph"],
            {"entities": len(graph["nodes"]), "relations": len(graph["edges"])},
        )
        self.assertTrue(summary["llm"]["extracted"])
        self.assertFalse(summary["rules"]["extracted"])

    def test_job_with_every_chunk_failed_is_marked_failed(self):
        kb_id = _seed_kb("kg-job-all-failed")
        _seed_doc(kb_id, "a.txt", ["内容一句。", "内容两句。"])
        with SessionLocal() as db:
            job = KgExtractionJob(kb_id=uuid.UUID(kb_id), mode="llm", status="pending", params={})
            db.add(job)
            db.commit()
            job_id = str(job.id)

        from app.services import knowledge_graph_llm_extraction as module

        with patch.object(module, "chat_completion_with_retry") as fake_llm:
            fake_llm.return_value = (None, {}, "llm_call_failed: LLMStreamStalled")
            module.run_kg_extraction_job(job_id)

        with SessionLocal() as db:
            job = db.get(KgExtractionJob, uuid.UUID(job_id))
            # 一个分片都没抽出来不能标「已完成」（否则界面是绿色完成标签+实体 0）
            self.assertEqual(job.status, "failed")
            self.assertIn("failed to extract", job.error)
            # 重试片计入总数（不出 4/2）；失败片数按最终仍失败的分片计（不因重试翻倍）
            self.assertEqual((job.total_units, job.done_units), (4, 4))
            self.assertEqual(job.llm_errors, 2)
            self.assertEqual((job.entities_found, job.relations_found), (0, 0))

    def test_job_partial_failure_stays_succeeded_with_note(self):
        kb_id = _seed_kb("kg-job-partial")
        _seed_doc(kb_id, "a.txt", ["内容一句。", "内容两句。"])
        with SessionLocal() as db:
            job = KgExtractionJob(kb_id=uuid.UUID(kb_id), mode="llm", status="pending", params={})
            db.add(job)
            db.commit()
            job_id = str(job.id)

        from app.services import knowledge_graph_llm_extraction as module

        # 串行：片1 成功、片2 失败、片2 重试仍失败
        outcomes = [
            (_GOOD_UNIT, {}, None),
            (None, {}, "llm_call_failed: LLMStreamStalled"),
            (None, {}, "llm_call_failed: LLMStreamStalled"),
        ]
        with patch.object(module, "chat_completion_with_retry", side_effect=outcomes):
            module.run_kg_extraction_job(job_id)

        with SessionLocal() as db:
            job = db.get(KgExtractionJob, uuid.UUID(job_id))
            self.assertEqual(job.status, "succeeded")
            self.assertIn("1 chunk(s) failed", job.error)
            self.assertEqual((job.total_units, job.done_units), (3, 3))
            self.assertEqual(job.llm_errors, 1)
            self.assertEqual(job.entities_found, 2)


    def test_job_interrupted_early_is_marked_failed(self):
        # 看门狗/时间预算让分片没跑完：不能标「已完成」（实测 3/18 片提前结束
        # 后界面仍显示绿色完成标注，剩余分片无人续抽）
        kb_id = _seed_kb("kg-job-interrupted")
        _seed_doc(kb_id, "a.txt", ["内容一句。", "内容两句。"])
        with SessionLocal() as db:
            job = KgExtractionJob(kb_id=uuid.UUID(kb_id), mode="llm", status="pending", params={})
            db.add(job)
            db.commit()
            job_id = str(job.id)

        from app.services import knowledge_graph_llm_extraction as module

        def stalled_wait(futures, timeout=None, return_when=None):
            # 模拟看门狗窗口内没有任何分片落地（确定性，不依赖时钟精度）
            return set(), set(futures)

        with patch.object(module, "wait", side_effect=stalled_wait), \
             patch.object(module, "chat_completion_with_retry", return_value=(_GOOD_UNIT, {}, None)):
            module.run_kg_extraction_job(job_id)

        with SessionLocal() as db:
            job = db.get(KgExtractionJob, uuid.UUID(job_id))
            self.assertEqual(job.status, "failed")
            self.assertIn("interrupted before finishing", job.error)
            self.assertIn("LLM calls stalled", job.error)
            self.assertEqual(job.done_units, 0)

    def test_interrupted_reextraction_keeps_remaining_chunks_resumable(self):
        # 重新抽取（force）清空图层时必须一并作废分片缓存：否则重抽中断后界面
        # 显示待抽 0 片、不给「继续抽取」入口，图层却只剩一部分（2026-11-24
        # 实测：图里 3/18 片，缓存仍是 18 片全部完成）
        kb_id = _seed_kb("kg-job-force-resume")
        _seed_doc(kb_id, "a.txt", ["点焊电流8kA会引起飞溅。", "电极采用铬锆铜材料制造。"])
        with SessionLocal() as db:
            job = KgExtractionJob(
                kb_id=uuid.UUID(kb_id), mode="llm", status="pending", params={"force": True},
            )
            db.add(job)
            db.commit()
            job_id = str(job.id)

        from concurrent.futures import FIRST_COMPLETED, wait as real_wait

        from app.services import knowledge_graph_llm_extraction as module

        electrode_unit = json.dumps({
            "entities": [
                {"name": "电极", "type": "部件", "aliases": [], "attributes": []},
                {"name": "铬锆铜", "type": "材料", "aliases": [], "attributes": []},
            ],
            "relations": [
                {"source": "电极", "target": "铬锆铜", "type": "相关", "evidence": "电极采用铬锆铜"},
            ],
        }, ensure_ascii=False)

        def fake_llm(db, *, config, messages, **kwargs):
            text = json.dumps(messages, ensure_ascii=False)
            return (electrode_unit if "铬锆铜" in text else _GOOD_UNIT), {}, None

        waits = {"n": 0}

        def one_then_stall(futures, timeout=None, return_when=None):
            # 第一次等待只放行一片（假 LLM 瞬间返回，两片可能都已完成）；第二次
            # 等待窗口内无任何分片完成（看门狗触发）
            done, pending = real_wait(futures, timeout=timeout, return_when=FIRST_COMPLETED)
            waits["n"] += 1
            if waits["n"] > 1:
                return set(), set(futures)
            released = set(sorted(done, key=id)[:1])
            return released, set(pending) | (set(done) - released)

        with patch.object(module, "chat_completion_with_retry", side_effect=fake_llm), \
             patch.object(module, "wait", side_effect=one_then_stall):
            module.run_kg_extraction_job(job_id)

        h = login_headers()
        url = f"/api/knowledge/bases/{kb_id}/graph/extract/summary"
        with SessionLocal() as db:
            job = db.get(KgExtractionJob, uuid.UUID(job_id))
            self.assertEqual(job.status, "failed")
            self.assertEqual((job.done_units, job.total_units), (1, 2))
        interrupted = client.get(url, headers=h).json()
        # 图里只有 1 片的结果 → 另 1 片必须算作待抽（重新抽取开始时缓存已作废）
        self.assertEqual(interrupted["llm"]["pending_chunks"], 1)
        self.assertEqual(interrupted["llm"]["latest_job"]["entities_found"], 2)

        # 续抽：只做剩下的 1 片
        with SessionLocal() as db:
            resume = KgExtractionJob(
                kb_id=uuid.UUID(kb_id), mode="llm", status="pending", params={},
            )
            db.add(resume)
            db.commit()
            resume_id = str(resume.id)
        calls = {"n": 0}

        def counting_llm(*args, **kwargs):
            calls["n"] += 1
            return fake_llm(*args, **kwargs)

        with patch.object(module, "chat_completion_with_retry", side_effect=counting_llm):
            module.run_kg_extraction_job(resume_id)
        self.assertEqual(calls["n"], 1)

        # 续建在原结果之上：两片的产出都在，补抽后图谱不减回去；
        # 状态标注的数字与画布逐项相等
        graph = client.get(f"/api/knowledge/bases/{kb_id}/graph", headers=h).json()
        self.assertEqual(
            sorted(n["name"] for n in graph["nodes"]), ["点焊", "电极", "铬锆铜", "飞溅"],
        )
        self.assertEqual(len(graph["edges"]), 2)
        resumed = client.get(url, headers=h).json()
        self.assertEqual(resumed["llm"]["pending_chunks"], 0)
        self.assertEqual(resumed["llm"]["latest_job"]["status"], "succeeded")
        self.assertEqual(resumed["llm"]["latest_job"]["entities_found"], len(graph["nodes"]))
        self.assertEqual(resumed["llm"]["latest_job"]["relations_found"], len(graph["edges"]))

    def test_force_reextraction_clears_what_is_not_extracted_again(self):
        # 全部重新抽取从零重建：这一轮没再抽到的实体与关系不残留
        kb_id = _seed_kb("kg-job-force-layer")
        _seed_doc(kb_id, "a.txt", ["点焊电流8kA会引起飞溅。"])
        with SessionLocal() as db:
            first = KgExtractionJob(
                kb_id=uuid.UUID(kb_id), mode="llm", status="pending", params={},
            )
            db.add(first)
            db.commit()
            first_id = str(first.id)

        from app.services import knowledge_graph_llm_extraction as module

        with patch.object(module, "chat_completion_with_retry", return_value=(_GOOD_UNIT, {}, None)):
            module.run_kg_extraction_job(first_id)
        h = login_headers()
        graph = client.get(f"/api/knowledge/bases/{kb_id}/graph", headers=h).json()
        self.assertEqual(sorted(n["name"] for n in graph["nodes"]), ["点焊", "飞溅"])

        # 全部重新抽取：这一轮大模型只抽到「点焊」
        only_weld = json.dumps({
            "entities": [{"name": "点焊", "type": "工艺", "aliases": [], "attributes": []}],
            "relations": [],
        }, ensure_ascii=False)
        with SessionLocal() as db:
            second = KgExtractionJob(
                kb_id=uuid.UUID(kb_id), mode="llm", status="pending", params={"force": True},
            )
            db.add(second)
            db.commit()
            second_id = str(second.id)
        with patch.object(module, "chat_completion_with_retry", return_value=(only_weld, {}, None)):
            module.run_kg_extraction_job(second_id)

        with SessionLocal() as db:
            second = db.get(KgExtractionJob, uuid.UUID(second_id))
            self.assertEqual(second.status, "succeeded")
            self.assertEqual((second.entities_found, second.relations_found), (1, 0))
        graph = client.get(f"/api/knowledge/bases/{kb_id}/graph", headers=h).json()
        self.assertEqual([n["name"] for n in graph["nodes"]], ["点焊"])
        self.assertEqual(graph["edges"], [])

    def test_quick_extraction_replaces_deep_results_and_deep_restores_from_cache(self):
        # 以最后一次抽取为主：快速抽取清掉大模型抽取结果，但保留分片缓存；
        # 之后改用深度抽取，抽过的分片按缓存重建，不再调用大模型
        kb_id = _seed_kb("kg-job-switch")
        _seed_doc(kb_id, "a.txt", ["点焊电流8kA会引起飞溅。", "电极采用铬锆铜材料制造。"])
        with SessionLocal() as db:
            first = KgExtractionJob(
                kb_id=uuid.UUID(kb_id), mode="llm", status="pending", params={},
            )
            db.add(first)
            db.commit()
            first_id = str(first.id)

        from app.services import knowledge_graph_llm_extraction as module

        electrode_unit = json.dumps({
            "entities": [
                {"name": "电极", "type": "部件", "aliases": [], "attributes": []},
                {"name": "铬锆铜", "type": "材料", "aliases": [], "attributes": []},
            ],
            "relations": [
                {"source": "电极", "target": "铬锆铜", "type": "相关", "evidence": "电极采用铬锆铜"},
            ],
        }, ensure_ascii=False)

        def fake_llm(db, *, config, messages, **kwargs):
            text = json.dumps(messages, ensure_ascii=False)
            return (electrode_unit if "铬锆铜" in text else _GOOD_UNIT), {}, None

        with patch.object(module, "chat_completion_with_retry", side_effect=fake_llm):
            module.run_kg_extraction_job(first_id)

        h = login_headers()
        url = f"/api/knowledge/bases/{kb_id}/graph/extract/summary"
        graph_url = f"/api/knowledge/bases/{kb_id}/graph"
        self.assertEqual(sorted(
            n["name"] for n in client.get(graph_url, headers=h).json()["nodes"]
        ), ["点焊", "电极", "铬锆铜", "飞溅"])

        # 改用快速抽取：大模型抽取的实体与关系整体清掉
        r = client.post(
            f"/api/knowledge/bases/{kb_id}/graph/extract", json={"mode": "rules"}, headers=h,
        )
        self.assertEqual(r.status_code, 200)
        summary = client.get(url, headers=h).json()
        self.assertNotEqual(summary["current"], "llm")
        self.assertFalse(summary["llm"]["extracted"])
        self.assertNotIn(
            "llm",
            {
                (n["properties"] or {}).get("method")
                for n in client.get(graph_url, headers=h).json()["nodes"]
            },
        )
        # 分片缓存保留：2 片都抽过 → 没有待抽分片
        self.assertEqual(summary["llm"]["cached_chunks"], 2)
        self.assertEqual(summary["llm"]["pending_chunks"], 0)

        # 切回深度抽取：抽过的分片按缓存重建，不调用大模型
        with SessionLocal() as db:
            second = KgExtractionJob(
                kb_id=uuid.UUID(kb_id), mode="llm", status="pending", params={},
            )
            db.add(second)
            db.commit()
            second_id = str(second.id)
        with patch.object(module, "chat_completion_with_retry") as fake_llm_now:
            module.run_kg_extraction_job(second_id)
        self.assertEqual(fake_llm_now.call_count, 0)
        with SessionLocal() as db:
            second = db.get(KgExtractionJob, uuid.UUID(second_id))
            self.assertEqual(second.status, "succeeded")
            # 回放的 2 片计入进度：一开始就是 2/2
            self.assertEqual((second.done_units, second.total_units), (2, 2))
        graph = client.get(graph_url, headers=h).json()
        self.assertEqual(
            sorted(n["name"] for n in graph["nodes"]), ["点焊", "电极", "铬锆铜", "飞溅"],
        )
        self.assertEqual(len(graph["edges"]), 2)
        summary = client.get(url, headers=h).json()
        self.assertEqual(summary["current"], "llm")
        self.assertTrue(summary["llm"]["extracted"])

    def test_quick_extraction_is_refused_while_a_deep_job_runs(self):
        # 快速抽取与深度抽取不并存：任务进行中若放行快速抽取，任务后续分片会
        # 继续往刚重建的结果里写，两种结果重新混杂
        kb_id = _seed_kb("kg-job-guard")
        _seed_doc(kb_id, "a.txt", ["点焊电流8kA会引起飞溅。"])
        with SessionLocal() as db:
            running = KgExtractionJob(
                kb_id=uuid.UUID(kb_id), mode="llm", status="running", params={}, total_units=1,
            )
            db.add(running)
            db.commit()
            running_id = running.id

        r = client.post(
            f"/api/knowledge/bases/{kb_id}/graph/extract",
            json={"mode": "rules"}, headers=login_headers(),
        )
        self.assertEqual(r.status_code, 409)
        with SessionLocal() as db:
            self.assertEqual(db.get(KgExtractionJob, running_id).status, "running")

    def test_summary_reports_mixed_legacy_layer_and_next_extraction_rebuilds(self):
        # 两层并存时期留下的存量库：摘要如实报告混杂；下一次深度抽取整体重建
        kb_id = _seed_kb("kg-job-mixed")
        _seed_doc(kb_id, "a.txt", ["点焊电流8kA会引起飞溅。"])
        with SessionLocal() as db:
            db.add_all([
                GraphEntity(
                    kb_id=uuid.UUID(kb_id), name="规则层实体", entity_type="concept",
                    properties={"source": "auto", "method": "rules", "freq": 5},
                ),
                GraphEntity(
                    kb_id=uuid.UUID(kb_id), name="旧的大模型实体", entity_type="工艺",
                    properties={"source": "auto", "method": "llm", "freq": 1},
                ),
            ])
            job = KgExtractionJob(kb_id=uuid.UUID(kb_id), mode="llm", status="pending", params={})
            db.add(job)
            db.commit()
            job_id = str(job.id)

        from app.services import knowledge_graph_llm_extraction as module

        h = login_headers()
        url = f"/api/knowledge/bases/{kb_id}/graph/extract/summary"
        before = client.get(url, headers=h).json()
        self.assertEqual(before["current"], "mixed")
        self.assertFalse(before["rules"]["extracted"])
        self.assertFalse(before["llm"]["extracted"])

        with patch.object(module, "chat_completion_with_retry", return_value=(_GOOD_UNIT, {}, None)):
            module.run_kg_extraction_job(job_id)
        names = sorted(
            n["name"] for n in client.get(f"/api/knowledge/bases/{kb_id}/graph", headers=h).json()["nodes"]
        )
        self.assertEqual(names, ["点焊", "飞溅"])
        self.assertEqual(client.get(url, headers=h).json()["current"], "llm")

    def test_extract_summary_reflects_history(self):
        kb_id = _seed_kb("kg-summary")
        _seed_doc(kb_id, "a.txt", ["点焊电流8kA会引起飞溅。", "点焊电流过大会导致飞溅。"])
        h = login_headers()
        url = f"/api/knowledge/bases/{kb_id}/graph/extract/summary"

        # 未抽取：当前图谱没有抽取结果，2 个分片待抽
        before = client.get(url, headers=h).json()
        self.assertEqual(before["chunks"], 2)
        self.assertIsNone(before["current"])
        self.assertEqual(before["rules"], {"extracted": False, "entities": 0})
        self.assertEqual(before["llm"]["extracted"], False)
        self.assertIsNone(before["llm"]["latest_job"])
        self.assertEqual(before["llm"]["pending_chunks"], 2)
        self.assertEqual(before["llm"]["cached_chunks"], 0)

        with SessionLocal() as db:
            job = KgExtractionJob(kb_id=uuid.UUID(kb_id), mode="llm", status="pending", params={})
            db.add(job)
            db.commit()
            job_id = str(job.id)

        from app.services import knowledge_graph_llm_extraction as module

        with patch.object(module, "chat_completion_with_retry", return_value=(_GOOD_UNIT, {}, None)):
            module.run_kg_extraction_job(job_id)

        after = client.get(url, headers=h).json()
        # 当前图谱由深度抽取生成
        self.assertEqual(after["current"], "llm")
        self.assertTrue(after["llm"]["extracted"])
        self.assertEqual(after["llm"]["latest_job"]["id"], job_id)
        self.assertEqual(after["llm"]["latest_job"]["status"], "succeeded")
        # 全部分片已成功 → 无待抽、2 片有缓存；无进行中任务
        self.assertEqual(after["llm"]["pending_chunks"], 0)
        self.assertEqual(after["llm"]["cached_chunks"], 2)
        self.assertIsNone(after["llm"]["active_job"])
        self.assertEqual(after["rules"], {"extracted": False, "entities": 0})

        # 任务进行中（30 分钟内创建）→ active_job 可见，刷新页面后能接续轮询
        with SessionLocal() as db:
            running = KgExtractionJob(
                kb_id=uuid.UUID(kb_id), mode="llm", status="running", params={},
                total_units=2, done_units=1,
            )
            db.add(running)
            db.commit()
            running_id = str(running.id)
        during = client.get(url, headers=h).json()
        self.assertEqual(during["llm"]["active_job"]["id"], running_id)
        self.assertEqual(during["llm"]["latest_job"]["id"], running_id)


class TestWebSearchOverride(unittest.TestCase):
    def test_default_follows_profile_and_explicit_flag_wins(self):
        from app.services.llm_gateway import GatewayLLMConfig, _build_llm_request

        def config(provider: str, capabilities: list[str]):
            return GatewayLLMConfig(
                api_url="https://example.invalid/v1/messages", api_key="k",
                model_id="m", temperature=0.1, timeout_seconds=30,
                profile_id=None, profile_name="p", provider=provider,
                model_config={"capabilities": capabilities},
            )

        messages = [{"role": "user", "content": "hi"}]

        def body_for(cfg, **kwargs):
            return _build_llm_request(cfg, messages, 0.1, 100, **kwargs)[2]

        # 调用方不传（None）：按档案能力决定（既有行为不变）
        self.assertIn("tools", body_for(config("anthropic", ["web_search"])))
        self.assertNotIn("tools", body_for(config("anthropic", [])))
        # 显式关闭优先于档案能力（KG 深度抽取等结构化批任务）
        self.assertNotIn(
            "tools", body_for(config("anthropic", ["web_search"]), web_search=False),
        )
        # 显式开启优先于档案未勾选
        self.assertIn("tools", body_for(config("anthropic", []), web_search=True))


class TestKgFusion(unittest.TestCase):
    def test_exact_name_auto_merge_repoints_relations(self):
        # 同库存活同名已被部分唯一索引禁止（迁移已治理历史脏数据）；自动归并
        # 的可触发形态=实体名命中另一实体的别名（归一化等价）。
        kb_id = _seed_kb("kg-fusion-exact")
        a = _seed_entity(kb_id, "点焊", "工艺", aliases=["spot welding"], freq=3)
        b = _seed_entity(kb_id, "SPOT WELDING", "工艺", freq=1)  # 归一化命中 a 的别名
        rel = _seed_relation(kb_id, b, a, "相关")

        with SessionLocal() as db:
            from app.models.knowledge import KnowledgeBase

            kb = db.get(KnowledgeBase, uuid.UUID(kb_id))
            from app.services.kg_fusion import auto_fuse_after_extraction

            report = auto_fuse_after_extraction(db, kb, method="llm")
            self.assertGreaterEqual(report["auto_merged"], 1)
            loser = db.get(GraphEntity, uuid.UUID(b))
            self.assertIsNotNone(loser.merged_into)
            winner = db.get(GraphEntity, uuid.UUID(a))
            # loser 原名并入 winner 别名（原 alias 也在）
            self.assertIn("SPOT WELDING", winner.aliases or [])
            self.assertIn("spot welding", winner.aliases or [])
            # 关系重指：原 b→a 的边应改为 a→a（自环被后续去重保留为存活）
            r = db.get(GraphRelation, uuid.UUID(rel))
            self.assertIsNotNone(r)
            self.assertEqual(str(r.source_id), a)

    def test_auto_merge_skips_pair_already_merged_in_this_pass(self):
        # 互为别名的一对：先处理的一方并入另一方后，轮到存活者时索引（本轮开始
        # 时的快照）仍指向「已并入自己」的对方——应识别为已合并并跳过。此前走
        # 进防环分支抛 ValueError，整个抽取任务被判失败：缓存回放建的图所有
        # 实体同一秒创建（created_at 相等、不换位），稳定触发（2026-11-24 实测）
        kb_id = _seed_kb("kg-fusion-mutual")
        with SessionLocal() as db:
            loser = GraphEntity(
                kb_id=uuid.UUID(kb_id), name="电阻焊", entity_type="工艺", aliases=["点焊"],
                properties={"source": "auto", "method": "llm", "freq": 1},
            )
            winner = GraphEntity(
                kb_id=uuid.UUID(kb_id), name="点焊", entity_type="工艺", aliases=["电阻焊"],
                properties={"source": "auto", "method": "llm", "freq": 1},
            )
            db.add(loser)  # 列表序在前：先处理它 → 它成为被并入方
            db.add(winner)
            db.commit()
            winner_id, loser_id = winner.id, loser.id

            from app.models.knowledge import KnowledgeBase

            from app.services.kg_fusion import auto_fuse_after_extraction

            report = auto_fuse_after_extraction(db, db.get(KnowledgeBase, uuid.UUID(kb_id)), method="llm")
            self.assertEqual(report["auto_merged"], 1)
            self.assertEqual(db.get(GraphEntity, loser_id).merged_into, winner_id)
            self.assertIn("电阻焊", db.get(GraphEntity, winner_id).aliases or [])

    def test_alias_and_conflict_and_fuzzy(self):
        kb_id = _seed_kb("kg-fusion-mixed")
        _seed_entity(kb_id, "点焊", "工艺", aliases=["电阻点焊"], freq=2)
        _seed_entity(kb_id, "电阻点焊", "工艺", freq=1)  # 命中别名 → 自动归并
        _seed_entity(kb_id, "电流", "指标", attributes=[
            {"name": "典型值", "value": "8kA", "doc_id": "doc1"},
            {"name": "典型值", "value": "10kA", "doc_id": "doc2"},
        ])
        # 高相似对（无 LLM 仲裁 → 默认进人工队列）
        _seed_entity(kb_id, "点焊质量", "概念", freq=1)
        _seed_entity(kb_id, "点焊质显", "概念", freq=1)

        with SessionLocal() as db:
            from app.models.knowledge import KnowledgeBase

            kb = db.get(KnowledgeBase, uuid.UUID(kb_id))
            from unittest.mock import patch as _patch

            from app.services import kg_fusion as fusion_module
            from app.services.kg_fusion import auto_fuse_after_extraction

            # 测试聚焦流程而非阈值：放宽相似度门槛（LLM 仲裁不可用→默认进队列）
            with _patch.object(fusion_module, "_fuzzy_threshold", lambda: 0.6):
                report = auto_fuse_after_extraction(db, kb, method="llm")
            self.assertGreaterEqual(report["auto_merged"], 1)
            self.assertGreaterEqual(report["conflicts"], 1)
            self.assertGreaterEqual(report["fuzzy_pending"], 1)

            pendings = db.query(KgMergeSuggestion).filter(
                KgMergeSuggestion.kb_id == uuid.UUID(kb_id),
                KgMergeSuggestion.status == "pending",
            ).all()
            types = {s.type for s in pendings}
            self.assertIn("attribute_conflict", types)
            self.assertIn("merge_entity", types)

            # 冲突裁决：采纳 10kA（与 API 行为一致：resolved 先写入 payload）
            conflict = next(s for s in pendings if s.type == "attribute_conflict")
            from app.services.kg_fusion import accept_suggestion

            payload = dict(conflict.payload or {})
            payload["resolved"] = {"value": "10kA"}
            conflict.payload = payload
            result = accept_suggestion(db, kb, conflict)
            self.assertEqual(result["status"], "accepted")
            entity = db.get(GraphEntity, conflict.entity_a_id)
            attr_values = [a["value"] for a in (entity.properties or {}).get("attributes", [])
                           if a["name"] == "典型值"]
            self.assertEqual(attr_values, ["10kA"])

    def test_accept_merge_suggestion(self):
        kb_id = _seed_kb("kg-fusion-accept")
        winner_id = _seed_entity(kb_id, "点焊", "工艺")
        loser_id = _seed_entity(kb_id, "spot welding", "工艺")
        _seed_relation(kb_id, loser_id, winner_id, "相关")

        with SessionLocal() as db:
            from app.models.knowledge import KnowledgeBase

            kb = db.get(KnowledgeBase, uuid.UUID(kb_id))
            suggestion = KgMergeSuggestion(
                kb_id=kb.id, type="merge_entity", status="pending",
                method="llm", entity_a_id=uuid.UUID(winner_id),
                entity_b_id=uuid.UUID(loser_id),
                payload={"reason": "LLM 仲裁"},
            )
            db.add(suggestion)
            db.commit()
            sid = str(suggestion.id)

            from app.services.kg_fusion import accept_suggestion

            result = accept_suggestion(db, kb, suggestion)
            self.assertEqual(result["status"], "accepted")
            loser = db.get(GraphEntity, uuid.UUID(loser_id))
            self.assertIsNotNone(loser.merged_into)
            winner = db.get(GraphEntity, uuid.UUID(winner_id))
            self.assertIn("spot welding", winner.aliases or [])


class TestKgProjection(unittest.TestCase):
    def test_resync_with_fake_driver(self):
        kb_id = _seed_kb("kg-projection")
        a = _seed_entity(kb_id, "点焊", "工艺")
        b = _seed_entity(kb_id, "飞溅", "缺陷")
        _seed_relation(kb_id, a, b, "导致缺陷")

        class FakeSession:
            def __init__(self, driver):
                self.driver = driver

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def run(self, query, **params):
                self.driver.queries.append((query, params))
                return []

        class FakeDriver:
            def __init__(self):
                self.queries = []

            def session(self, database=None):
                return FakeSession(self)

        from app.services.kg_projection import KgProjection

        driver = FakeDriver()
        projection = KgProjection(driver_factory=lambda: driver)
        with SessionLocal() as db:
            counts = projection.resync_kb(db, uuid.UUID(kb_id))
        self.assertEqual(counts["entities"], 2)
        self.assertEqual(counts["relations"], 1)
        merged_queries = [q for q, _ in driver.queries if "MERGE" in q]
        self.assertGreaterEqual(len(merged_queries), 2)  # 实体批 + 关系批

    def test_schema_is_created_on_first_connection(self):
        # 投影按 (kbId, id) 定位节点：没有索引时每条关系的两次 MATCH 都是全标签
        # 扫描（399 实体 / 6,230 关系的库重建要 30 秒）。首连时幂等建约束与索引
        class Result:
            def __init__(self, log, query):
                self.log, self.query = log, query

            def consume(self):
                self.log.append(("consume", self.query))

        class Session:
            def __init__(self, log):
                self.log = log

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def run(self, query, **params):
                self.log.append(("run", query))
                return Result(self.log, query)

        class Driver:
            def __init__(self, log):
                self.log = log

            def session(self, database=None):
                return Session(self.log)

        from app.services.kg_projection import KgProjection

        log = []
        projection = KgProjection()
        projection._driver = Driver(log)
        projection._ensure_schema()

        statements = [query for kind, query in log if kind == "consume"]
        self.assertEqual(len(statements), 2)  # 两条语句都被执行到底（consume）
        self.assertIn("CREATE CONSTRAINT kg_entity_id IF NOT EXISTS", statements[0])
        self.assertIn("FOR (e:KGEntity) REQUIRE e.id IS UNIQUE", statements[0])
        self.assertIn("CREATE INDEX kg_entity_kb IF NOT EXISTS", statements[1])
        self.assertIn("FOR (e:KGEntity) ON (e.kbId)", statements[1])

    def test_pg_fallback_neighbors_and_path(self):
        kb_id = _seed_kb("kg-pg-fallback")
        a = _seed_entity(kb_id, "点焊", "工艺")
        b = _seed_entity(kb_id, "飞溅", "缺陷")
        c = _seed_entity(kb_id, "电流", "指标")
        _seed_relation(kb_id, a, b, "导致缺陷")
        _seed_relation(kb_id, c, b, "相关")

        from app.services.kg_projection import (
            neighbors_pg,
            related_topk_pg,
            shortest_path_pg,
        )

        with SessionLocal() as db:
            one_hop = neighbors_pg(db, uuid.UUID(kb_id), uuid.UUID(a), hops=1)
            names = {e["name"] for e in one_hop["entities"]}
            self.assertIn("飞溅", names)
            path = shortest_path_pg(db, uuid.UUID(kb_id), uuid.UUID(a), uuid.UUID(c))
            self.assertGreaterEqual(len(path["nodes"]), 3)  # a→b→c
            related = related_topk_pg(db, uuid.UUID(kb_id), uuid.UUID(a), k=5)
            self.assertTrue(related[0]["name"], "飞溅")


class TestKgApi(unittest.TestCase):
    def test_01_ontology_endpoints(self):
        h = login_headers()
        kb_id = _seed_kb("kg-api-ontology")
        r = client.get(f"/api/knowledge/bases/{kb_id}/graph/ontology", headers=h)
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()["ontology"]["entity_types"])
        r = client.put(
            f"/api/knowledge/bases/{kb_id}/graph/ontology",
            json={"entity_types": ["工艺"], "relation_types": ["导致"]},
            headers=h,
        )
        self.assertEqual(r.status_code, 200)
        r = client.get(f"/api/knowledge/bases/{kb_id}/graph/ontology", headers=h)
        self.assertEqual(r.json()["ontology"]["entity_types"], ["工艺"])
        self.assertTrue(r.json()["custom"])

    def test_02_extract_llm_mode_dispatches_and_status(self):
        h = login_headers()
        kb_id = _seed_kb("kg-api-extract")
        _seed_doc(kb_id, "a.txt", ["点焊电流8kA。"])

        from app.services import knowledge_graph_llm_extraction as module

        with patch.object(module, "chat_completion_with_retry") as fake_llm, \
             patch("app.tasks.kg_tasks.dispatch_kg_extraction") as fake_dispatch:
            fake_llm.return_value = (_GOOD_UNIT, {}, None)
            fake_dispatch.side_effect = (
                lambda job_id: module.run_kg_extraction_job(job_id)
            )
            r = client.post(
                f"/api/knowledge/bases/{kb_id}/graph/extract",
                json={"mode": "llm"},
                headers=h,
            )
            self.assertEqual(r.status_code, 200)
            self.assertEqual(r.json()["mode"], "llm")
            job_id = r.json()["job_id"]
            self.assertTrue(fake_dispatch.called)

        r = client.get(
            f"/api/knowledge/bases/{kb_id}/graph/extract/jobs/{job_id}", headers=h,
        )
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["status"], "succeeded")
        self.assertGreaterEqual(r.json()["entities_found"], 2)

    def test_03_rules_mode_still_sync(self):
        h = login_headers()
        kb_id = _seed_kb("kg-api-rules")
        _seed_doc(kb_id, "a.txt", ["点焊是一种电阻焊工艺。点焊包含电极与电极头。"])
        r = client.post(
            f"/api/knowledge/bases/{kb_id}/graph/extract",
            json={"mode": "rules"},
            headers=h,
        )
        self.assertEqual(r.status_code, 200)
        self.assertIn("entities_created", r.json())

    def test_04_create_entity_links_same_name(self):
        h = login_headers()
        kb_id = _seed_kb("kg-api-link")
        existing = _seed_entity(kb_id, "点焊", "工艺")
        existing_en = _seed_entity(kb_id, "spot weld", "工艺")
        r = client.post(
            f"/api/knowledge/bases/{kb_id}/graph/entities",
            json={"name": "点焊", "entity_type": "工艺"},
            headers=h,
        )
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json().get("linked"))
        self.assertEqual(r.json()["id"], existing)
        # 归一化等价（英文大小写）也链接
        r = client.post(
            f"/api/knowledge/bases/{kb_id}/graph/entities",
            json={"name": "SPOT WELD", "entity_type": "工艺"},
            headers=h,
        )
        self.assertTrue(r.json().get("linked"))
        self.assertEqual(r.json()["id"], existing_en)

    def test_05_fusion_endpoints_list_and_reject(self):
        h = login_headers()
        kb_id = _seed_kb("kg-api-fusion")
        a = _seed_entity(kb_id, "点焊", "工艺")
        b = _seed_entity(kb_id, "spot welding", "工艺")
        with SessionLocal() as db:
            suggestion = KgMergeSuggestion(
                kb_id=uuid.UUID(kb_id), type="merge_entity", status="pending",
                method="llm", entity_a_id=uuid.UUID(a), entity_b_id=uuid.UUID(b),
                payload={"reason": "test"},
            )
            db.add(suggestion)
            db.commit()
            sid = str(suggestion.id)

        r = client.get(
            f"/api/knowledge/bases/{kb_id}/graph/fusion/suggestions?status=pending",
            headers=h,
        )
        self.assertEqual(r.status_code, 200)
        items = r.json()
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["entity_a"]["name"], "点焊")

        r = client.post(
            f"/api/knowledge/bases/{kb_id}/graph/fusion/suggestions/{sid}/reject",
            headers=h,
        )
        self.assertEqual(r.status_code, 200)
        with SessionLocal() as db:
            row = db.get(KgMergeSuggestion, uuid.UUID(sid))
            self.assertEqual(row.status, "rejected")

    def test_06_entity_detail_and_graph_queries(self):
        h = login_headers()
        kb_id = _seed_kb("kg-api-queries")
        a = _seed_entity(kb_id, "点焊", "工艺", aliases=["spot welding"])
        b = _seed_entity(kb_id, "飞溅", "缺陷")
        _seed_relation(kb_id, a, b, "导致缺陷", weight=5)

        r = client.get(f"/api/knowledge/bases/{kb_id}/graph/entities/{a}", headers=h)
        self.assertEqual(r.status_code, 200)
        detail = r.json()
        self.assertEqual(detail["method"], "llm")
        self.assertIn("spot welding", detail["aliases"])
        self.assertTrue(detail["related"])

        r = client.get(
            f"/api/knowledge/bases/{kb_id}/graph/query/path",
            params={"from_id": a, "to_id": b},
            headers=h,
        )
        self.assertEqual(r.status_code, 200)
        self.assertGreaterEqual(len(r.json()["nodes"]), 2)

        r = client.get(
            f"/api/knowledge/bases/{kb_id}/graph/query/neighbors/{b}",
            headers=h,
        )
        self.assertEqual(r.status_code, 200)
        self.assertTrue(any(e["name"] == "点焊" for e in r.json()["entities"]))

        r = client.get(f"/api/knowledge/bases/{kb_id}/graph/neo4j/status", headers=h)
        self.assertEqual(r.status_code, 200)
        self.assertFalse(r.json()["available"])  # 测试环境无 NEO4J_URI

    def test_07_full_graph_hides_merged(self):
        h = login_headers()
        kb_id = _seed_kb("kg-api-fullgraph")
        a = _seed_entity(kb_id, "点焊", "工艺")
        b = _seed_entity(kb_id, "Spot Welding", "工艺")
        with SessionLocal() as db:
            from app.models.knowledge import KnowledgeBase
            from app.services.kg_fusion import merge_entities

            kb = db.get(KnowledgeBase, uuid.UUID(kb_id))
            loser = db.get(GraphEntity, uuid.UUID(b))
            winner = db.get(GraphEntity, uuid.UUID(a))
            merge_entities(db, kb, winner, loser, method="manual", reason="t")

        r = client.get(f"/api/knowledge/bases/{kb_id}/graph", headers=h)
        self.assertEqual(r.status_code, 200)
        names = [n["name"] for n in r.json()["nodes"]]
        self.assertNotIn("Spot Welding", names)
        self.assertIn("点焊", names)


if __name__ == "__main__":
    unittest.main()
