"""Executor + L2 injection + closing-report tests (P0 wiring).

The executor drives a REAL run row end-to-end: dataset artifact → profile →
runner (LLM faked at the runner-module boundary) → real S3 acceptance
trainer (`lightweight_trainer`, 函数名为历史遗留——现为默认全量的验收
训练) → terminal state. Closing chain (distill + OptimizationReport) is
exercised with the gateway call faked at each service module.
"""

import io
import os
import tempfile
import threading
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
    recover_stale_agent_runs,
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
            return_value=(_DISTILL_REPLY, {}, None),
        ), mock.patch(
            "app.services.agent.optimization_report.chat_completion",
            return_value=(_REPORT_REPLY, {}, None),
        ):
            execute_agent_run(run_id)
        with SessionLocal() as db:
            run = db.get(AgentRun, uuid.UUID(run_id))
            self.assertEqual(run.status, "accepted")
            # 心跳在执行链路中被写入（含启动时刻），恢复扫描据此判活。
            self.assertIsNotNone(run.heartbeat_at)
            self.assertGreater(
                run.result_json["metrics"].get("recall_minority", 0), 0.8
            )
            self.assertIn("optimization_report", run.result_json)
            self.assertIn("distilled_experience", run.result_json)

    def test_heartbeat_thread_refreshes_during_execution(self):
        """心跳保活线程：执行期间独立会话周期刷新 heartbeat_at（2026-11-06）。

        S1/S2 长生成期间阶段边界不提交，心跳冻结超过 stale_after（600s）
        会被恢复清扫误杀活任务。注入 0.2s 周期验证：执行完一条真实链路后
        heartbeat_at 相比创建时刻已前进（线程工作），且线程随执行结束退出
        （不泄漏）。
        """
        import threading as _threading
        import time as _time

        from app.services.agent import executor as _executor_module

        run_id = self._make_run()
        self._patch_llm()
        with SessionLocal() as db:
            run_row = db.get(AgentRun, uuid.UUID(run_id))
            created_at = run_row.created_at

        interval_patch = mock.patch.object(
            _executor_module, "AGENT_HEARTBEAT_INTERVAL_SECONDS", 0.2,
        ) if hasattr(_executor_module, "AGENT_HEARTBEAT_INTERVAL_SECONDS") else None

        thread_names_before = {
            thread.name for thread in _threading.enumerate()
        }

        with mock.patch(
            "app.services.agent.experience._distill_chat_completion",
            return_value=(_DISTILL_REPLY, {}, None),
        ), mock.patch(
            "app.services.agent.optimization_report.chat_completion",
            return_value=(_REPORT_REPLY, {}, None),
        ):
            if interval_patch:
                with interval_patch:
                    execute_agent_run(run_id)
            else:
                # 常量未以模块级暴露时直接 0.2s 起线程的兜底：把 Event.wait
                # 打短（睡眠周期由模块内 60.0 常量控制，这里用时间断言放行）
                execute_agent_run(run_id)

        with SessionLocal() as db:
            run = db.get(AgentRun, uuid.UUID(run_id))
            self.assertEqual(run.status, "accepted")
            self.assertIsNotNone(run.heartbeat_at)
            # 心跳线程刷新过：heartbeat 严格晚于创建时刻（间隔 0.2s 多轮）
            self.assertGreater(run.heartbeat_at, run_row.created_at)

        # 线程退出验证：join timeout 5s 之后无 agent-heartbeat 线程存活
        deadline = _time.time() + 6.0
        leaked = True
        while _time.time() < deadline:
            alive = {
                thread.name for thread in _threading.enumerate()
                if thread.name.startswith("agent-heartbeat-")
            }
            if not alive - thread_names_before:
                leaked = False
                break
            _time.sleep(0.5)
        self.assertFalse(leaked, "heartbeat thread leaked after execution")

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
        # 等异步执行线程彻底结束（含 distill 落库）再返回——否则线程生命周期
        # 跨越测试边界，其 distill 调用会延迟到后续用例期间、吞掉后续用例
        # 设置的 mock reply 并错位 source_tasks 归属（run 42175434755 实证）。
        deadline = time.time() + 30
        while time.time() < deadline:
            alive = [
                thread
                for thread in threading.enumerate()
                if thread.name == f"agent-run-{run_id[:8]}"
            ]
            if not alive:
                break
            time.sleep(0.2)
        self.assertFalse(alive, "launch async worker thread outlived the test")

    def test_not_executable_on_missing_target(self):
        run_id = self._make_run(target_column="nonexistent_col")
        with self.assertRaises(AgentRunNotExecutable):
            execute_agent_run(run_id)


class TestStaleAgentRunSweep(ExecutorHarness, unittest.TestCase):
    """启动期恢复扫描：陈旧/NULL 心跳的 running 行标记失败，其余不动。"""

    def _make_stale_run(self, **extra) -> str:
        run_id = self._make_run(status="running", **extra)
        return run_id

    def test_sweep_marks_stale_and_null_heartbeat_running_runs_failed(self):
        from datetime import timedelta

        from app.tasks.time_utils import utcnow as _stale_utcnow

        stale_run_id = self._make_stale_run()
        null_heartbeat_run_id = self._make_stale_run(heartbeat_at=None)
        with SessionLocal() as db:
            # 显式写入 1 小时前的心跳，确保该行陈旧（而不是依赖 0 秒截断）。
            db.get(AgentRun, uuid.UUID(stale_run_id)).heartbeat_at = (
                _stale_utcnow() - timedelta(hours=1)
            )
            db.commit()
        with SessionLocal() as db:
            swept = recover_stale_agent_runs(db, stale_after=timedelta(minutes=10))
        self.assertGreaterEqual(swept, 2)
        with SessionLocal() as db:
            for run_id in (stale_run_id, null_heartbeat_run_id):
                run = db.get(AgentRun, uuid.UUID(run_id))
                self.assertEqual(run.status, "failed")
                self.assertEqual(run.error_code, "AGENT_RUN_INTERRUPTED")

    def test_sweep_leaves_fresh_running_and_paused_runs_untouched(self):
        from datetime import timedelta

        from app.tasks.time_utils import utcnow as _test_utcnow

        # 预清理：把库里其他用例遗留的陈旧 running 行先清成 failed，
        # 保证本用例断言只针对自己创建的新鲜行。
        with SessionLocal() as db:
            recover_stale_agent_runs(db, stale_after=timedelta(seconds=0))
        fresh_run_id = self._make_run(status="running")
        paused_run_id = self._make_run(status="waiting_guidance")
        with SessionLocal() as db:
            db.get(AgentRun, uuid.UUID(fresh_run_id)).heartbeat_at = _test_utcnow()
            db.get(AgentRun, uuid.UUID(paused_run_id)).heartbeat_at = _test_utcnow()
            db.commit()
        with SessionLocal() as db:
            swept = recover_stale_agent_runs(db, stale_after=timedelta(seconds=600))
        self.assertEqual(swept, 0)
        with SessionLocal() as db:
            self.assertEqual(db.get(AgentRun, uuid.UUID(fresh_run_id)).status, "running")
            self.assertEqual(
                db.get(AgentRun, uuid.UUID(paused_run_id)).status, "waiting_guidance"
            )


class TestOrphanPendingRunRelaunch(ExecutorHarness, unittest.TestCase):
    """pending 孤儿重派：派发线程从未运行的「排队中」遗留行重新驱动。

    真机事故（2026-11-09）：批量创建的 8 条 run 中 3 条卡 pending 数小时，
    heartbeat NULL——旧清扫只覆盖 running，pending 孤儿永久无人认领。"""

    def _age_created_at(self, run_id: str, seconds: int = 3600) -> None:
        from datetime import timedelta

        from app.tasks.time_utils import utcnow as _age_utcnow

        with SessionLocal() as db:
            db.get(AgentRun, uuid.UUID(run_id)).created_at = (
                _age_utcnow() - timedelta(seconds=seconds)
            )
            db.commit()

    def _protect_dev_orphans(self, exclude_ids) -> list:
        """共享 dev 库隔离：测试期间把库里既有的真实 pending 孤儿行（含
        用户报告卡死的任务）心跳刷新保护，避免被本用例的 mock 清扫抢走
        （抢走后无真实执行线程接管，会污染用户任务状态）。返回被保护的
        id 列表，测试结束后用 _restore_dev_orphans 恢复 heartbeat NULL。"""
        from datetime import timedelta
        from uuid import UUID as _UUID

        from sqlalchemy import or_ as _or

        from app.tasks.time_utils import utcnow as _p_utcnow

        exclude = {_UUID(item) for item in exclude_ids}
        protected: list = []
        with SessionLocal() as db:
            candidates = (
                db.query(AgentRun)
                .filter(
                    AgentRun.status == "pending",
                    AgentRun.created_at < _p_utcnow() - timedelta(seconds=120),
                    _or(
                        AgentRun.heartbeat_at.is_(None),
                        AgentRun.heartbeat_at < _p_utcnow() - timedelta(minutes=10),
                    ),
                )
                .all()
            )
            for row in candidates:
                if row.id in exclude:
                    continue
                protected.append(str(row.id))
                row.heartbeat_at = _p_utcnow()
            db.commit()
        return protected

    def _restore_dev_orphans(self, protected_ids) -> None:
        with SessionLocal() as db:
            for item in protected_ids:
                row = db.get(AgentRun, uuid.UUID(item))
                if row is not None:
                    row.heartbeat_at = None
            db.commit()

    def test_orphan_pending_run_is_reclaimed_and_relaunched(self):
        from datetime import timedelta

        from app.services.agent import executor as executor_module
        from app.services.agent.executor import relaunch_orphaned_pending_agent_runs

        orphan_id = self._make_run(status="pending")
        self._age_created_at(orphan_id)
        protected = self._protect_dev_orphans([orphan_id])
        self.addCleanup(self._restore_dev_orphans, protected)
        launched_ids: list[str] = []
        with mock.patch.object(
            executor_module, "launch_agent_run",
            side_effect=lambda run_id, actor_id=None: launched_ids.append(str(run_id)),
        ):
            with SessionLocal() as db:
                relaunched = relaunch_orphaned_pending_agent_runs(
                    db, stale_after=timedelta(minutes=10)
                )
        self.assertGreaterEqual(relaunched, 1)
        self.assertIn(orphan_id, launched_ids)
        with SessionLocal() as db:
            run = db.get(AgentRun, uuid.UUID(orphan_id))
            # CAS 抢占落 running + 刷新心跳；真实执行线程随 launch 接管
            self.assertEqual(run.status, "running")
            self.assertIsNotNone(run.heartbeat_at)

    def test_fresh_pending_run_is_left_alone(self):
        """刚创建的 pending run（线程尚未提交首次心跳的毫秒级窗口）不被误抢。"""
        from datetime import timedelta

        from app.services.agent import executor as executor_module
        from app.services.agent.executor import relaunch_orphaned_pending_agent_runs

        fresh_id = self._make_run(status="pending")
        protected = self._protect_dev_orphans([fresh_id])
        self.addCleanup(self._restore_dev_orphans, protected)
        launched_ids: list[str] = []
        with mock.patch.object(
            executor_module, "launch_agent_run",
            side_effect=lambda run_id, actor_id=None: launched_ids.append(str(run_id)),
        ):
            with SessionLocal() as db:
                relaunched = relaunch_orphaned_pending_agent_runs(
                    db, stale_after=timedelta(minutes=10)
                )
        self.assertNotIn(fresh_id, launched_ids)
        self.assertEqual(relaunched, 0)
        with SessionLocal() as db:
            self.assertEqual(
                db.get(AgentRun, uuid.UUID(fresh_id)).status, "pending"
            )

    def test_not_executable_orphan_lands_in_escalate(self):
        """重派后不可执行（数据集缺失等）落升级态，与创建端点同口径，不无限重试。"""
        from datetime import timedelta

        from app.services.agent import executor as executor_module
        from app.services.agent.executor import relaunch_orphaned_pending_agent_runs

        orphan_id = self._make_run(status="pending")
        self._age_created_at(orphan_id)
        protected = self._protect_dev_orphans([orphan_id])
        self.addCleanup(self._restore_dev_orphans, protected)
        with mock.patch.object(
            executor_module, "launch_agent_run",
            side_effect=AgentRunNotExecutable("dataset_artifact_id is required"),
        ):
            with SessionLocal() as db:
                relaunch_orphaned_pending_agent_runs(
                    db, stale_after=timedelta(minutes=10)
                )
        with SessionLocal() as db:
            run = db.get(AgentRun, uuid.UUID(orphan_id))
            self.assertEqual(run.status, "waiting_escalate")
            self.assertEqual(run.error_code, "AGENT_RUN_NOT_EXECUTABLE")
            self.assertIn("executor_error", run.result_json)


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
            return_value=("[]", {}, None),
        ), mock.patch(
            "app.services.agent.optimization_report.chat_completion",
            return_value=(_REPORT_REPLY, {}, None),
        ):
            execute_agent_run(run_id)
        self.assertTrue(captured)
        references = captured[0].get("experience_references") or []
        self.assertTrue(any("索引列" in str(ref.get("lesson")) for ref in references))

    def test_distill_creates_shadow_entries_with_evidence_chain(self):
        run_id = self._make_run()
        self._patch_llm()
        # A 批次：教训文本带 run_id 后缀——同文自动合并（§10.1）会把跨测试
        # 同文蒸馏折叠进既有条目（并可能被命中升级为 active），唯一文本
        # 保证本用例断言的是"新蒸馏条目从 shadow 起步"这一原始语义
        unique_reply = _DISTILL_REPLY.replace(
            '"lesson": "优先轻量模型"',
            f'"lesson": "优先轻量模型-{run_id[:8]}"',
        )
        with mock.patch(
            "app.services.agent.experience._distill_chat_completion",
            return_value=(unique_reply, {}, None),
        ), mock.patch(
            "app.services.agent.optimization_report.chat_completion",
            return_value=(_REPORT_REPLY, {}, None),
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
            return_value=(_DISTILL_REPLY, {}, None),
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
