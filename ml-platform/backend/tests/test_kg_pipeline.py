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

    def test_job_failure_records_error(self):
        kb_id = _seed_kb("kg-job-fail")
        _seed_doc(kb_id, "a.txt", ["内容一句。"])
        with SessionLocal() as db:
            job = KgExtractionJob(kb_id=uuid.UUID(kb_id), mode="llm", status="pending", params={})
            db.add(job)
            db.commit()
            job_id = str(job.id)

        from app.services import knowledge_graph_llm_extraction as module

        with patch.object(module, "chat_completion_with_retry") as fake_llm:
            fake_llm.return_value = (None, {}, "llm_empty_completion")
            module.run_kg_extraction_job(job_id)

        with SessionLocal() as db:
            job = db.get(KgExtractionJob, uuid.UUID(job_id))
            # 单元失败不炸任务：llm_errors 记账，聚合仍可能为空层
            self.assertIn(job.status, ("succeeded", "failed"))
            self.assertGreaterEqual(job.llm_errors, 1)


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
