"""Wizard guidance + runner pause tests (AutoML Agent plan, Task A5.1)."""

import os
import unittest
from uuid import uuid4

os.environ.setdefault("LLM_MASTER_KEY", __import__(
    "cryptography.fernet", fromlist=["Fernet"]
).Fernet.generate_key().decode("ascii"))

import pandas as pd  # noqa: E402
from pydantic import ValidationError  # noqa: E402

from app.database import Base, SessionLocal, engine  # noqa: E402
from app.models.agent_run import AgentRun  # noqa: E402
from app.services.agent import runner as runner_module  # noqa: E402
from app.services.agent.contracts import (  # noqa: E402
    AnalysisReport,
    FeatureScript,
    ReviewVerdict,
    UserGuidance,
)
from app.services.agent.wizard import (  # noqa: E402
    algorithm_scope,
    merge_gates,
    pause_plan,
)
from app.services.llm_gateway import GatewayLLMConfig  # noqa: E402

Base.metadata.create_all(bind=engine)

_REPORT = AnalysisReport(
    domain_hypothesis="tightening",
    domain_reasoning="扭矩域",
    focus_channels=[{"name": "dev", "columns": ["F1"], "why": "主因"}],
    expected_important_features=[{"name_hint": "D", "reason": "r", "priority": "high"}],
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


def _verdict(text):
    return ReviewVerdict(verdict=text, business_readiness="ok")


def _config(profile_id):
    return GatewayLLMConfig(
        api_url="https://api.example.com/v1",
        api_key="sk-" + uuid4().hex,
        model_id="glm-4.6",
        temperature=None,
        timeout_seconds=30,
        profile_id=profile_id,
        profile_name="wizard-test",
    )


def _frame():
    return pd.DataFrame(
        {
            "F1": [5.0, 0.1] * 10,
            "F2": [-1.0, 1.0] * 10,
            "target": [1, 0] * 10,
        }
    )


class TestGuidanceContract(unittest.TestCase):
    def test_empty_guidance_is_valid_and_detected(self):
        guidance = UserGuidance()
        self.assertTrue(guidance.is_empty())

    def test_invalid_data_shape_rejected(self):
        with self.assertRaises(ValidationError):
            UserGuidance(feature={"data_shape": "audio"})

    def test_pause_stages_intersected_with_legal_positions(self):
        guidance = UserGuidance(pause_at_stages=["s1", "s3", "s9"])
        self.assertEqual(pause_plan(guidance), {"s1", "s3"})


class TestGateMerge(unittest.TestCase):
    def test_user_gate_replaces_default(self):
        merged, warnings = merge_gates({"recall_minority": 0.90}, {"recall_minority": 0.95})
        self.assertEqual(merged["recall_minority"], 0.95)
        self.assertEqual(warnings, [])

    def test_gate_below_default_produces_yellow_warning(self):
        merged, warnings = merge_gates({"recall_minority": 0.90}, {"recall_minority": 0.5})
        self.assertEqual(merged["recall_minority"], 0.5)
        self.assertEqual(len(warnings), 1)
        self.assertIn("gate_below_platform_default", warnings[0])

    def test_non_numeric_gate_ignored_with_warning(self):
        merged, warnings = merge_gates({"recall_minority": 0.90}, {"recall_minority": "high"})
        self.assertEqual(merged["recall_minority"], 0.90)
        self.assertTrue(any("invalid_gate_ignored" in warning for warning in warnings))


class TestAlgorithmScope(unittest.TestCase):
    def test_whitelist_is_hard_constraint(self):
        guidance = UserGuidance(modeling={"algorithm_whitelist": ["lightgbm"]})
        self.assertEqual(algorithm_scope(guidance), ["lightgbm"])
        self.assertEqual(algorithm_scope(None), [])


class TestRunnerPause(unittest.TestCase):
    def setUp(self):
        with SessionLocal() as db:
            from app.models.llm_profile import LLMProfile
            from app.models.user import User

            admin = db.query(User).filter(User.username == "admin").first()
            if admin is None:
                from tests.auth_test_support import ensure_admin

                ensure_admin()
                admin = db.query(User).filter(User.username == "admin").one()
            profile = LLMProfile(
                name="wizard-%s" % uuid4().hex[:6],
                api_url="https://api.wizard-test-llm.com/v1/chat/completions",
                model_id="glm-4.6",
                is_default=False,
            )
            db.add(profile)
            db.commit()
            self.profile_id = str(profile.id)
            run = AgentRun(target_column="target")
            db.add(run)
            db.commit()
            self.run_id = run.id
        self.db = SessionLocal()
        self.run = self.db.get(AgentRun, self.run_id)
        self.addCleanup(self.db.close)

    def test_step_mode_pauses_after_s1_and_resumes(self):
        from tests.auth_test_support import ensure_admin

        ensure_admin()
        guidance = {
            "analysis": {"prompts": ["关注偏差"]},
            "pause_at_stages": ["s1"],
        }
        with SessionLocal() as db:
            from app.models.llm_profile import LLMProfile

            profile_id = str(db.query(LLMProfile).first().id)

        def fake_s1(db, **kwargs):
            self.assertTrue(kwargs.get("guidance"))
            return _REPORT, None, {"total_tokens": 10}

        def fake_s2(db, **kwargs):
            return _SCRIPT, None, {"total_tokens": 10}

        def fake_s4(db, **kwargs):
            return _verdict("pass"), None, {"total_tokens": 10}

        for target, replacement in (
            ("run_s1", fake_s1),
            ("run_s2", fake_s2),
            ("run_s4", fake_s4),
        ):
            self.addCleanup(
                setattr, runner_module, target, getattr(runner_module, target)
            )
            setattr(runner_module, target, replacement)

        runner = runner_module.AgentRunner(
            self.db,
            run=self.run,
            config=_config(profile_id),
            profile_report={"row_count": 20},
            dataset_frame=_frame(),
            guidance=guidance,
            trainer=lambda features, y, hints: {
                "metrics": {"recall_minority": 0.95},
                "topk_metrics": [{"recall_minority": 0.95}, {"recall_minority": 0.94}],
                "importance": [{"feature": "D", "importance": 0.9}],
            },
        )
        paused = runner.run_to_completion()
        self.assertEqual(paused.status, "waiting_guidance")
        self.assertEqual(paused.current_stage, "s1")

        # Resume: the paused slot is consumed and the run reaches accepted.
        resumed = runner.run_to_completion()
        self.assertEqual(resumed.status, "accepted")
        self.assertEqual(resumed.current_stage, "done")
