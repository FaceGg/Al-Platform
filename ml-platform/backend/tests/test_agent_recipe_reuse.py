"""配方 agent_trace 沉淀 + 一键复用端点回归（2026-11-18 用户需求）。

覆盖：
- build_fixation_content 固化时沉淀 agent_trace（S1 思考/注入经验/轮次决策链，
  有界截断）；
- POST /api/agent/recipes/{id}/reuse：guidance 快照+用户修改项深合并 → 新任务
  携 recipe_trace 启动；范式镜像互斥；快照缺失 fail-closed。
"""

import atexit
import os
import sys
import tempfile
import unittest
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, ".")

# 本地直跑密封化：未显式设置 DATABASE_URL 时指向进程专属临时库
if not os.environ.get("DATABASE_URL"):
    _SEALED_DIR = Path("temp_test")
    _SEALED_DIR.mkdir(exist_ok=True)
    _SEALED_DB = _SEALED_DIR / f"agent-recipe-reuse-{os.getpid()}-{uuid.uuid4().hex[:8]}.db"
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

os.environ.setdefault("LLM_MASTER_KEY", __import__(
    "cryptography.fernet", fromlist=["Fernet"]
).Fernet.generate_key().decode("ascii"))

from fastapi.testclient import TestClient  # noqa: E402

from app.database import Base, SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.api.auth import pwd_context  # noqa: E402
from app.models.recipe import PipelineRecipe  # noqa: E402
from app.models.user import User  # noqa: E402
from app.services.agent.recipe import (  # noqa: E402
    build_fixation_content,
    create_recipe,
    get_current_version,
)

Base.metadata.create_all(bind=engine)
client = TestClient(app)


def _ensure_admin():
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


def _login():
    r = client.post("/api/auth/login", data={"username": "admin", "password": "admin123"})
    return {"Authorization": "Bearer " + r.json()["access_token"]}


_FAKE_RUN = SimpleNamespace(
    id=uuid.uuid4(),
    target_column="label",
    status="accepted",
    guidance_json={
        "task_type": "supervised",
        "modeling": {
            "algorithm_whitelist": ["lightgbm"],
            "param_hints": {},
            "ensemble": {"enabled": True, "top_k": 3},
        },
        "evaluation": {"metric_gates": {"recall_minority": 0.9}},
    },
    result_json={"metrics": {"recall_minority": 0.93}},
)

_FAKE_MEMORY = {
    "rounds": [
        {
            "round": 1,
            "s1": {
                "domain": "tightening",
                "reasoning": "扭矩偏差主导，索引列疑似泄漏，建议剔除",
                "brief": "拧紧质量域，二分类",
            },
            "s2": {
                "description": "剔除索引列并加偏差特征",
                "generated_columns": ["torque_dev"],
                "dropped_columns": ["index"],
            },
            "s3": {"metrics": {"recall_minority": 0.88}, "ensemble": {"adopted": True}},
            "s4": {"gate_passed": False, "gate_failures": ["recall_minority 0.88 < 0.9"]},
            "review": {"verdict": "fail", "surprises": ["召回略低"], "hints": ["提高迭代"]},
            "hints": ["提高迭代"],
        },
        {
            "round": 2,
            "s2": {"description": "保留偏差特征并放宽截断", "generated_columns": [], "dropped_columns": []},
            "s3": {"metrics": {"recall_minority": 0.94}, "ensemble": {"adopted": False}},
            "s4": {"gate_passed": True},
            "review": {"verdict": "pass"},
        },
    ],
    "injected_experience": [
        {"lesson": "索引列默认剔除", "action": "S2 drop", "confidence": 0.9},
    ],
}


class TestFixationAgentTrace(unittest.TestCase):
    """固化内容必须携带大模型思考/决策链（复用建模的推理指引）。"""

    def test_agent_trace_captures_reasoning_and_rounds(self):
        content = build_fixation_content(_FAKE_RUN, _FAKE_MEMORY)
        trace = content.get("agent_trace")
        self.assertIsInstance(trace, dict)
        self.assertIn("扭矩偏差主导", trace["s1_reasoning"])
        self.assertIn("拧紧质量域", trace["s1_brief"])
        self.assertEqual(len(trace["rounds"]), 2)
        first = trace["rounds"][0]
        self.assertEqual(first["review_verdict"], "fail")
        self.assertIn("recall_minority 0.88 < 0.9", first["s4_gate_failures"][0])
        self.assertTrue(first["ensemble_adopted"])
        self.assertIn("torque_dev", first["generated_columns"])
        # 注入经验随配方沉淀（复用即继承经验上下文）
        self.assertEqual(trace["injected_experience"][0]["lesson"], "索引列默认剔除")

    def test_agent_trace_bounded_on_noise(self):
        """畸形/超长档案不炸固化：全部字段有界，噪声条目被丢弃。"""
        noisy_memory = {
            "rounds": [
                {
                    "round": i + 1,
                    "s1": {"reasoning": "思" * 5000},
                    "s2": {"description": "描" * 2000},
                    "s3": {"metrics": {f"f{k}": 0.1 for k in range(40)}},
                    "s4": {"gate_failures": ["x" * 500] * 10},
                    "review": {"verdict": "fail" * 100, "surprises": None},
                    "hints": ["h" * 1000] * 10,
                }
                for i in range(15)
            ],
            "injected_experience": [{"lesson": "l" * 1000}] * 20,
        }
        content = build_fixation_content(_FAKE_RUN, noisy_memory)
        trace = content["agent_trace"]
        self.assertLessEqual(len(trace["rounds"]), 10)
        self.assertLessEqual(len(trace["s1_reasoning"]), 2000)
        self.assertLessEqual(len(trace["injected_experience"]), 10)
        self.assertLessEqual(len(trace["rounds"][0]["s4_gate_failures"]), 6)


class TestRecipeReuseAPI(unittest.TestCase):
    """一键复用：快照+修改项 → 新任务并启动。"""

    @classmethod
    def setUpClass(cls):
        _ensure_admin()
        cls.h = _login()
        db = SessionLocal()
        try:
            from app.models.project import Project
            from app.services.artifact_service import build_artifact_service

            admin = db.query(User).filter(User.username == "admin").one()
            project = Project(name="reuse-%s" % uuid.uuid4().hex[:8], owner_id=admin.id)
            db.add(project)
            db.flush()
            cls.project_id = project.id
            service = build_artifact_service(db)
            with tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / "reuse-src.csv"
                path.write_text("f1,f2,label\n1.0,2.0,0\n", encoding="utf-8")
                artifact = service.create_from_file(
                    cls.project_id, path, f"reuse-src-{uuid.uuid4().hex[:6]}",
                    "dataset", metadata={"row_count": 1},
                )
            cls.artifact_id = artifact.id
            snapshot = {
                "task_type": "supervised",
                "max_rounds": 3,
                "modeling": {
                    "algorithm_whitelist": ["lightgbm"],
                    "ensemble": {"enabled": False, "top_k": 3},
                },
                "evaluation": {"metric_gates": {"recall_minority": 0.9}},
            }
            content = {
                "domain": "tightening",
                "inputs": {"target_column": "label"},
                "feature_script": "def transform(rows):\n    return rows\n",
                "acceptance_gates": {"recall_minority": 0.9},
                "guidance": snapshot,
                "agent_trace": {
                    "s1_reasoning": "扭矩偏差主导",
                    "s1_brief": "拧紧质量域",
                    "injected_experience": [],
                    "rounds": [],
                },
                "source_run_id": str(uuid.uuid4()),
            }
            recipe = create_recipe(
                db,
                project_id=cls.project_id,
                name="reuse-test-" + uuid.uuid4().hex[:6],
                content=content,
            )
            cls.recipe_id = recipe.id
            # 缺快照的存量配方（fail-closed 路径）
            legacy = create_recipe(
                db,
                project_id=cls.project_id,
                name="legacy-" + uuid.uuid4().hex[:6],
                content={"domain": "x", "feature_script": ""},
            )
            cls.legacy_recipe_id = legacy.id
            cls.no_target_recipe_id = None
            cls.anomaly_recipe_id = None
        finally:
            db.close()

    def test_reuse_creates_run_with_merged_guidance_and_trace(self):
        with patch("app.services.agent.executor.launch_agent_run") as launch:
            r = client.post(
                f"/api/agent/recipes/{self.recipe_id}/reuse",
                json={
                    "dataset_artifact_id": str(self.artifact_id),
                    "guidance_overrides": {
                        "max_rounds": 5,
                        "modeling": {"ensemble": {"enabled": True, "top_k": 4}},
                    },
                },
                headers=self.h,
            )
        self.assertEqual(r.status_code, 201, r.text)
        body = r.json()
        self.assertEqual(body["target_column"], "label")
        launch.assert_called_once()
        db = SessionLocal()
        try:
            from app.models.agent_run import AgentRun

            run = db.get(AgentRun, uuid.UUID(body["run_id"]))
            self.assertIsNotNone(run)
            guidance = run.guidance_json or {}
            # 修改项覆盖快照：其余字段沿用配方
            self.assertEqual(guidance.get("max_rounds"), 5)
            self.assertTrue(guidance["modeling"]["ensemble"]["enabled"])
            self.assertEqual(guidance["modeling"]["ensemble"]["top_k"], 4)
            self.assertEqual(guidance["modeling"]["algorithm_whitelist"], ["lightgbm"])
            self.assertEqual(guidance["evaluation"]["metric_gates"], {"recall_minority": 0.9})
            # 源任务思考链随任务落 memory（S1 引述块输入）
            self.assertIn("扭矩偏差主导", (run.memory_json or {}).get("recipe_trace", {}).get("s1_reasoning", ""))
            self.assertEqual((run.memory_json or {}).get("recipe_source", {}).get("recipe_id"), str(self.recipe_id))
        finally:
            db.close()

    def test_reuse_legacy_recipe_without_snapshot_fails_closed(self):
        r = client.post(
            f"/api/agent/recipes/{self.legacy_recipe_id}/reuse",
            json={"dataset_artifact_id": str(self.artifact_id)},
            headers=self.h,
        )
        self.assertEqual(r.status_code, 409)
        self.assertEqual(r.json()["detail"]["code"], "RECIPE_GUIDANCE_MISSING")

    def test_reuse_supervised_requires_target(self):
        # 配方无目标列 + 请求未提供 → 400（合同镜像）
        db = SessionLocal()
        try:
            recipe = create_recipe(
                db,
                project_id=self.project_id,
                name="no-target-" + uuid.uuid4().hex[:6],
                content={
                    "domain": "x",
                    "inputs": {"target_column": None},
                    "guidance": {"task_type": "supervised"},
                },
            )
            type(self).no_target_recipe_id = recipe.id
            recipe_id = recipe.id
        finally:
            db.close()
        r = client.post(
            f"/api/agent/recipes/{recipe_id}/reuse",
            json={"dataset_artifact_id": str(self.artifact_id)},
            headers=self.h,
        )
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.json()["detail"]["code"], "AGENT_RUN_TARGET_REQUIRED")

    def test_reuse_anomaly_forces_target_none(self):
        # 无监督配方：请求带目标列也被强制清空（镜像互斥）
        db = SessionLocal()
        try:
            recipe = create_recipe(
                db,
                project_id=self.project_id,
                name="anomaly-" + uuid.uuid4().hex[:6],
                content={
                    "domain": "x",
                    "inputs": {"target_column": None},
                    "guidance": {"task_type": "anomaly"},
                },
            )
            type(self).anomaly_recipe_id = recipe.id
            recipe_id = recipe.id
        finally:
            db.close()
        with patch("app.services.agent.executor.launch_agent_run"):
            r = client.post(
                f"/api/agent/recipes/{recipe_id}/reuse",
                json={
                    "dataset_artifact_id": str(self.artifact_id),
                    "target_column": "should_be_dropped",
                },
                headers=self.h,
            )
        self.assertEqual(r.status_code, 201, r.text)
        run_id = r.json()["run_id"]
        db = SessionLocal()
        try:
            from app.models.agent_run import AgentRun

            run = db.get(AgentRun, uuid.UUID(run_id))
            self.assertEqual(run.target_column, None)
            self.assertEqual((run.guidance_json or {}).get("task_type"), "anomaly")
        finally:
            db.close()

    def test_reuse_unknown_recipe_404(self):
        r = client.post(
            f"/api/agent/recipes/{uuid.uuid4()}/reuse",
            json={"dataset_artifact_id": str(self.artifact_id)},
            headers=self.h,
        )
        self.assertEqual(r.status_code, 404)

    @classmethod
    def tearDownClass(cls):
        # 清理共享库种子：配方版本→配方→工件→项目（按外键逆序）
        db = SessionLocal()
        try:
            from app.models.artifact import Artifact
            from app.models.project import Project
            from app.models.recipe import PipelineRecipeVersion

            for recipe_id in (cls.recipe_id, cls.legacy_recipe_id, cls.no_target_recipe_id,
                              cls.anomaly_recipe_id):
                recipe = db.get(PipelineRecipe, recipe_id)
                if recipe is not None:
                    db.query(PipelineRecipeVersion).filter(
                        PipelineRecipeVersion.recipe_id == recipe.id
                    ).delete()
                    db.delete(recipe)
            artifact = db.get(Artifact, cls.artifact_id)
            if artifact is not None:
                db.delete(artifact)
            project = db.get(Project, cls.project_id)
            if project is not None:
                db.delete(project)
            db.commit()
        finally:
            db.close()


if __name__ == "__main__":
    unittest.main()
