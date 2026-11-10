"""闭环「智能体重训模式」回归：增量触发 / agent 重放全链 / 终态状态机。

覆盖（P1 定稿，DEVELOPMENT_PLAN §闭环智能体重训）：
- 增量边沿触发（engine 首触发行为与历史电平触发一致；换模推进基线后
  需新积累才再触发）；
- agent 触发闸门：配方未绑定/快照缺失 fail-closed、冷却静默跳过、
  24h 熔断（首触顶一次性事件+管理员通知）、部署级单飞；
- agent 重放创建：合并工件物化+自动标注、无人值守 guidance（剥暂停/
  关自动服务化）、LLM 档案沿用；
- refresh agent 分支：accepted→固化配方+铸造派发（白名单转发）、
  失败/升级→不换模不推基线、超时熔断；
- 换模终态：成功→基线推进+冷却+重放引用清理；门禁否决→不推进。
"""

import atexit
import os
import sys
import tempfile
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, ".")

# 本地直跑密封化（同 test_demo_loop）：未显式设置 DATABASE_URL 时指向
# 进程专属临时库，避免用例落共享开发库后残留行干扰计数断言
if not os.environ.get("DATABASE_URL"):
    _SEALED_DIR = Path("temp_test")
    _SEALED_DIR.mkdir(exist_ok=True)
    _SEALED_DB = _SEALED_DIR / f"agent-loop-retrain-{os.getpid()}-{uuid.uuid4().hex[:8]}.db"
    os.environ["DATABASE_URL"] = "sqlite:///" + _SEALED_DB.as_posix()

    def _cleanup_sealed_db():
        try:
            import app.database as _sealed_database

            _sealed_database.engine.dispose()
        except Exception:
            pass
        try:
            _SEALED_DB.unlink(missing_ok=True)
        except OSError:
            pass

    atexit.register(_cleanup_sealed_db)

from fastapi.testclient import TestClient  # noqa: E402

from app.config import settings  # noqa: E402
from app.database import Base, SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.api.auth import pwd_context  # noqa: E402
from app.models.agent_run import AgentRun  # noqa: E402
from app.models.demo_loop import DemoLoopConfig, DemoLoopEvent  # noqa: E402
from app.models.model_registry import InferenceDeployment, ModelVersion, RegisteredModel  # noqa: E402
from app.models.recipe import PipelineRecipe  # noqa: E402
from app.models.user import User  # noqa: E402
from app.services.agent.recipe import create_recipe  # noqa: E402
from app.services.demo_loop import DemoLoopService  # noqa: E402

Base.metadata.create_all(bind=engine)
client = TestClient(app)


def ensure_admin():
    db = SessionLocal()
    try:
        if db.query(User).filter(User.username == "admin").first() is None:
            db.add(User(
                username="admin",
                password_hash=pwd_context.hash("admin123"),
                role="admin",
            ))
            db.commit()
    finally:
        db.close()


def login(username="admin", password="admin123"):
    r = client.post("/api/auth/login", data={"username": username, "password": password})
    return {"Authorization": "Bearer " + r.json()["access_token"]}


_RETRAIN_GUIDANCE = {
    "modeling": {
        "algorithm_whitelist": ["logistic"],
        "ensemble": {"enabled": False, "top_k": 3},
    },
    "evaluation": {"metric_gates": {"recall_minority": 0.5}},
    "auto_servitize": True,
}


def _recipe_content(**overrides):
    content = {
        "domain": "test-domain",
        "inputs": {"target_column": "label"},
        "feature_script": "def transform(rows):\n    return rows\n",
        "acceptance_gates": {"recall_minority": 0.5},
        "retrain_ensemble": {"enabled": False},
        "retrain_algorithm_ids": ["logistic"],
        "guidance": dict(_RETRAIN_GUIDANCE),
        "source_run_id": str(uuid.uuid4()),
    }
    content.update(overrides)
    return content


class _FakeVersion:
    def __init__(self):
        self.id = uuid.uuid4()
        self.version_number = 7


class _StubDispatcher:
    def __init__(self):
        self.enqueued = []
        self.started = []

    def enqueue(self, job_id):
        self.enqueued.append(str(job_id))
        return f"local:stub-{len(self.enqueued)}"

    def start(self, task_id):
        self.started.append(task_id)


class AgentLoopRetrain(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        ensure_admin()
        cls.h = login()
        db = SessionLocal()
        try:
            cls.user_id = db.query(User).filter(User.username == "admin").one().id
        finally:
            db.close()
        r = client.post("/api/projects", json={
            "name": f"agent-retrain-{uuid.uuid4().hex[:8]}",
            "description": "closed-loop agent retrain tests",
        }, headers=cls.h)
        assert r.status_code == 201, r.text
        cls.project_id = r.json()["id"]
        db = SessionLocal()
        try:
            import joblib
            import pandas as pd
            from sklearn.linear_model import LogisticRegression

            from app.services.artifact_service import build_artifact_service

            frame = pd.DataFrame({
                "f1": [0.0, 0.2, 0.1, 0.3, 0.15, 5.0, 5.4, 4.8, 5.2, 5.1],
                "f2": [1.0, 1.2, 0.9, 1.1, 1.05, -1.0, -1.2, -0.9, -1.1, -1.0],
            })
            model = LogisticRegression().fit(frame, [0, 0, 0, 0, 0, 1, 1, 1, 1, 1])
            service = build_artifact_service(db)
            with tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / "toy_model.joblib"
                joblib.dump(model, path)
                artifact = service.create_from_file(
                    uuid.UUID(cls.project_id), path, f"toy-model-{uuid.uuid4().hex[:6]}",
                    "model", metadata={"source": "test"},
                )
            registered = RegisteredModel(
                project_id=uuid.UUID(cls.project_id),
                name=f"toy-model-{uuid.uuid4().hex[:6]}",
                created_by_id=cls.user_id,
            )
            db.add(registered)
            db.flush()
            version = ModelVersion(
                registered_model_id=registered.id,
                version_number=1,
                source_kind="onnx_artifact",
                source_artifact_id=artifact.id,
                onnx_artifact_id=artifact.id,
                framework="sklearn",
                feature_schema=["f1", "f2"],
                lifecycle_state="enabled",
                approval_status="approved",
                output_schema={"target_columns": ["label"]},
            )
            db.add(version)
            db.flush()
            deployment = InferenceDeployment(
                project_id=uuid.UUID(cls.project_id),
                name=f"toy-deploy-{uuid.uuid4().hex[:6]}",
                model_version_id=version.id,
                desired_state="running",
                observed_state="running",
                created_by_id=cls.user_id,
            )
            db.add(deployment)
            db.commit()
            cls.deployment_id = str(deployment.id)
        finally:
            db.close()

    def setUp(self):
        """项目级测试隔离：清掉上一用例遗留的 agent_running 占位——项目
        并发闸门（默认 2）会把同项目遗留的 in-flight 配置算进 busy，导致
        后续触发被静默跳过（行为正确，测试需显式清场）。"""
        db = SessionLocal()
        try:
            db.query(DemoLoopConfig).filter(
                DemoLoopConfig.project_id == uuid.UUID(self.project_id),
            ).update({
                DemoLoopConfig.retrain_status: "idle",
                DemoLoopConfig.retrain_agent_run_id: None,
                DemoLoopConfig.retrain_agent_started_at: None,
            }, synchronize_session=False)
            db.commit()
        finally:
            db.close()

    # ---------------------------------------------------------------- helpers

    def _db(self):
        return SessionLocal()

    def _create_config(self, db, **overrides):
        fields = dict(
            alert_threshold_rows=100,
            retrain_enabled=True,
            retrain_threshold_rows=1,
            retrain_target_column="label",
        )
        fields.update(overrides)
        config = DemoLoopConfig(
            project_id=uuid.UUID(self.project_id),
            deployment_id=uuid.UUID(self.deployment_id),
            name=f"闭环-{uuid.uuid4().hex[:6]}",
            error_classes=["1"],
            **fields,
        )
        db.add(config)
        db.commit()
        db.refresh(config)
        return config

    def _create_recipe(self, db, content=None):
        return create_recipe(
            db,
            project_id=uuid.UUID(self.project_id),
            name=f"recipe-{uuid.uuid4().hex[:6]}",
            content=content or _recipe_content(),
            created_by=self.user_id,
        )

    def _error_dataset(self, db, lines):
        """lines：现成 CSV 文本行（首行表头）。"""
        from app.services.artifact_service import build_artifact_service

        service = build_artifact_service(db)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "retrain-src.csv"
            path.write_text("\n".join(lines) + "\n", encoding="utf-8")
            artifact = service.create_from_file(
                uuid.UUID(self.project_id), path, f"retrain-src-{uuid.uuid4().hex[:6]}",
                "dataset", metadata={"row_count": len(lines) - 1},
            )
        return artifact

    def _predict_error(self, config_name_hint=None):
        """走 API 回流一行报错（命中 error_classes=1）。"""
        r = client.post(
            f"/api/projects/{self.project_id}/demo-loop/predict",
            json={"record": {"f1": 5.4, "f2": -1.2, "label": ""}},
            headers=self.h,
        )
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()

    def _events(self, db, config):
        return [
            event.event_type
            for event in db.query(DemoLoopEvent)
            .filter(DemoLoopEvent.config_id == config.id)
            .order_by(DemoLoopEvent.created_at.asc(), DemoLoopEvent.id.asc())
            .all()
        ]

    def _insert_trigger_events(self, db, config, count):
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        for index in range(count):
            db.add(DemoLoopEvent(
                config_id=config.id,
                event_type="retrain_agent_triggered",
                severity="warning",
                message="seed",
                created_at=now - timedelta(hours=1),
            ))
        db.commit()

    # ------------------------------------------------------------------ tests

    def test_01_engine_first_trigger_unchanged(self):
        """引擎模式默认行为不变：增量基线 0 时首触发与历史电平触发一致。"""
        db = self._db()
        try:
            dataset = self._error_dataset(db, [("f1,f2,label"), ("1.0,2.0,0")])
            config = self._create_config(
                db,
                retrain_threshold_rows=3,
                retrain_dataset_artifact_id=dataset.id,
            )
            service = DemoLoopService(db)
            stub = _StubDispatcher()
            with patch("app.services.experiment_tracking.resolve_tracking_configuration",
                       return_value=("sqlite:///./temp_test/ut_mlflow_tracking.db",
                                     "file:./temp_test/ut_mlflow_artifacts")), \
                    patch("app.services.closed_loop_actions.automl_dispatcher", return_value=stub):
                for _ in range(3):
                    service.predict(config, {"f1": 5.4, "f2": -1.2, "label": ""}, self.user_id)
            db.refresh(config)
            self.assertEqual(config.retrain_status, "queued")
            self.assertIsNotNone(config.retrain_job_id)
            self.assertEqual(int(config.retrain_trained_baseline_count or 0), 0)
            self.assertIn("retrain_triggered", self._events(db, config))
        finally:
            db.close()

    def test_01b_engine_trigger_forwards_input_columns(self):
        """重训特征列白名单转发：配置列随 job.params.input_columns 下发（稀疏宽表）。"""
        from app.models.training import TrainingJob

        db = self._db()
        try:
            dataset = self._error_dataset(db, [("f1,f2,label"), ("1.0,2.0,0")])
            config = self._create_config(
                db,
                retrain_threshold_rows=1,
                retrain_dataset_artifact_id=dataset.id,
                retrain_input_columns=["f1", "f2"],
            )
            service = DemoLoopService(db)
            stub = _StubDispatcher()
            with patch("app.services.experiment_tracking.resolve_tracking_configuration",
                       return_value=("sqlite:///./temp_test/ut_mlflow_tracking.db",
                                     "file:./temp_test/ut_mlflow_artifacts")), \
                    patch("app.services.closed_loop_actions.automl_dispatcher", return_value=stub):
                service.predict(config, {"f1": 5.4, "f2": -1.2, "label": ""}, self.user_id)
            db.refresh(config)
            job = db.get(TrainingJob, config.retrain_job_id)
            self.assertIsNotNone(job)
            self.assertEqual(job.params["input_columns"], ["f1", "f2"])
        finally:
            db.close()

    def test_02_agent_trigger_requires_bound_recipe(self):
        """agent 模式未绑定配方：fail-closed 事件，不创建重放。"""
        db = self._db()
        try:
            config = self._create_config(db, retrain_mode="agent")
            service = DemoLoopService(db)
            service.predict(config, {"f1": 5.4, "f2": -1.2, "label": ""}, self.user_id)
            db.refresh(config)
            self.assertEqual(config.retrain_status, "idle")
            self.assertIsNone(config.retrain_agent_run_id)
            types = self._events(db, config)
            self.assertIn("retrain_failed", types)
        finally:
            db.close()

    def test_03_agent_trigger_creates_replay_run(self):
        """agent 触发：合并工件物化（含自动标注）+ 无人值守 guidance + 源档案沿用。"""
        db = self._db()
        try:
            recipe = self._create_recipe(db)
            source_run = AgentRun(
                project_id=uuid.UUID(self.project_id),
                target_column="label",
                status="accepted",
                guidance_json=dict(_RETRAIN_GUIDANCE),
                created_by=self.user_id,
            )
            db.add(source_run)
            db.flush()
            content = _recipe_content(source_run_id=str(source_run.id))
            from app.services.agent.recipe import update_recipe

            update_recipe(db, recipe.id, content=content, change_note="bind source run")
            dataset = self._error_dataset(db, [("f1,f2,label"), ("1.0,2.0,0")])
            config = self._create_config(
                db,
                retrain_mode="agent",
                retrain_agent_recipe_id=recipe.id,
                retrain_dataset_artifact_id=dataset.id,
            )
            service = DemoLoopService(db)
            with patch("app.services.agent.executor.launch_agent_run") as launch:
                service.predict(config, {"f1": 5.4, "f2": -1.2, "label": ""}, self.user_id)
            db.refresh(config)
            self.assertEqual(config.retrain_status, "agent_running")
            self.assertIsNotNone(config.retrain_agent_run_id)
            launch.assert_called_once()
            run = db.get(AgentRun, config.retrain_agent_run_id)
            self.assertIsNotNone(run)
            self.assertEqual(run.status, "pending")
            self.assertEqual(run.target_column, "label")
            # 无人值守：逐步暂停剥离、自动服务化关闭
            self.assertNotIn("pause_at_stages", run.guidance_json or {})
            self.assertFalse((run.guidance_json or {}).get("auto_servitize", False))
            # LLM 档案/预算沿用源 run
            self.assertEqual(run.llm_profile_id, source_run.llm_profile_id)
            self.assertIn("retrain_agent_triggered", self._events(db, config))
        finally:
            db.close()

    def test_04_single_flight_blocks_second_trigger(self):
        """部署级单飞：重放在途时后续触发被阻塞（不排队不重建）。"""
        db = self._db()
        try:
            recipe = self._create_recipe(db)
            dataset = self._error_dataset(db, [("f1,f2,label"), ("1.0,2.0,0")])
            config = self._create_config(
                db,
                retrain_mode="agent",
                retrain_agent_recipe_id=recipe.id,
                retrain_dataset_artifact_id=dataset.id,
            )
            service = DemoLoopService(db)
            with patch("app.services.agent.executor.launch_agent_run"):
                service.predict(config, {"f1": 5.4, "f2": -1.2, "label": ""}, self.user_id)
            db.refresh(config)
            self.assertEqual(config.retrain_status, "agent_running")
            first_run_id = config.retrain_agent_run_id
            service.predict(config, {"f1": 5.5, "f2": -1.3, "label": ""}, self.user_id)
            db.refresh(config)
            self.assertEqual(config.retrain_agent_run_id, first_run_id)
            db.refresh(config)
        finally:
            db.close()

    def test_05_cooldown_silently_skips(self):
        """冷却期内：静默跳过（无事件、无重放）。"""
        db = self._db()
        try:
            recipe = self._create_recipe(db)
            dataset = self._error_dataset(db, [("f1,f2,label"), ("1.0,2.0,0")])
            config = self._create_config(
                db,
                retrain_mode="agent",
                retrain_agent_recipe_id=recipe.id,
                retrain_dataset_artifact_id=dataset.id,
                retrain_cool_until=datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(minutes=30),
            )
            service = DemoLoopService(db)
            with patch("app.services.agent.executor.launch_agent_run") as launch:
                service.predict(config, {"f1": 5.4, "f2": -1.2, "label": ""}, self.user_id)
            db.refresh(config)
            self.assertIsNone(config.retrain_agent_run_id)
            launch.assert_not_called()
            self.assertNotIn("retrain_agent_triggered", self._events(db, config))
        finally:
            db.close()

    def test_06_circuit_breaker_stops_and_notifies(self):
        """24h 熔断：第 limit+1 次评估触发一次性 critical 事件+管理员通知。"""
        db = self._db()
        try:
            recipe = self._create_recipe(db)
            dataset = self._error_dataset(db, [("f1,f2,label"), ("1.0,2.0,0")])
            config = self._create_config(
                db,
                retrain_mode="agent",
                retrain_agent_recipe_id=recipe.id,
                retrain_dataset_artifact_id=dataset.id,
            )
            limit = int(settings.agent_retrain_daily_limit)
            self._insert_trigger_events(db, config, limit)
            service = DemoLoopService(db)
            with patch("app.services.agent.executor.launch_agent_run") as launch:
                service.predict(config, {"f1": 5.4, "f2": -1.2, "label": ""}, self.user_id)
            db.refresh(config)
            self.assertIsNone(config.retrain_agent_run_id)
            launch.assert_not_called()
            self.assertIn("retrain_agent_circuit_break", self._events(db, config))
            # 再次回流：静默（不重复熔断事件）
            service.predict(config, {"f1": 5.5, "f2": -1.3, "label": ""}, self.user_id)
            breaks = [
                event for event in self._events(db, config)
                if event == "retrain_agent_circuit_break"
            ]
            self.assertEqual(len(breaks), 1)
        finally:
            db.close()

    def test_07_poll_accept_fixates_recipe_and_dispatches_casting(self):
        """accepted → 固化新配方 + 铸造派发（白名单/集成转发），状态机交还引擎。"""
        db = self._db()
        try:
            recipe = self._create_recipe(db)
            run = AgentRun(
                project_id=uuid.UUID(self.project_id),
                dataset_artifact_id=uuid.uuid4(),
                target_column="label",
                status="accepted",
                round_count=2,
                guidance_json=dict(_RETRAIN_GUIDANCE),
                created_by=self.user_id,
            )
            db.add(run)
            db.flush()
            config = self._create_config(
                db,
                retrain_mode="agent",
                retrain_agent_recipe_id=recipe.id,
                retrain_agent_run_id=run.id,
                retrain_agent_started_at=datetime.now(timezone.utc).replace(tzinfo=None),
                retrain_status="agent_running",
            )

            captured = {}

            def _fake_trigger(db_, **kwargs):
                captured.update(kwargs)
                job = type("Job", (), {"id": uuid.uuid4(), "params": {"max_trials": kwargs.get("max_trials")}})()
                return job

            service = DemoLoopService(db)
            with patch("app.services.closed_loop_actions.trigger_retrain_job", side_effect=_fake_trigger):
                handled = service.refresh_retrain_status(config, self.user_id)
            self.assertTrue(handled is None)  # refresh 无返回值；断言状态迁移
            db.refresh(config)
            self.assertEqual(config.retrain_status, "queued")
            self.assertIsNotNone(config.retrain_job_id)
            db.refresh(run)
            self.assertTrue((run.result_json or {}).get("fixated_recipe_id"))
            self.assertIn("retrain_agent_accepted", self._events(db, config))
            self.assertIn("retrain_casting_started", self._events(db, config))
            # D5：配方白名单随铸造下发
            self.assertEqual(captured.get("algorithm_ids"), ["logistic"])
            self.assertEqual(captured.get("dataset_artifact_ids"), [str(run.dataset_artifact_id)])
        finally:
            db.close()

    def test_08_poll_failure_keeps_old_model(self):
        """重放失败/升级：不换模不推基线，清重放引用 + 冷却。"""
        db = self._db()
        try:
            for status, expected_event in [
                ("waiting_escalate", "retrain_agent_rejected"),
                ("failed", "retrain_agent_failed"),
            ]:
                recipe = self._create_recipe(db)
                run = AgentRun(
                    project_id=uuid.UUID(self.project_id),
                    target_column="label",
                    status=status,
                    error_code="AGENT_S4_CONTRACT_FAILED",
                    guidance_json=dict(_RETRAIN_GUIDANCE),
                    created_by=self.user_id,
                )
                db.add(run)
                db.flush()
                config = self._create_config(
                    db,
                    retrain_mode="agent",
                    retrain_agent_recipe_id=recipe.id,
                    retrain_agent_run_id=run.id,
                    retrain_agent_started_at=datetime.now(timezone.utc).replace(tzinfo=None),
                    retrain_status="agent_running",
                    error_count=50,
                )
                service = DemoLoopService(db)
                service.refresh_retrain_status(config, self.user_id)
                db.refresh(config)
                self.assertEqual(config.retrain_status, "failed")
                self.assertIsNone(config.retrain_agent_run_id)
                self.assertIsNotNone(config.retrain_cool_until)
                self.assertEqual(int(config.retrain_trained_baseline_count or 0), 0)
                self.assertIn(expected_event, self._events(db, config))
        finally:
            db.close()

    def test_09_poll_timeout(self):
        """重放超过轮询上限：按失败处理，任务留档。"""
        db = self._db()
        try:
            recipe = self._create_recipe(db)
            run = AgentRun(
                project_id=uuid.UUID(self.project_id),
                target_column="label",
                status="running",
                guidance_json=dict(_RETRAIN_GUIDANCE),
                created_by=self.user_id,
            )
            db.add(run)
            db.flush()
            config = self._create_config(
                db,
                retrain_mode="agent",
                retrain_agent_recipe_id=recipe.id,
                retrain_agent_run_id=run.id,
                retrain_agent_started_at=(
                    datetime.now(timezone.utc).replace(tzinfo=None)
                    - timedelta(seconds=int(settings.agent_retrain_poll_max_age_seconds) + 60)
                ),
                retrain_status="agent_running",
            )
            service = DemoLoopService(db)
            service.refresh_retrain_status(config, self.user_id)
            db.refresh(config)
            self.assertEqual(config.retrain_status, "failed")
            self.assertIsNone(config.retrain_agent_run_id)
            self.assertIn("retrain_agent_timeout", self._events(db, config))
        finally:
            db.close()

    def test_10_swap_advances_baseline_and_cooldown(self):
        """换模成功：基线推进到当期 error_count + 冷却 + 重放引用清理。"""
        db = self._db()
        try:
            recipe = self._create_recipe(db)
            run = AgentRun(
                project_id=uuid.UUID(self.project_id),
                target_column="label",
                status="accepted",
                result_json={"fixated_recipe_id": str(recipe.id)},
                guidance_json=dict(_RETRAIN_GUIDANCE),
                created_by=self.user_id,
            )
            db.add(run)
            db.flush()
            config = self._create_config(
                db,
                retrain_mode="agent",
                retrain_agent_recipe_id=recipe.id,
                retrain_agent_run_id=run.id,
                retrain_status="queued",
                error_count=900,
            )
            job = type("Job", (), {"id": uuid.uuid4()})()
            with patch("app.services.demo_loop.complete_retrain_swap", return_value=_FakeVersion()) as swap:
                service = DemoLoopService(db)
                service._swap_to_best_model(config, job, self.user_id)
            swap.assert_called_once()
            # 换模传本轮固化配方：配方门禁兜底（引擎候选已补 recall_minority
            # 输出，键与轻量口径对齐，不再 missing-veto 死锁）。
            self.assertEqual(
                swap.call_args.kwargs.get("recipe_id"), str(recipe.id))
            db.commit()
            db.refresh(config)
            self.assertEqual(int(config.retrain_trained_baseline_count), 900)
            self.assertIsNone(config.retrain_agent_run_id)
            self.assertIsNotNone(config.retrain_cool_until)
            self.assertIn("model_swapped", self._events(db, config))
        finally:
            db.close()

    def test_11_gate_veto_keeps_signal(self):
        """门禁否决（无合格候选）：不换模不推基线，轮次终态清理引用。"""
        db = self._db()
        try:
            config = self._create_config(
                db,
                retrain_mode="agent",
                error_count=900,
            )
            job = type("Job", (), {"id": uuid.uuid4()})()
            with patch("app.services.demo_loop.complete_retrain_swap", return_value=None):
                service = DemoLoopService(db)
                service._swap_to_best_model(config, job, self.user_id)
            db.commit()
            db.refresh(config)
            self.assertEqual(int(config.retrain_trained_baseline_count), 0)
            self.assertIsNone(config.retrain_agent_run_id)
            self.assertIn("retrain_failed", self._events(db, config))
        finally:
            db.close()

    def test_12_catchup_uses_full_accumulation(self):
        """追赶语义：部署完成后按全量积累评估（900-20 >= 20 → 立即新一轮）。"""
        db = self._db()
        try:
            recipe = self._create_recipe(db)
            dataset = self._error_dataset(db, [("f1,f2,label"), ("1.0,2.0,0")])
            config = self._create_config(
                db,
                retrain_mode="agent",
                retrain_agent_recipe_id=recipe.id,
                retrain_dataset_artifact_id=dataset.id,
                error_count=900,
                retrain_trained_baseline_count=20,
                retrain_status="idle",
            )
            service = DemoLoopService(db)
            with patch("app.services.agent.executor.launch_agent_run"):
                service.refresh_retrain_status(config, self.user_id)
            db.refresh(config)
            self.assertEqual(config.retrain_status, "agent_running")
            self.assertIsNotNone(config.retrain_agent_run_id)
        finally:
            db.close()

    def test_13_catchup_not_triggered_without_new_errors(self):
        """报错已停：换模后 error_count-baseline=0 < 阈值 → 不再触发（恰一次追赶）。"""
        db = self._db()
        try:
            recipe = self._create_recipe(db)
            dataset = self._error_dataset(db, [("f1,f2,label"), ("1.0,2.0,0")])
            config = self._create_config(
                db,
                retrain_mode="agent",
                retrain_agent_recipe_id=recipe.id,
                retrain_dataset_artifact_id=dataset.id,
                error_count=900,
                retrain_trained_baseline_count=900,
                retrain_status="idle",
            )
            service = DemoLoopService(db)
            with patch("app.services.agent.executor.launch_agent_run") as launch:
                service.refresh_retrain_status(config, self.user_id)
            db.refresh(config)
            self.assertIsNone(config.retrain_agent_run_id)
            launch.assert_not_called()
        finally:
            db.close()

    def test_13b_catchup_respects_disabled_or_zero_threshold(self):
        """状态轮询的追赶评估同样受「启用+阈值>0」守卫：阈值 0（界面语义=
        关闭）或未启用时绝不触发——曾因 5-0<0 不成立被大屏每次轮询触发。"""
        db = self._db()
        try:
            recipe = self._create_recipe(db)
            dataset = self._error_dataset(db, [("f1,f2,label"), ("1.0,2.0,0")])
            for overrides in ({"retrain_threshold_rows": 0}, {"retrain_enabled": False}):
                config = self._create_config(
                    db,
                    retrain_mode="agent",
                    retrain_agent_recipe_id=recipe.id,
                    retrain_dataset_artifact_id=dataset.id,
                    error_count=5,
                    retrain_status="idle",
                    **overrides,
                )
                service = DemoLoopService(db)
                with patch("app.services.agent.executor.launch_agent_run") as launch:
                    service.refresh_retrain_status(config, self.user_id)
                db.refresh(config)
                self.assertIsNone(config.retrain_agent_run_id, overrides)
                self.assertEqual(config.retrain_status, "idle", overrides)
                launch.assert_not_called()
        finally:
            db.close()

    def test_14_mode_config_validation(self):
        """API 校验：retrain_mode 枚举、agent 需绑定配方、外来配方拒绝。"""
        headers = self.h
        r = client.post(f"/api/projects/{self.project_id}/demo-loop/loops", json={
            "name": f"闭环模式校验-{uuid.uuid4().hex[:4]}",
            "deployment_id": self.deployment_id,
            "error_classes": ["1"],
            "retrain_mode": "bogus",
        }, headers=headers)
        self.assertEqual(r.status_code, 422, r.text)
        db = self._db()
        try:
            # 外来配方：配方属于其他项目 → 本项目创建 agent 模式闭环拒绝
            other_project = client.post("/api/projects", json={
                "name": f"agent-retrain-other-{uuid.uuid4().hex[:6]}",
            }, headers=headers).json()["id"]
            foreign = create_recipe(
                db,
                project_id=uuid.UUID(other_project),
                name=f"foreign-{uuid.uuid4().hex[:6]}",
                content=_recipe_content(),
                created_by=self.user_id,
            )
            r = client.post(f"/api/projects/{self.project_id}/demo-loop/loops", json={
                "name": f"外来配方-{uuid.uuid4().hex[:4]}",
                "deployment_id": self.deployment_id,
                "error_classes": ["1"],
                "retrain_mode": "agent",
                "retrain_agent_recipe_id": str(foreign.id),
            }, headers=headers)
            self.assertEqual(r.status_code, 422, r.text)
            self.assertIn("不属于本项目", r.text)
            # 正向：本项目配方可直接新建 agent 模式闭环（新行 retrain_status
            # 尚为 None，曾被误判「重训进行中不允许切换模式」恒 422）
            own = self._create_recipe(db)
            r = client.post(f"/api/projects/{self.project_id}/demo-loop/loops", json={
                "name": f"本项目配方-{uuid.uuid4().hex[:4]}",
                "deployment_id": self.deployment_id,
                "error_classes": ["1"],
                "retrain_mode": "agent",
                "retrain_agent_recipe_id": str(own.id),
            }, headers=headers)
            self.assertEqual(r.status_code, 201, r.text)
            self.assertEqual(r.json().get("retrain_mode"), "agent")
        finally:
            db.close()


    def test_15_fixation_target_semantics_enables_servitize_draft(self):
        """target_semantics 生产方：固化 content 带目标列取值，servitize 推导
        不再「cannot derive error classes」降级。无语义描述时兜底取少数类
        （target_values 按频次升序，首个=少数类）+ 全量 ambiguous——此前取
        字典序最小，点焊 fault（1=缺陷/0=正常）会把正常焊点全判报错回流。"""
        import pandas as pd

        from app.services.agent.recipe import build_fixation_content
        from app.services.agent.servitize import derive_error_classes

        class _Run:
            id = uuid.uuid4()
            target_column = "fault"
            guidance_json = {"evaluation": {"metric_gates": {"recall_minority": 0.9}}}
            result_json = {}

        content = build_fixation_content(
            _Run(), {}, target_values=[1, 0],
            smoke_row={"f1": 1.0},
        )
        self.assertEqual(content["target_semantics"], {"1": "", "0": ""})
        self.assertEqual(content["minority_label"], "1")
        error_classes, ambiguous = derive_error_classes(
            content["target_semantics"], content["minority_label"])
        # 无语义描述 → 少数类兜底为报错类；ambiguous 保持全量（发布批准时人工核对）
        self.assertEqual(error_classes, ["1"])
        self.assertEqual(ambiguous, ["1", "0"])
        # 旧配方无 minority_label：退回字典序最小（行为不变）
        self.assertEqual(derive_error_classes(content["target_semantics"])[0], ["0"])


if __name__ == "__main__":
    unittest.main()
