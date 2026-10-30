"""Experience store tests (AutoML Agent plan, Task A3.1).

Contract under test (spec v0.9 §10.2/§16.5): distilled entries start in
``shadow`` (hits counted, not injected) with mandatory evidence; human-sourced
entries are directly active at 0.75; retrieval filters status/domain/
confidence with an explicit ``>= 0.7`` boundary; shadow entries promote to
active after two hits; retirement filters immediately.
"""

import os
import unittest
from uuid import uuid4

os.environ.setdefault("LLM_MASTER_KEY", __import__(
    "cryptography.fernet", fromlist=["Fernet"]
).Fernet.generate_key().decode("ascii"))

from app.database import Base, SessionLocal, engine  # noqa: E402
from app.models.experience_entry import ExperienceEntry  # noqa: E402
from app.services.agent.experience import (  # noqa: E402
    ExperienceEvidenceRequired,
    promote_shadow_entries,
    record_experience,
    retire_entry,
    retrieve_for_task,
)

Base.metadata.create_all(bind=engine)


class TestExperienceStore(unittest.TestCase):
    def setUp(self):
        # Shared test database: start each test from an empty experience store.
        with SessionLocal() as db:
            db.query(ExperienceEntry).delete()
            db.commit()

    def _record(self, db, **overrides):
        fields = dict(
            domain="tightening",
            situation="索引列被树模型高权重利用",
            lesson="索引类列默认剔除",
            action="S2 默认 drop 单基数码列",
            evidence={"source_tasks": ["task-" + uuid4().hex[:6]]},
            generality="cross-domain",
            confidence=0.86,
        )
        fields.update(overrides)
        return record_experience(db, **fields)

    def test_distilled_entry_starts_shadow_with_evidence(self):
        with SessionLocal() as db:
            entry = self._record(db)
            self.assertEqual(entry.status, "shadow")
            self.assertEqual(entry.origin, "distilled")

    def test_distilled_entry_requires_evidence(self):
        with SessionLocal() as db:
            with self.assertRaises(ExperienceEvidenceRequired):
                self._record(db, evidence={"source_tasks": []})

    def test_human_entry_directly_active(self):
        with SessionLocal() as db:
            entry = self._record(
                db, origin="human", confidence=0.75,
                evidence={"source": "chat_save_insight"},
            )
            self.assertEqual(entry.status, "active")
            self.assertEqual(entry.confidence, 0.75)

    def test_retrieval_filters_status_confidence_and_domain(self):
        with SessionLocal() as db:
            self._record(db, confidence=0.86)  # shadow → counted, not returned
            active = self._record(db, confidence=0.9)
            active.status = "active"
            low = self._record(db, confidence=0.69)
            low.status = "active"
            other_domain = self._record(db, domain="welding", confidence=0.95)
            other_domain.status = "active"
            active_id, low_id, other_id = active.id, low.id, other_domain.id
            entries = retrieve_for_task(
                db, domain="tightening", profile_fingerprint={}, top_k=10
            )
            returned = [item.id for item in entries]
        self.assertIn(active_id, returned)
        self.assertNotIn(low_id, returned)      # 0.69 < 0.7
        self.assertNotIn(other_id, returned)    # domain mismatch

    def test_confidence_boundary_is_inclusive(self):
        with SessionLocal() as db:
            boundary = self._record(db, confidence=0.70)
            boundary.status = "active"
            boundary_id = boundary.id
            entries = retrieve_for_task(
                db, domain="tightening", profile_fingerprint={}, top_k=10
            )
            self.assertIn(boundary_id, [item.id for item in entries])

    def test_shadow_hits_promote_to_active(self):
        with SessionLocal() as db:
            entry = self._record(db)
            entry_id = entry.id
            for _ in range(2):
                retrieve_for_task(
                    db, domain="tightening", profile_fingerprint={}, top_k=10
                )
            db.expire_all()
            # hit_count≥2 后检索内自动升级（RSI 接线），无需外部触发。
            refreshed = db.get(type(entry), entry_id)
            self.assertEqual(refreshed.hit_count, 2)
            self.assertEqual(refreshed.status, "active")
            entries = retrieve_for_task(
                db, domain="tightening", profile_fingerprint={}, top_k=10
            )
            self.assertIn(entry_id, [item.id for item in entries])

    def test_promotion_projects_cross_domain_entry_into_system_partition(self):
        """知识中心验收回归：升 active 的跨域条目自动投影系统分区文档。"""
        from app.models.knowledge import Document
        from app.services.knowledge_center import get_system_partition

        with SessionLocal() as db:
            partition, _binding = get_system_partition(db, None)
            before = db.query(Document).filter(Document.kb_id == partition.id).count()
            entry = self._record(db, confidence=0.9)  # cross-domain, ≥0.85 gate
            entry_id = entry.id
            for _ in range(2):
                retrieve_for_task(
                    db, domain="tightening", profile_fingerprint={}, top_k=10
                )
            db.expire_all()
            promoted = db.get(type(entry), entry_id)
            self.assertEqual(promoted.status, "active")
            after = db.query(Document).filter(Document.kb_id == partition.id).count()
            self.assertGreater(after, before)
            doc = (
                db.query(Document)
                .filter(Document.kb_id == partition.id, Document.filename == f"经验 {entry_id}")
                .first()
            )
            self.assertIsNotNone(doc)
            self.assertIn("教训：", doc.content)

    def test_retire_filters_immediately(self):
        with SessionLocal() as db:
            entry = self._record(db)
            entry.status = "active"
            db.commit()
            entry_id = entry.id
            retire_entry(db, entry_id)
            entries = retrieve_for_task(
                db, domain="tightening", profile_fingerprint={}, top_k=10
            )
            self.assertNotIn(entry_id, [item.id for item in entries])

    def test_top_k_ranking_by_confidence(self):
        with SessionLocal() as db:
            for confidence in (0.8, 0.9, 0.85):
                entry = self._record(db, confidence=confidence)
                entry.status = "active"
            entries = retrieve_for_task(
                db, domain="tightening", profile_fingerprint={}, top_k=2
            )
            confidences = [item.confidence for item in entries]
            self.assertEqual(confidences, sorted(confidences, reverse=True))
            self.assertEqual(len(entries), 2)
