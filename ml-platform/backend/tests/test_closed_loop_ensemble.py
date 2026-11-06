"""闭环自动化集成学习：配置字段 → 重训下发 → 配方固化/服务化映射。

链路：向导第三步 guidance.modeling.ensemble →（固化）配方 retrain_ensemble →
（服务化）闭环 retrain_ensemble_enabled/top_k →（重训）trigger_retrain_job
ensemble → 引擎终选层集成 → 换模优先任务冠军（含被采纳的集成）。
"""

import tempfile
import unittest
import joblib
from pathlib import Path
from types import SimpleNamespace
from unittest import mock
from uuid import uuid4

from pydantic import ValidationError

from app.api.agent_extras import _fixation_content
from app.api.demo_loop import DemoLoopConfigUpdate
from app.models.demo_loop import DemoLoopConfig
from app.services import demo_loop as demo_loop_module


class TestLoopEnsembleConfig(unittest.TestCase):
    def test_apply_config_fields_persists_and_clamps_top_k(self):
        service = demo_loop_module.DemoLoopService(mock.MagicMock())
        config = DemoLoopConfig()
        service._apply_config_fields(config, uuid4(), {
            "retrain_ensemble_enabled": True, "retrain_ensemble_top_k": 9,
        })
        self.assertTrue(config.retrain_ensemble_enabled)
        self.assertEqual(config.retrain_ensemble_top_k, 5)
        service._apply_config_fields(config, uuid4(), {"retrain_ensemble_top_k": 1})
        self.assertEqual(config.retrain_ensemble_top_k, 2)

    def test_api_request_rejects_out_of_range_top_k(self):
        with self.assertRaises(ValidationError):
            DemoLoopConfigUpdate(retrain_ensemble_top_k=6)
        self.assertEqual(DemoLoopConfigUpdate(retrain_ensemble_top_k=4).retrain_ensemble_top_k, 4)

    def _trigger(self, *, enabled: bool) -> dict:
        service = demo_loop_module.DemoLoopService(mock.MagicMock())
        config = SimpleNamespace(
            retrain_dataset_artifact_ids=[str(uuid4())], retrain_dataset_artifact_id=None,
            error_artifact_id=None, correct_artifact_id=None,
            retrain_target_column="fault", name="loop", error_count=7,
            project_id=uuid4(), retrain_max_trials=10,
            retrain_ensemble_enabled=enabled, retrain_ensemble_top_k=4,
            retrain_algorithm_ids=["catboost", "lightgbm"],
            retrain_job_id=None, retrain_status=None,
        )
        fake_job = SimpleNamespace(id=uuid4(), params={"max_trials": 10})
        with mock.patch.object(demo_loop_module, "trigger_retrain_job", return_value=fake_job) as trigger, \
                mock.patch.object(service, "_emit"):
            service._trigger_retrain_inner(config, uuid4())
        return trigger.call_args.kwargs

    def test_retrain_forwards_ensemble_when_enabled(self):
        kwargs = self._trigger(enabled=True)
        self.assertEqual(kwargs["ensemble"], {"enabled": True, "top_k": 4})
        # 向导算法白名单随重训下发（缩小引擎搜索族）
        self.assertEqual(kwargs["algorithm_ids"], ["catboost", "lightgbm"])

    def test_retrain_omits_ensemble_when_disabled(self):
        self.assertIsNone(self._trigger(enabled=False)["ensemble"])


class TestRecipeEnsembleFixation(unittest.TestCase):
    @staticmethod
    def _run(modeling: dict):
        return SimpleNamespace(
            id=uuid4(), target_column="fault",
            guidance_json={"modeling": modeling, "evaluation": {}},
            result_json={"metrics": {}},
        )

    def test_fixation_carries_wizard_ensemble_choice(self):
        content = _fixation_content(self._run({"ensemble": {"enabled": True, "top_k": 4}}), {"rounds": []})
        self.assertEqual(content["retrain_ensemble"], {"enabled": True, "top_k": 4})

    def test_fixation_without_ensemble_is_disabled(self):
        content = _fixation_content(self._run({}), {"rounds": []})
        self.assertEqual(content["retrain_ensemble"], {"enabled": False})

    def test_fixation_carries_algorithm_whitelist(self):
        """向导算法白名单随配方固化（此前 guidance.modeling.algorithm_whitelist
        无任何消费方，勾选形同虚设）。"""
        content = _fixation_content(self._run({
            "algorithm_whitelist": ["catboost", "lightgbm"],
            "ensemble": {"enabled": True, "top_k": 3},
        }), {"rounds": []})
        self.assertEqual(content["retrain_algorithm_ids"], ["catboost", "lightgbm"])

    def test_fixation_without_whitelist_is_empty(self):
        content = _fixation_content(self._run({}), {"rounds": []})
        self.assertEqual(content["retrain_algorithm_ids"], [])


class TestServitizeAlgorithmWhitelist(unittest.TestCase):
    """服务化：配方 retrain_algorithm_ids → 闭环配置字段（重训引擎搜索族）。"""

    def test_recipe_whitelist_flows_into_loop_config(self):
        import uuid as _uuid

        import numpy as np
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker
        from sklearn.linear_model import LogisticRegression

        from app.database import Base
        from app.models.model_registry import InferenceDeployment, ModelVersion, RegisteredModel
        from app.models.project import Project
        from app.models.user import User
        # 应用级 ArtifactService（存储根取测试配置）：servitize 冒烟经同根加载
        from app.services.artifact_service import build_artifact_service
        from app.services.agent.servitize import servitize_recipe

        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        Session = sessionmaker(bind=engine, expire_on_commit=False)
        with Session() as db:
            user = User(username="sv-algo", password_hash="h")
            db.add(user)
            db.flush()
            project = Project(name="sv-algo", owner_id=user.id)
            db.add(project)
            db.flush()
            # 真实可预测的 joblib 模型工件：servitize 冒烟（dry-run predict）
            # 走进程内回退路径加载它
            service = build_artifact_service(db)
            features = np.asarray([[0.0, 1.0], [5.0, -1.0]])
            fitted = LogisticRegression(random_state=0).fit(features, [0, 1])
            with tempfile.TemporaryDirectory() as tmp:
                model_file = Path(tmp) / "m.joblib"
                joblib.dump(fitted, model_file)
                artifact = service.create_from_file(
                    project.id, model_file, "m.joblib", "model",
                    metadata={"source": "automl"}, commit=False,
                )
            model = RegisteredModel(project_id=project.id, name="m", created_by_id=user.id)
            db.add(model)
            db.flush()
            version = ModelVersion(
                registered_model_id=model.id, version_number=1,
                source_kind="platform_joblib", source_model_library_id=artifact.id,
                source_artifact_id=artifact.id,
                onnx_artifact_id=artifact.id,
                framework="sklearn",
                approval_status="approved", created_by_id=user.id,
                feature_schema=[
                    {"name": "f1", "dtype": "float64"},
                    {"name": "f2", "dtype": "float64"},
                ],
                output_schema={"target_columns": ["fault"]},
            )
            db.add(version)
            db.flush()
            deployment = InferenceDeployment(
                project_id=project.id, name="dep", model_version_id=version.id,
                desired_state="running", observed_state="running", created_by_id=user.id,
            )
            db.add(deployment)
            db.commit()
            draft = servitize_recipe(
                db, project_id=project.id, actor_id=user.id,
                deployment_id=deployment.id,
                recipe_content={
                    "target_semantics": {"0": "合格", "1": "不合格"},
                    "feature_script": "def transform(df):" + chr(10) + "    return df",
                    "smoke_row": {"f1": 5.0, "f2": -1.0},
                    "retrain_algorithm_ids": ["catboost", "lightgbm"],
                },
                model_api_name="sv-algo-%s" % _uuid.uuid4().hex[:6],
            )
            loop = db.get(DemoLoopConfig, _uuid.UUID(draft.loop_config_id))
            self.assertEqual(loop.retrain_algorithm_ids, ["catboost", "lightgbm"])
        engine.dispose()


class TestOrchestrationRetrainEnsemble(unittest.TestCase):
    """应用编排「重训阈值」算子：画布参数开启集成 → 重训下发 ensemble。"""

    def _execute(self, params: dict) -> dict:
        from app.engine.registry import OperatorRegistry
        import app.operators  # noqa: F401  (populates the registry)

        artifact = SimpleNamespace(id=uuid4(), metadata_={"row_count": 20, "cycle_base": 0})
        artifact_service = SimpleNamespace(
            db=mock.MagicMock(), resolve=lambda *_args, **_kwargs: artifact,
        )
        context = SimpleNamespace(
            artifact_service=artifact_service, project_id=uuid4(), operator_id=uuid4(),
        )
        with mock.patch(
            "app.services.closed_loop_actions.trigger_retrain_job",
            return_value=SimpleNamespace(id=uuid4()),
        ) as trigger:
            OperatorRegistry.get("retrain_threshold").execute(context, {"data": []}, {
                "dataset_artifact_id": str(artifact.id),
                "retrain_target_column": "fault",
                "threshold_rows": 10,
                **params,
            })
        return trigger.call_args.kwargs

    def test_boolean_param_forwards_ensemble(self):
        kwargs = self._execute({"retrain_ensemble_enabled": True, "retrain_ensemble_top_k": 4})
        self.assertEqual(kwargs["ensemble"], {"enabled": True, "top_k": 4})

    def test_string_params_are_parsed_and_top_k_clamped(self):
        kwargs = self._execute({"retrain_ensemble_enabled": "true", "retrain_ensemble_top_k": "9"})
        self.assertEqual(kwargs["ensemble"], {"enabled": True, "top_k": 5})

    def test_ensemble_off_by_default(self):
        self.assertIsNone(self._execute({})["ensemble"])
        self.assertIsNone(self._execute({"retrain_ensemble_enabled": "false"})["ensemble"])


if __name__ == "__main__":
    unittest.main()
