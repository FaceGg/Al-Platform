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
        """软优先域排序（方案 B，2026-11-18 用户拍板）：status/confidence 仍是
        硬门槛（shadow 不返回、0.69 < 0.7 拒收），域改为**排序软优先**——
        其他域条目仍返回但排在本域之后。"""
        with SessionLocal() as db:
            # 互异 lesson 防同文合并折叠（§10.1），保持过滤语义可断言
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
        self.assertIn(other_id, returned)       # 软优先：其他域仍注入
        # 域三段秩：本域在前，异域靠后（即便异域置信度更高 0.95 > 0.9）
        self.assertLess(returned.index(active_id), returned.index(other_id))

    def test_retrieval_soft_domain_ranking_order(self):
        """域三段秩：本域 > cross-domain > 其他域，域秩优先于置信度。"""
        with SessionLocal() as db:
            cross = self._record(db, confidence=0.93, lesson="软排序-跨域通用", generality="cross-domain")
            cross.domain = "cross-domain"
            cross.status = "active"
            other = self._record(db, confidence=0.92, lesson="软排序-其他域", domain="welding")
            other.status = "active"
            mine = self._record(db, confidence=0.72, lesson="软排序-本域")
            mine.status = "active"
            mine_id, cross_id, other_id = mine.id, cross.id, other.id
            entries = retrieve_for_task(
                db, domain="tightening", profile_fingerprint={}, top_k=10
            )
            order = [item.id for item in entries]
        self.assertEqual(
            order.index(mine_id), 0, "本域低置信（0.72）仍应排最前（域秩优先）"
        )
        self.assertLess(order.index(cross_id), order.index(other_id))

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

    def test_outcome_decay_below_gate_removes_projection(self):
        """调分跌破投影门槛 → 系统分区投影同步移除（衰减反向同步）。

        用户实测：投影显示 ≥0.85 而真源已被任务失败反馈衰减到 0.81——
        平台不再注入的教训不应继续被 RAG 检索引用。"""
        from app.models.knowledge import Document
        from app.services.knowledge_center import (
            get_system_partition,
            project_experience_entry,
        )

        with SessionLocal() as db:
            partition, _binding = get_system_partition(db, None)
            entry = self._record(db, confidence=0.90)  # ≥0.85 先投影
            entry_id = entry.id
            project_experience_entry(db, entry, None)
            self.assertIsNotNone(
                db.query(Document)
                .filter(Document.kb_id == partition.id, Document.filename == f"经验 {entry_id}")
                .first()
            )
        with SessionLocal() as db:
            apply_experience_task_outcome(db, [entry_id], passed=False)  # 0.90×0.9=0.81 <0.85
        with SessionLocal() as db:
            partition, _binding = get_system_partition(db, None)
            doc = (
                db.query(Document)
                .filter(Document.kb_id == partition.id, Document.filename == f"经验 {entry_id}")
                .first()
            )
            self.assertIsNone(doc)  # 跌破门槛 → 投影移除
            self.assertEqual(float(db.get(type(entry), entry_id).confidence), 0.81)

    def test_outcome_decay_above_gate_refreshes_projection(self):
        """调分仍达门槛 → 投影保留且正文置信度刷新（不再显示衰减前数值）。"""
        from app.models.knowledge import Document
        from app.services.knowledge_center import (
            get_system_partition,
            project_experience_entry,
        )

        with SessionLocal() as db:
            partition, _binding = get_system_partition(db, None)
            entry = self._record(db, confidence=0.95)  # 封顶值，投影
            entry_id = entry.id
            project_experience_entry(db, entry, None)
            before = (
                db.query(Document)
                .filter(Document.kb_id == partition.id, Document.filename == f"经验 {entry_id}")
                .first()
            )
            self.assertIsNotNone(before)
            self.assertIn("置信度：0.95", before.content)
        with SessionLocal() as db:
            apply_experience_task_outcome(db, [entry_id], passed=False)  # 0.95×0.9=0.855 ≥0.85
        with SessionLocal() as db:
            partition, _binding = get_system_partition(db, None)
            after = (
                db.query(Document)
                .filter(Document.kb_id == partition.id, Document.filename == f"经验 {entry_id}")
                .first()
            )
            self.assertIsNotNone(after)  # 仍达门槛 → 投影保留
            self.assertNotIn("置信度：0.95", after.content)  # 正文已刷新
            self.assertIn("置信度：0.85", after.content)  # 0.855 两位小数
            self.assertEqual(float(db.get(type(entry), entry_id).confidence), 0.855)

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
            # 同文自动合并（§10.1）的去重键剥空白/标点/数字（「同教训不同
            # 置信度尾缀」视为重复）——排名/计数类用例必须用**语义互异**的
            # lesson 造独立条目；仅改数字尾缀（-0.8/-0.9）规范化后同文会
            # 折叠为一条（CI 双 OS 实测 1 != 2）。
            distinct_lessons = (
                "索引类单基数码列默认剔除",
                "索引列改用频度编码保留",
                "波形索引列禁止默认剔除",
            )
            for confidence, lesson in zip((0.8, 0.9, 0.85), distinct_lessons):
                entry = self._record(
                    db, confidence=confidence,
                    lesson=lesson,
                )
                entry.status = "active"
            entries = retrieve_for_task(
                db, domain="tightening", profile_fingerprint={}, top_k=2
            )
            confidences = [item.confidence for item in entries]
            self.assertEqual(confidences, sorted(confidences, reverse=True))
            self.assertEqual(len(entries), 2)
