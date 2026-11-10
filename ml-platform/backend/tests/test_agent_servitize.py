"""S5 servitization tests (AutoML Agent plan, Task A3.3).

Contract under test (spec v0.9 §12.1/§12.6): draft semantics (loop created
passively, model API ``offline`` until the explicit approval switch),
defect-class derivation from target semantics, dry-run smoke with ZERO
backflow (negative control: a wet predict on the same config DOES write), and
the project-level mutex.
"""

import os
import tempfile
import threading
import unittest
import uuid
from pathlib import Path
from uuid import uuid4

os.environ.setdefault("LLM_MASTER_KEY", __import__(
    "cryptography.fernet", fromlist=["Fernet"]
).Fernet.generate_key().decode("ascii"))

import joblib  # noqa: E402
from sklearn.linear_model import LogisticRegression  # noqa: E402

from app.database import Base, SessionLocal, engine  # noqa: E402
from app.models.api_model import PlatformAPI  # noqa: E402
from app.models.demo_loop import DemoLoopConfig  # noqa: E402
from app.models.model_library import ModelLibrary  # noqa: E402
from app.models.model_registry import (  # noqa: E402
    InferenceDeployment,
    ModelVersion,
    RegisteredModel,
)
from app.models.project import Project  # noqa: E402
from app.models.user import User  # noqa: E402
from app.services.agent.servitize import (  # noqa: E402
    activate_servitize,
    derive_error_classes,
    servitize_lock,
    servitize_recipe,
)
from app.services.artifact_service import build_artifact_service  # noqa: E402
from tests.auth_test_support import ensure_admin  # noqa: E402

Base.metadata.create_all(bind=engine)

_RECIPE_CONTENT = {
    "domain": "tightening",
    "target_semantics": {"0": "不合格", "1": "合格"},
    "inputs": {"target_column": "DECIDE(判定结果)"},
    "feature_script": "def transform(df):\n    return df",
    "acceptance_gates": {"recall_minority": 0.90},
    "smoke_row": {"f1": 5.0, "f2": -1.0},
}


class TestDeriveErrorClasses(unittest.TestCase):
    def test_defect_semantics_derived(self):
        classes, ambiguous = derive_error_classes(
            {"0": "不合格", "1": "合格"}
        )
        self.assertEqual(classes, ["0"])
        self.assertEqual(ambiguous, ["1"])

    def test_no_match_falls_back_with_ambiguity(self):
        classes, ambiguous = derive_error_classes({"A": "类型甲", "B": "类型乙"})
        self.assertEqual(classes, ["A"])
        self.assertEqual(sorted(ambiguous), ["A", "B"])

    def test_no_match_prefers_minority_label(self):
        # 点焊 fault：1=缺陷（少数类）/0=正常——无描述时取少数类，而非字典序最小
        classes, ambiguous = derive_error_classes({"1": "", "0": ""}, "1")
        self.assertEqual(classes, ["1"])
        self.assertEqual(sorted(ambiguous), ["0", "1"])
        # 语义命中优先于少数类兜底
        classes, _ = derive_error_classes({"0": "不合格", "1": "合格"}, "1")
        self.assertEqual(classes, ["0"])
        # 少数类标签不在取值里（脏数据）→ 退回字典序最小
        self.assertEqual(derive_error_classes({"A": "", "B": ""}, "Z")[0], ["A"])


class TestServitize(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        ensure_admin()
        db = SessionLocal()
        try:
            admin = db.query(User).filter(User.username == "admin").one()
            project = Project(name="s5-%s" % uuid4().hex[:8], owner_id=admin.id)
            db.add(project)
            db.flush()
            service = build_artifact_service(db)
            model = LogisticRegression().fit(
                [[0.0, 1.0], [0.2, 1.1], [5.0, -1.0], [5.2, -1.2]],
                [0, 0, 1, 1],
            )
            with tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / "s5-model.joblib"
                joblib.dump(model, path)
                artifact = service.create_from_file(
                    project.id, path, "s5-model", "model"
                )
            artifact_id = uuid.UUID(str(artifact.id))
            registered = RegisteredModel(
                project_id=project.id,
                name="s5-model-%s" % uuid4().hex[:6],
                created_by_id=admin.id,
            )
            db.add(registered)
            db.flush()
            library = ModelLibrary(
                name="s5-lib-%s" % uuid4().hex[:6],
                project_id=project.id,
                owner_id=admin.id,
                status="completed",
                framework="sklearn",
                model_artifact_id=artifact_id,
                file_size=1,
                format="joblib",
            )
            db.add(library)
            db.flush()
            version = ModelVersion(
                registered_model_id=registered.id,
                version_number=1,
                source_kind="platform_joblib",
                source_artifact_id=artifact_id,
                onnx_artifact_id=artifact_id,
                approval_status="approved",
                source_model_library_id=library.id,
                created_by_id=admin.id,
            )
            db.add(version)
            db.flush()
            deployment = InferenceDeployment(
                project_id=project.id,
                name="s5-deploy-%s" % uuid4().hex[:6],
                model_version_id=version.id,
                created_by_id=admin.id,
            )
            db.add(deployment)
            db.commit()
            cls.project_id = project.id
            cls.deployment_id = str(deployment.id)
            cls.admin_id = admin.id
        finally:
            db.close()

    def setUp(self):
        # Shared deployment across tests: clear servitize state so each test
        # starts from an unpublished project.
        with SessionLocal() as db:
            from app.models.demo_loop import DemoLoopEvent

            db.query(PlatformAPI).filter(
                PlatformAPI.source_kind == "servitize"
            ).delete()
            db.query(DemoLoopEvent).delete()
            db.query(DemoLoopConfig).delete()
            db.commit()

    def servitize(self, **overrides):
        with SessionLocal() as db:
            return servitize_recipe(
                db,
                project_id=self.project_id,
                actor_id=self.admin_id,
                deployment_id=self.deployment_id,
                recipe_content=dict(_RECIPE_CONTENT),
                **overrides,
            )

    def test_draft_semantics_loop_passive_api_offline(self):
        draft = self.servitize(model_api_name="s5-draft-%s" % uuid4().hex[:6])
        self.assertFalse(draft.activated)
        with SessionLocal() as db:
            api = db.get(PlatformAPI, uuid.UUID(draft.model_api_id))
            loop = db.get(DemoLoopConfig, uuid.UUID(draft.loop_config_id))
        self.assertEqual(api.status, "offline")
        self.assertEqual(api.source_kind, "servitize")
        self.assertIsNotNone(loop)
        self.assertEqual(loop.error_classes, ["0"])
        # 脚本桥接：配方带 S2 特征脚本 → 闭环 script 模式（result= 适配尾）
        self.assertEqual(loop.feature_engineering_mode, "script")
        self.assertIn("result = transform(df)", loop.feature_script or "")
        # A draft loop has seen zero traffic.
        self.assertEqual(int(loop.total_count or 0), 0)
        # 旧配方无 retrain_ensemble 键：闭环重训集成默认关闭（行为不变）
        self.assertFalse(loop.retrain_ensemble_enabled)
        # 未传配方 id 的服务化保持引擎默认（不擅自绑智能体重训）
        self.assertEqual(loop.retrain_mode or "engine", "engine")
        self.assertIsNone(loop.retrain_agent_recipe_id)
        # 市场条目调用入口 = 闭环 scoped predict（曾为空串，调用示例无从调用）
        self.assertEqual(
            api.endpoint,
            f"/api/projects/{self.project_id}/demo-loop/loops/{loop.id}/predict",
        )
        self.assertEqual(api.method, "POST")
        self.assertEqual(api.request_schema.get("record"), {"f1": 5.0, "f2": -1.0})

    def test_marketplace_example_record_excludes_target(self):
        """示例行取冒烟行（训练集首行，真实形态带目标列）但剔除目标列。"""
        from app.services.agent.servitize import example_record

        content = dict(
            _RECIPE_CONTENT,
            smoke_row={"f1": 5.0, "f2": -1.0, "DECIDE(判定结果)": 1},
        )
        self.assertEqual(example_record(content), {"f1": 5.0, "f2": -1.0})
        self.assertEqual(example_record({}), {})

    def test_semantics_without_descriptions_use_minority_as_error_class(self):
        """固化配方的目标语义只有取值无描述（真实形态）：闭环缺陷类取少数类。"""
        content = dict(_RECIPE_CONTENT, target_semantics={"1": "", "0": ""},
                       minority_label="1")
        with SessionLocal() as db:
            draft = servitize_recipe(
                db,
                project_id=self.project_id,
                actor_id=self.admin_id,
                deployment_id=self.deployment_id,
                recipe_content=content,
                model_api_name="s5-minority-%s" % uuid4().hex[:6],
            )
            loop = db.get(DemoLoopConfig, uuid.UUID(draft.loop_config_id))
            self.assertEqual(draft.error_classes, ["1"])
            self.assertEqual(loop.error_classes, ["1"])

    def _source_run(self, db, *, dataset_exists=True):
        """配方源 run：其数据集就是部署模型的原始训练集。"""
        from app.models.agent_run import AgentRun

        dataset_id = uuid4()
        if dataset_exists:
            service = build_artifact_service(db)
            with tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / "s5-train.csv"
                path.write_text("f1,f2,DECIDE(判定结果)\n0.0,1.0,0\n5.0,-1.0,1\n",
                                encoding="utf-8")
                dataset = service.create_from_file(
                    self.project_id, path, "s5-train-%s" % uuid4().hex[:6], "dataset")
            dataset_id = uuid.UUID(str(dataset.id))
        run = AgentRun(
            project_id=self.project_id,
            dataset_artifact_id=dataset_id,
            target_column="DECIDE(判定结果)",
            status="accepted",
            created_by=self.admin_id,
        )
        db.add(run)
        db.commit()
        return run, dataset_id

    def _bound_servitize(self, db, run, name):
        from app.services.agent.recipe import create_recipe

        content = dict(_RECIPE_CONTENT, source_run_id=str(run.id))
        recipe = create_recipe(
            db, project_id=self.project_id, name="s5-recipe-%s" % uuid4().hex[:6],
            content=content, created_by=self.admin_id,
        )
        db.commit()
        draft = servitize_recipe(
            db,
            project_id=self.project_id,
            actor_id=self.admin_id,
            deployment_id=self.deployment_id,
            recipe_content=content,
            model_api_name=name,
            recipe_id=recipe.id,
        )
        return recipe, draft

    def test_recipe_bound_servitize_enables_agent_retrain(self):
        """一键服务化（带配方）：闭环绑智能体重训+配方、阈值缺省 20、重训
        数据含配方源 run 的原始训练集——此前停在引擎/未绑配方/阈值 0/无
        重训集：④ 发布编排必 422，合并重训集只剩报错行（近乎单类）。"""
        with SessionLocal() as db:
            run, dataset_id = self._source_run(db)
            recipe, draft = self._bound_servitize(db, run, "s5-bind-%s" % uuid4().hex[:6])
            loop = db.get(DemoLoopConfig, uuid.UUID(draft.loop_config_id))
            db.refresh(loop)
            self.assertEqual(loop.retrain_mode, "agent")
            self.assertEqual(loop.retrain_agent_recipe_id, recipe.id)
            self.assertEqual(loop.retrain_threshold_rows, 20)
            self.assertTrue(loop.retrain_enabled)
            self.assertEqual(loop.retrain_dataset_artifact_ids, [str(dataset_id)])

    def test_reservitize_keeps_user_tuned_threshold(self):
        """复用草稿重新服务化：用户已调的阈值不被缺省值覆盖。"""
        name = "s5-tune-%s" % uuid4().hex[:6]
        with SessionLocal() as db:
            run, _dataset_id = self._source_run(db)
            _recipe, first = self._bound_servitize(db, run, name)
            loop = db.get(DemoLoopConfig, uuid.UUID(first.loop_config_id))
            loop.retrain_threshold_rows = 50
            db.commit()
            _recipe, second = self._bound_servitize(db, run, name)
            self.assertEqual(first.loop_config_id, second.loop_config_id)
            loop = db.get(DemoLoopConfig, uuid.UUID(second.loop_config_id))
            db.refresh(loop)
            self.assertEqual(loop.retrain_threshold_rows, 50)

    def test_missing_source_dataset_does_not_block_servitize(self):
        """源 run 数据集已删：只是不绑重训集，服务化本身照常完成。"""
        with SessionLocal() as db:
            run, _dataset_id = self._source_run(db, dataset_exists=False)
            _recipe, draft = self._bound_servitize(db, run, "s5-gone-%s" % uuid4().hex[:6])
            loop = db.get(DemoLoopConfig, uuid.UUID(draft.loop_config_id))
            db.refresh(loop)
            self.assertEqual(loop.retrain_mode, "agent")
            self.assertFalse(loop.retrain_dataset_artifact_ids)

    def test_error_dataset_precreated_before_first_backflow(self):
        """④ 发布编排需在首次回流前拿到报错集 id：预建（幂等）后首次真实
        回流直接追加进同一数据集，不另起新集。"""
        from app.services.demo_loop import DemoLoopService

        draft = self.servitize(model_api_name="s5-err-%s" % uuid4().hex[:6])
        with SessionLocal() as db:
            loop = db.get(DemoLoopConfig, uuid.UUID(draft.loop_config_id))
            self.assertIsNone(loop.error_artifact_id)
            service = DemoLoopService(db)
            artifact = service.ensure_error_dataset(
                loop, ["confidence", "f1", "f2", "prediction"])
            db.refresh(loop)
            self.assertEqual(loop.error_artifact_id, artifact.id)
            self.assertEqual(service.ensure_error_dataset(loop, ["f1"]).id, artifact.id)
            # {0.0, 1.0} 预测为 0，命中报错类别 "0" → 真实回流
            service.predict(loop, {"f1": 0.0, "f2": 1.0}, self.admin_id)
            db.refresh(loop)
            self.assertEqual(int(loop.error_count or 0), 1)
            self.assertEqual(loop.error_artifact_id, artifact.id)

    def test_recipe_ensemble_choice_flows_into_loop_retrain(self):
        """向导第三步的集成选项随配方固化 → 服务化闭环重训沿用。"""
        content = dict(_RECIPE_CONTENT, retrain_ensemble={"enabled": True, "top_k": 4})
        with SessionLocal() as db:
            draft = servitize_recipe(
                db,
                project_id=self.project_id,
                actor_id=self.admin_id,
                deployment_id=self.deployment_id,
                recipe_content=content,
                model_api_name="s5-ens-%s" % uuid4().hex[:6],
            )
        with SessionLocal() as db:
            loop = db.get(DemoLoopConfig, uuid.UUID(draft.loop_config_id))
        self.assertTrue(loop.retrain_ensemble_enabled)
        self.assertEqual(loop.retrain_ensemble_top_k, 4)

    def test_smoke_is_dry_run_with_zero_backflow(self):
        draft = self.servitize(model_api_name="s5-smoke-%s" % uuid4().hex[:6])
        self.assertTrue(draft.smoke.get("dry_run"))
        self.assertEqual(draft.smoke.get("appended"), False)
        with SessionLocal() as db:
            loop = db.get(DemoLoopConfig, uuid.UUID(draft.loop_config_id))
            total_after_smoke = int(loop.total_count or 0)
            errors_after_smoke = int(loop.error_count or 0)
        self.assertEqual(total_after_smoke, 0)
        self.assertEqual(errors_after_smoke, 0)

        # Negative control: a wet predict on the SAME config writes state —
        # proving the zero-backflow assertion above can detect pollution.
        with SessionLocal() as db:
            loop = db.get(DemoLoopConfig, uuid.UUID(draft.loop_config_id))
            from app.services.demo_loop import DemoLoopService

            DemoLoopService(db).predict(
                loop, {"f1": 5.0, "f2": -1.0}, self.admin_id
            )
            db.refresh(loop)
            self.assertGreaterEqual(int(loop.total_count or 0), 1)

    def test_activation_flips_offline_to_published(self):
        draft = self.servitize(model_api_name="s5-act-%s" % uuid4().hex[:6])
        with SessionLocal() as db:
            api = activate_servitize(
                db, model_api_id=draft.model_api_id, actor_id=self.admin_id
            )
            self.assertEqual(api.status, "published")
            self.assertIsNotNone(api.published_at)
            with self.assertRaises(ValueError):
                activate_servitize(
                    db, model_api_id=draft.model_api_id, actor_id=self.admin_id
                )

    def test_reservitize_reuses_draft_and_bumps_version(self):
        # platform_apis is unique per (source_kind, source_id, version): a
        # second servitize call on the SAME deployment must reuse the offline
        # draft row (and its loop config), bumping the entry version (§12.4).
        base = "s5-reuse-%s" % uuid4().hex[:6]
        first = self.servitize(model_api_name=base)
        second = self.servitize(model_api_name=base)
        self.assertEqual(first.model_api_id, second.model_api_id)
        self.assertEqual(first.loop_config_id, second.loop_config_id)
        with SessionLocal() as db:
            api = db.get(PlatformAPI, uuid.UUID(second.model_api_id))
            self.assertEqual(api.version, "v2")
            self.assertEqual(api.status, "offline")

    def test_project_mutex_serializes_servitize(self):
        order = []

        def worker():
            with servitize_lock(self.project_id):
                order.append("enter")
                order.append("exit")

        threads = [threading.Thread(target=worker) for _ in range(3)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        # Strict alternation proves mutual exclusion: never enter,enter.
        for index in range(0, len(order) - 2, 2):
            self.assertEqual(order[index], "enter")
            self.assertEqual(order[index + 1], "exit")
