"""闭环自动化集成学习：配置字段 → 重训下发 → 配方固化/服务化映射。

链路：向导第三步 guidance.modeling.ensemble →（固化）配方 retrain_ensemble →
（服务化）闭环 retrain_ensemble_enabled/top_k →（重训）trigger_retrain_job
ensemble → 引擎终选层集成 → 换模优先任务冠军（含被采纳的集成）。
"""

import unittest
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
            retrain_job_id=None, retrain_status=None,
        )
        fake_job = SimpleNamespace(id=uuid4(), params={"max_trials": 10})
        with mock.patch.object(demo_loop_module, "trigger_retrain_job", return_value=fake_job) as trigger, \
                mock.patch.object(service, "_emit"):
            service._trigger_retrain_inner(config, uuid4())
        return trigger.call_args.kwargs

    def test_retrain_forwards_ensemble_when_enabled(self):
        self.assertEqual(self._trigger(enabled=True)["ensemble"], {"enabled": True, "top_k": 4})

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
