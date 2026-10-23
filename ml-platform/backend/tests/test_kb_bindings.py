"""Knowledge center binding + unified retrieval tests (Task A6.1)."""

import os
import unittest
from uuid import uuid4

os.environ.setdefault("LLM_MASTER_KEY", __import__(
    "cryptography.fernet", fromlist=["Fernet"]
).Fernet.generate_key().decode("ascii"))

from app.database import Base, SessionLocal, engine  # noqa: E402
from app.models.experience_entry import ExperienceEntry  # noqa: E402
from app.models.kb_binding import KBBinding  # noqa: E402
from app.models.knowledge import Document, KnowledgeBase  # noqa: E402
from app.models.project import Project  # noqa: E402
from app.models.user import User  # noqa: E402
from app.services.knowledge_center import (  # noqa: E402
    get_or_create_binding,
    get_system_partition,
    project_experience_entry,
    unified_retrieve,
    update_binding,
)
from tests.auth_test_support import ensure_admin  # noqa: E402

Base.metadata.create_all(bind=engine)


class TestKBCenter(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        ensure_admin()
        db = SessionLocal()
        try:
            admin = db.query(User).filter(User.username == "admin").one()
            project = Project(name="kb-%s" % uuid4().hex[:8], owner_id=admin.id)
            db.add(project)
            kb = KnowledgeBase(
                name="工艺文档-%s" % uuid4().hex[:6],
                description="",
                owner_id=admin.id,
            )
            db.add(kb)
            db.commit()
            cls.admin_id = admin.id
            cls.project_id = project.id
            cls.kb_id = kb.id
        finally:
            db.close()

    def setUp(self):
        with SessionLocal() as db:
            db.query(ExperienceEntry).delete()
            db.query(KBBinding).delete()
            db.query(Document).delete()
            db.query(KnowledgeBase).filter(
                KnowledgeBase.name.like("平台经验%")
            ).delete()
            db.commit()

    def test_system_partition_cannot_be_disabled(self):
        with SessionLocal() as db:
            kb, binding = get_system_partition(db, self.admin_id)
            with self.assertRaises(ValueError):
                update_binding(db, binding, {"enabled": False})

    def test_scope_and_channel_filtering(self):
        with SessionLocal() as db:
            binding = get_or_create_binding(db, self.kb_id)
            update_binding(
                db,
                binding,
                {"scope_projects": [str(self.project_id)], "scope_chat": False},
            )

            from app.models.kb_binding import KBBinding as KB

            fresh = db.get(KB, binding.id)
            allowed = fresh.scope_projects == ["*"] or str(self.project_id) in (
                fresh.scope_projects or []
            )
            self.assertTrue(allowed)
            self.assertFalse(fresh.scope_chat)

    def test_unified_retrieve_merges_experience_partition_with_citations(self):
        with SessionLocal() as db:
            get_or_create_binding(db, self.kb_id)  # 未绑定的库不参与统一检索
            entry = ExperienceEntry(
                domain="tightening",
                situation="索引列被高权重利用",
                lesson="默认剔除",
                action="S2 drop",
                status="active",
                confidence=0.9,
                origin="human",
                evidence_json={"source": "test"},
            )
            db.add(entry)
            db.commit()
            entry_id = str(entry.id)

            def fake_chunks(db_, kb_, query_, top_k):
                return [
                    {
                        "content": "点焊质量取决于电流与压力",
                        "filename": "标准5.2",
                        "chunk_id": "c-1",
                        "score": 0.41,
                    }
                ]

            result = unified_retrieve(
                db,
                query="索引列怎么处理",
                channel="agent_s1",
                domain="tightening",
                retrieve_fn=fake_chunks,
            )
        sources = {item["source"] for item in result["citations"]}
        self.assertIn("exp", sources)
        exp_citation = next(item for item in result["citations"] if item["source"] == "exp")
        self.assertEqual(exp_citation["entry"], entry_id)
        self.assertIn("kb", sources)

    def test_projection_is_idempotent_by_entry_id(self):
        with SessionLocal() as db:
            entry = ExperienceEntry(
                domain="cross-domain",
                situation="s",
                lesson="l",
                action="a",
                status="active",
                confidence=0.9,
                origin="distilled",
                generality="cross-domain",
                evidence_json={"source_tasks": ["t1"]},
            )
            db.add(entry)
            db.commit()
            entry_id = entry.id
            first = project_experience_entry(db, entry, self.admin_id)
            second = project_experience_entry(db, entry, self.admin_id)
            docs = (
                db.query(Document)
                .filter(Document.filename == "经验 %s" % entry_id)
                .all()
            )
        self.assertEqual(first, second)
        self.assertIsNotNone(first)
        self.assertEqual(len(docs), 1)

    def test_projection_chunks_document_for_retrieval(self):
        from app.models.knowledge import Chunk
        from app.services.knowledge_retrieval import retrieve_chunks

        with SessionLocal() as db:
            entry = ExperienceEntry(
                domain="cross-domain",
                situation="索引列被树模型高权重利用",
                lesson="索引列默认剔除或频度编码",
                action="S2 脚本默认 drop 单基数码列",
                status="active",
                confidence=0.9,
                origin="distilled",
                generality="cross-domain",
                evidence_json={"source_tasks": ["t1"]},
            )
            db.add(entry)
            db.commit()
            project_experience_entry(db, entry, self.admin_id)
            kb, _binding = get_system_partition(db, self.admin_id)
            chunks = db.query(Chunk).filter(Chunk.doc_id.isnot(None)).all()
            kb_chunks = [
                chunk
                for chunk in chunks
                if db.get(Document, chunk.doc_id).kb_id == kb.id
            ]
            self.assertGreaterEqual(len(kb_chunks), 1)
            hits = retrieve_chunks(db, kb, "索引列", top_k=3)
        self.assertGreaterEqual(len(hits), 1)

    def test_domain_entry_not_projected(self):
        with SessionLocal() as db:
            entry = ExperienceEntry(
                domain="tightening",
                situation="s",
                lesson="l",
                action="a",
                status="active",
                confidence=0.9,
                origin="distilled",
                generality="domain",
                evidence_json={"source_tasks": ["t1"]},
            )
            db.add(entry)
            db.commit()
            result = project_experience_entry(db, entry, self.admin_id)
        self.assertIsNone(result)
