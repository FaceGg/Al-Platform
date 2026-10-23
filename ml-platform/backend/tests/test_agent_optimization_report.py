"""Optimization report tests (AutoML Agent plan, Task A5.2)."""

import os
import unittest
from unittest import mock
from uuid import uuid4

os.environ.setdefault("LLM_MASTER_KEY", __import__(
    "cryptography.fernet", fromlist=["Fernet"]
).Fernet.generate_key().decode("ascii"))

from app.database import Base, SessionLocal, engine  # noqa: E402
from app.models.agent_run import AgentRun  # noqa: E402
from app.services.agent.optimization_report import build_report  # noqa: E402
from app.services.llm_gateway import GatewayLLMConfig  # noqa: E402

Base.metadata.create_all(bind=engine)

_GOOD_REPLY = """
```json
{
  "what_optimized": ["剔除 ID 索引列（轮1 评审发现）"],
  "findings": ["扭矩偏差是第一主导特征"],
  "strengths": ["不合格召回 0.944（门禁 0.90）"],
  "unsatisfactory": [
    {"issue": "精确率低于预期", "cause": "边界贴限样本",
     "missing": "缺少螺栓规格分层阈值列", "suggestion": "补 SPECIFICATION 特征"}
  ],
  "next_hints": ["补充分组特征"]
}
```
"""


def _config():
    return GatewayLLMConfig(
        api_url="https://api.example.com/v1",
        api_key="sk-" + uuid4().hex,
        model_id="glm-4.6",
        temperature=None,
        timeout_seconds=30,
        profile_id=str(uuid4()),
        profile_name="report-test",
    )


class TestOptimizationReport(unittest.TestCase):
    def _make_run(self, **fields):
        with SessionLocal() as db:
            run = AgentRun(target_column="target", **fields)
            db.add(run)
            db.commit()
            run_id = run.id
        db = SessionLocal()
        self.addCleanup(db.close)
        return db, db.get(AgentRun, run_id)

    def test_report_generated_and_cost_from_counters(self):
        db, run = self._make_run(
            token_used=412000, round_count=2, token_budget=500000
        )
        run.status = "accepted"
        run.memory_json = {
            "rounds": [{"round": 1, "verdict": "pass"}],
            "gate_warnings": [],
        }
        self.db_commit = True
        with mock.patch(
            "app.services.agent.optimization_report.chat_completion",
            return_value=(_GOOD_REPLY, {}),
        ):
            report, error = build_report(
                db,
                run=run,
                config=_config(),
                metrics={"recall_minority": 0.944},
            )
        self.assertIsNone(error)
        self.assertEqual(report.cost, {})
        result = run.result_json
        self.assertEqual(result["cost"]["llm_tokens"], 412000)
        self.assertEqual(result["cost"]["rounds_total"], 2)
        self.assertIn("cost", result["optimization_report"])
        self.assertEqual(
            result["optimization_report"]["cost"]["llm_tokens"], 412000
        )

    def test_platform_counters_survive_llm_failure(self):
        db, run = self._make_run(token_used=1000, round_count=1)
        run.status = "waiting_escalate"
        with mock.patch(
            "app.services.agent.optimization_report.chat_completion",
            side_effect=RuntimeError("boom"),
        ):
            report, error = build_report(db, run=run, config=_config())
        self.assertIsNone(report)
        self.assertIn("llm_call_failed", error)
        self.assertEqual(run.result_json["cost"]["llm_tokens"], 1000)

    def test_contract_violation_reported(self):
        db, run = self._make_run(token_used=5)
        bad = '{"what_optimized": "应该是数组"}'
        with mock.patch(
            "app.services.agent.optimization_report.chat_completion",
            return_value=(bad, {}),
        ):
            report, error = build_report(db, run=run, config=_config())
        self.assertIsNone(report)
        self.assertIn("contract_violation", error)
