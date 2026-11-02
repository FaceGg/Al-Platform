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
    apply_experience_task_outcome,
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

    def test_same_lesson_merges_into_existing_entry(self):
        # §10.1 去重合同：同域同文折叠为一条——置信度取高者、任务并集
        with SessionLocal() as db:
            first = self._record(db, confidence=0.6)
            first_id = first.id
            merged = self._record(db, confidence=0.9, source_tasks=["task-extra"])
            self.assertEqual(merged.id, first_id)
            self.assertEqual(float(merged.confidence), 0.9)
            self.assertIn("task-extra", merged.source_tasks)
            self.assertEqual(
                db.query(ExperienceEntry).count(), 1,
            )

    def test_distilled_entry_requires_evidence(self):
        with SessionLocal() as db:
            with self.assertRaises(ExperienceEvidenceRequired):
                self._record(db, evidence={"source_tasks": []})

    def test_outcome_pass_bumps_confidence_and_counts(self):
        with SessionLocal() as db:
            entry = self._record(db, confidence=0.8)
            db.query(ExperienceEntry).filter(
                ExperienceEntry.id == entry.id
            ).update({"status": "active"})
            db.commit()
            entry_id = entry.id
            apply_experience_task_outcome(db, [entry_id], passed=True)
            refreshed = db.get(ExperienceEntry, entry_id)
        self.assertAlmostEqual(float(refreshed.confidence), 0.82, places=4)
        self.assertEqual(refreshed.success_count, 1)
        self.assertEqual(refreshed.fail_count, 0)
        self.assertEqual(refreshed.status, "active")

    def test_outcome_fail_decays_and_demotes_below_gate(self):
        # 0.72 × 0.9 = 0.648 < 0.70 注入门 → 回 shadow 并清零冷静期
        with SessionLocal() as db:
            entry = self._record(db, confidence=0.72)
            db.query(ExperienceEntry).filter(
                ExperienceEntry.id == entry.id
            ).update({"status": "active", "hit_count": 5})
            db.commit()
            entry_id = entry.id
            apply_experience_task_outcome(db, [entry_id], passed=False)
            refreshed = db.get(ExperienceEntry, entry_id)
        self.assertAlmostEqual(float(refreshed.confidence), 0.648, places=4)
        self.assertEqual(refreshed.fail_count, 1)
        self.assertEqual(refreshed.status, "shadow")
        self.assertEqual(refreshed.hit_count, 0)

    def test_outcome_fail_keeps_active_above_gate(self):
        with SessionLocal() as db:
            entry = self._record(db, confidence=0.9)
            db.query(ExperienceEntry).filter(
                ExperienceEntry.id == entry.id
            ).update({"status": "active"})
            db.commit()
            entry_id = entry.id
            apply_experience_task_outcome(db, [entry_id], passed=False)
            refreshed = db.get(ExperienceEntry, entry_id)
        self.assertAlmostEqual(float(refreshed.confidence), 0.81, places=4)
        self.assertEqual(refreshed.status, "active")

    def test_outcome_leaves_retired_untouched(self):
        with SessionLocal() as db:
            entry = self._record(db, confidence=0.9)
            db.query(ExperienceEntry).filter(
                ExperienceEntry.id == entry.id
            ).update({"status": "retired"})
            db.commit()
            entry_id = entry.id
            apply_experience_task_outcome(db, [entry_id], passed=False)
            refreshed = db.get(ExperienceEntry, entry_id)
        self.assertEqual(refreshed.status, "retired")
        self.assertAlmostEqual(float(refreshed.confidence), 0.9, places=4)
        self.assertEqual(refreshed.fail_count, 1)  # 计数仍如实累计

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
            # A 批次：互异 lesson 防同文合并折叠（§10.1），保持过滤语义可断言
            self._record(db, confidence=0.86, lesson="教训-影子")  # shadow → counted, not returned
            active = self._record(db, confidence=0.9, lesson="教训-主条目")
            active.status = "active"
            low = self._record(db, confidence=0.69, lesson="教训-低置信")
            low.status = "active"
            other_domain = self._record(db, domain="welding", confidence=0.95, lesson="教训-异域")
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
            # A 批次：同文自动合并（§10.1）上线后，排名/计数类用例必须用
            # 互异 lesson 造独立条目，否则三条会折叠为一条
            for confidence in (0.8, 0.9, 0.85):
                entry = self._record(
                    db, confidence=confidence,
                    lesson=f"索引类列默认剔除-{confidence}",
                )
                entry.status = "active"
            entries = retrieve_for_task(
                db, domain="tightening", profile_fingerprint={}, top_k=2
            )
            confidences = [item.confidence for item in entries]
            self.assertEqual(confidences, sorted(confidences, reverse=True))
            self.assertEqual(len(entries), 2)
