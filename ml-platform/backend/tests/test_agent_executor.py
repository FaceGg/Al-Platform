"""Executor + L2 injection + closing-report tests (P0 wiring).

The executor drives a REAL run row end-to-end: dataset artifact → profile →
runner (LLM faked at the runner-module boundary) → real lightweight trainer →
terminal state. Closing chain (distill + OptimizationReport) is exercised with
the gateway call faked at each service module.
"""

import io
import os
import tempfile
import time
import unittest
import uuid
from pathlib import Path
from unittest import mock
from uuid import uuid4

os.environ.setdefault("LLM_MASTER_KEY", __import__(
    "cryptography.fernet", fromlist=["Fernet"]
).Fernet.generate_key().decode("ascii"))

import pandas as pd  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.database import Base, SessionLocal, engine  # noqa: E402
from app.models.agent_run import AgentRun  # noqa: E402
from app.models.experience_entry import ExperienceEntry  # noqa: E402
from app.models.llm_profile import LLMProfile  # noqa: E402
from app.services.agent import runner as runner_module  # noqa: E402
from app.services.agent.contracts import (  # noqa: E402
    AnalysisReport,
    FeatureScript,
    ReviewVerdict,
)
from app.services.agent.executor import (  # noqa: E402
    AgentRunNotExecutable,
    execute_agent_run,
    launch_agent_run,
)
from app.services.artifact_service import build_artifact_service  # noqa: E402
from tests.auth_test_support import ensure_admin  # noqa: E402

Base.metadata.create_all(bind=engine)

_REPORT = AnalysisReport(
    domain_hypothesis="tightening",
    domain_reasoning="扭矩域",
    focus_channels=[{"name": "dev", "columns": ["F1"], "why": "主因"}],
    expected_important_features=[{"name_hint": "D", "reason": "r", "priority": "high"}],
    leakage_suspects=[],
    feature_engineering_brief="派生偏差",
)
_SCRIPT = FeatureScript(
    script=(
        "def transform(df):\n"
        "    out = df.copy()\n"
        "    out['D'] = out['F1'] - out['F2']\n"
        "    return out\n"
    ),
    description="偏差特征",
)
_VERDICT_PASS = ReviewVerdict(verdict="pass", business_readiness="可上线")

_DISTILL_REPLY = (
    '[{"situation": "小样本场景", "lesson": "优先轻量模型", '
    '"action": "S3 默认从轻量家族起步", "generality": "cross-domain", "confidence": 0.82}]'
)
_REPORT_REPLY = (
    '{"what_optimized": ["剔除常量列"], "findings": ["F1 主导"], '
    '"strengths": ["链路一轮收敛"], "unsatisfactory": [], "next_hints": []}'
)


def _frame_csv() -> bytes:
    frame = pd.DataFrame(
        {
            "F1": [5.0 + i * 0.01 for i in range(60)] + [0.1 + i * 0.01 for i in range(60)],
            "F2": [-1.0] * 60 + [1.0] * 60,
            "target": [1] * 60 + [0] * 60,
        }
    )
    buffer = io.BytesIO()
    frame.to_csv(buffer, index=False)
    return buffer.getvalue()


class ExecutorHarness(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        ensure_admin()
        with SessionLocal() as db:
            from app.models.project import Project
            from app.models.user import User

            cls.admin_id = (
                db.query(User).filter(User.username == "admin").one().id
            )
            project = Project(name="exec-%s" % uuid4().hex[:8], owner_id=cls.admin_id)
            db.add(project)
            db.flush()
            cls.project_id = project.id
            service = build_artifact_service(db)
            with tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / "agent_exec.csv"
                path.write_bytes(_frame_csv())
                artifact = service.create_from_file(
                    project.id, path, "agent-exec-%s" % uuid4().hex[:6], "dataset"
                )
                db.commit()
                cls.artifact_id = artifact.id
            profile = LLMProfile(
                name="exec-%s" % uuid4().hex[:6],
                api_url="https://api.exec-test-llm.com/v1/chat/completions",
                model_id="glm-4.6",
                is_default=False,
            )
            from app.config import settings as app_settings
            from app.services.llm_profile_crypto import encrypt_llm_api_key

            if app_settings.llm_master_key is None:
                from cryptography.fernet import Fernet as _Fernet
                from pydantic import SecretStr

                app_settings.llm_master_key = SecretStr(_Fernet.generate_key().decode())
            profile.api_key_encrypted = encrypt_llm_api_key(
                "sk-" + uuid4().hex, app_settings.llm_master_key
            )
            db.add(profile)
            db.commit()
            cls.profile_id = profile.id

    def _make_run(self, **extra) -> str:
        fields = {
            "project_id": self.project_id,
            "dataset_artifact_id": self.artifact_id,
            "target_column": "target",
            "llm_profile_id": self.profile_id,
            "created_by": self.admin_id,
        }
        fields.update(extra)
        with SessionLocal() as db:
            run = AgentRun(**fields)
            db.add(run)
            db.commit()
            return str(run.id)

    def _patch_llm(self, captured=None):
        def fake_s1(db, **kwargs):
            if captured is not None:
                captured.append(kwargs)
            return _REPORT, None, {"total_tokens": 50}

        def fake_s2(db, **kwargs):
            return _SCRIPT, None, {"total_tokens": 50}

        def fake_s4(db, **kwargs):
            return _VERDICT_PASS, None, {"total_tokens": 50}

        patches = []
        for target, replacement in (
            ("run_s1", fake_s1),
            ("run_s2", fake_s2),
            ("run_s4", fake_s4),
        ):
            patcher = mock.patch.object(runner_module, target, replacement)
            patcher.start()
            patches.append(patcher)
        self.addCleanup(lambda: [p.stop() for p in patches])


class TestExecutor(ExecutorHarness, unittest.TestCase):
    def test_execute_run_end_to_end_accepted_with_real_trainer(self):
        run_id = self._make_run()
        self._patch_llm()
        with mock.patch(
            "app.services.agent.experience._distill_chat_completion",
            return_value=(_DISTILL_REPLY, {}),
        ), mock.patch(
            "app.services.agent.optimization_report.chat_completion",
            return_value=(_REPORT_REPLY, {}),
        ):
            execute_agent_run(run_id)
        with SessionLocal() as db:
            run = db.get(AgentRun, uuid.UUID(run_id))
            self.assertEqual(run.status, "accepted")
            self.assertGreater(
                run.result_json["metrics"].get("recall_minority", 0), 0.8
            )
            self.assertIn("optimization_report", run.result_json)
            self.assertIn("distilled_experience", run.result_json)

    def test_launch_thread_reaches_terminal_state(self):
        run_id = self._make_run()
        self._patch_llm()
        launch_agent_run(run_id, actor_id=self.admin_id)
        deadline = time.time() + 60
        status = "pending"
        while time.time() < deadline:
            with SessionLocal() as db:
                status = db.get(AgentRun, uuid.UUID(run_id)).status
            if status in ("accepted", "waiting_escalate", "failed", "cancelled"):
                break
            time.sleep(0.5)
        self.assertEqual(status, "accepted")

    def test_not_executable_on_missing_target(self):
        run_id = self._make_run(target_column="nonexistent_col")
        with self.assertRaises(AgentRunNotExecutable):
            execute_agent_run(run_id)


class TestL2InjectionAndDistill(ExecutorHarness, unittest.TestCase):
    def test_s1_receives_active_experience_references(self):
        with SessionLocal() as db:
            entry = ExperienceEntry(
                domain="cross-domain",
                situation="索引列被误用",
                lesson="索引列默认剔除",
                action="S2 drop",
                status="active",
                confidence=0.9,
                origin="human",
                evidence_json={"source": "test"},
            )
            db.add(entry)
            db.commit()
        captured: list[dict] = []
        run_id = self._make_run()
        self._patch_llm(captured)
        with mock.patch(
            "app.services.agent.experience._distill_chat_completion",
            return_value=("[]", {}),
        ), mock.patch(
            "app.services.agent.optimization_report.chat_completion",
            return_value=(_REPORT_REPLY, {}),
        ):
            execute_agent_run(run_id)
        self.assertTrue(captured)
        references = captured[0].get("experience_references") or []
        self.assertTrue(any("索引列" in str(ref.get("lesson")) for ref in references))

    def test_distill_creates_shadow_entries_with_evidence_chain(self):
        run_id = self._make_run()
        self._patch_llm()
        with mock.patch(
            "app.services.agent.experience._distill_chat_completion",
            return_value=(_DISTILL_REPLY, {}),
        ), mock.patch(
            "app.services.agent.optimization_report.chat_completion",
            return_value=(_REPORT_REPLY, {}),
        ):
            execute_agent_run(run_id)
        with SessionLocal() as db:
            run = db.get(AgentRun, uuid.UUID(run_id))
            distilled_ids = run.result_json.get("distilled_experience") or []
            self.assertEqual(len(distilled_ids), 1)
            entry = db.get(ExperienceEntry, uuid.UUID(distilled_ids[0]))
            self.assertEqual(entry.status, "shadow")
            self.assertEqual(entry.origin, "distilled")
            self.assertEqual(entry.evidence_json.get("source_tasks"), [run_id])

    def test_escalate_path_also_distills_lessons(self):
        def failing_s2(db, **kwargs):
            return None, "contract_violation: bad", {"total_tokens": 5}

        run_id = self._make_run()
        self._patch_llm()
        with mock.patch.object(runner_module, "run_s2", failing_s2), mock.patch(
            "app.services.agent.experience._distill_chat_completion",
            return_value=(_DISTILL_REPLY, {}),
        ), mock.patch(
            "app.services.agent.optimization_report.chat_completion",
            side_effect=RuntimeError("report unavailable"),
        ):
            execute_agent_run(run_id)
        with SessionLocal() as db:
            run = db.get(AgentRun, uuid.UUID(run_id))
            self.assertEqual(run.status, "waiting_escalate")
            # 报告失败不影响蒸馏，也不影响终态。
            self.assertEqual(len(run.result_json.get("distilled_experience") or []), 1)
