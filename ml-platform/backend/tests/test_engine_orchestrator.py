"""Orchestrator engine unit tests."""
import sys, os, unittest
sys.path.insert(0, ".")

from app.engine.orchestrator import Orchestrator
from app.main import app
from app.database import Base, engine, SessionLocal

Base.metadata.create_all(bind=engine)


class TestOrchestrator(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.db_factory = SessionLocal
        cls.orch = Orchestrator(db_session_factory=cls.db_factory)

    def test_01_init(self):
        self.assertIsNotNone(self.orch)
        self.assertIsNotNone(self.orch.db_factory)
        self.assertEqual(self.orch.llm_key, "")

    def test_02_register_callback(self):
        called = []
        def cb(event_type, data):
            called.append((event_type, data))
        self.orch.register_callback("test_event", cb)
        self.assertIn("test_event", self.orch._callbacks)

    def test_03_decompose_quality_prediction(self):
        """Decompose weld quality prediction task (rule-based fallback)."""
        result = self.orch.decompose_with_llm("点焊质量预测任务")
        self.assertIsInstance(result, list)
        self.assertGreaterEqual(len(result), 2)
        self.assertEqual(result[0]["agent_type"], "executor")

    def test_04_decompose_parameter_recommendation(self):
        """Decompose parameter recommendation task."""
        result = self.orch.decompose_with_llm("焊接参数推荐与优化")
        self.assertIsInstance(result, list)
        self.assertGreaterEqual(len(result), 2)

    def test_05_decompose_generic_task(self):
        """Decompose generic task (fallback)."""
        result = self.orch.decompose_with_llm("做一个数据分析报告")
        self.assertIsInstance(result, list)
        self.assertEqual(result[0]["agent_type"], "llm")

    def test_06_request_review(self):
        result = self.orch.request_human_review(
            "task_001", "quality_check", {"score": 0.95}
        )
        self.assertEqual(result["status"], "awaiting_review")

    def test_07_get_pending_reviews(self):
        reviews = self.orch.get_pending_reviews()
        self.assertIsInstance(reviews, list)
        self.assertGreaterEqual(len(reviews), 1)

    def test_08_submit_review_approved(self):
        result = self.orch.submit_review("task_001", approved=True, comment="Looks good")
        self.assertEqual(result["status"], "ok")

    def test_09_submit_review_not_found(self):
        result = self.orch.submit_review("nonexistent_task", approved=True)
        self.assertEqual(result["status"], "not_found")

    def test_10_multiple_decompositions(self):
        tasks = [
            "质量预测",
            "参数推荐",
            "通用数据分析",
        ]
        for t in tasks:
            result = self.orch.decompose_with_llm(t)
            self.assertIsInstance(result, list)
            self.assertGreater(len(result), 0)


if __name__ == "__main__":
    unittest.main()
