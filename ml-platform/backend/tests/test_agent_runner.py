"""Agent Runner tests (AutoML Agent plan, Task A2.2/A2.3).

All LLM traffic is mocked at the runner's module boundary (run_s1/run_s2/
run_s4); the sandbox runs for real against a small frame; S3 uses an injected
deterministic trainer (the platform AutoML binding lands in P3).
"""

import os
import unittest
import uuid
from unittest import mock
from uuid import uuid4

os.environ.setdefault("LLM_MASTER_KEY", __import__(
    "cryptography.fernet", fromlist=["Fernet"]
).Fernet.generate_key().decode("ascii"))

import pandas as pd  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.database import Base, SessionLocal, engine  # noqa: E402
from app.models.agent_run import AgentRun  # noqa: E402
from app.services.agent import runner as runner_module  # noqa: E402
from app.services.agent.contracts import (  # noqa: E402
    AnalysisReport,
    FeatureScript,
    ReviewVerdict,
)
from app.services.llm_gateway import GatewayLLMConfig  # noqa: E402

Base.metadata.create_all(bind=engine)
_test_client = TestClient(__import__("app.main", fromlist=["app"]).app)

_REPORT = AnalysisReport(
    domain_hypothesis="tightening",
    domain_reasoning="扭矩域",
    focus_channels=[{"name": "dev", "columns": ["ACTUAL_TORQUE"], "why": "偏差"}],
    expected_important_features=[
        {"name_hint": "TORQUE_DEVIATION", "reason": "偏差主因", "priority": "high"}
    ],
    leakage_suspects=[{"column": "DECIDE_ONE", "why": "同源判定"}],
    feature_engineering_brief="派生偏差特征，剔除泄漏列",
)

_SCRIPT_OK = FeatureScript(
    script=(
        "import pandas as pd\n"
        "def transform(df):\n"
        "    out = df.drop(columns=['DECIDE_ONE'])\n"
        "    out['TORQUE_DEVIATION'] = out['ACTUAL_TORQUE'] - out['TARGET_TORQUE']\n"
        "    return out\n"
    ),
    description="偏差特征",
    generated_columns=["TORQUE_DEVIATION"],
    dropped_columns=["DECIDE_ONE"],
)


def _verdict(verdict_text: str, hints=None) -> ReviewVerdict:
    return ReviewVerdict(
        verdict=verdict_text,
        business_readiness="结论",
        next_iteration_hints=hints or [],
    )


def _config(profile_id: str):
    return GatewayLLMConfig(
        api_url="https://api.example.com/v1",
        api_key="sk-" + uuid4().hex,
        model_id="glm-4.6",
        temperature=None,
        timeout_seconds=30,
        profile_id=profile_id,
        profile_name="runner-test",
    )


def _trainer_passing(feature_df, y, hints):
    return {
        "metrics": {"recall_minority": 0.94, "f1": 0.9},
        "topk_metrics": [{"recall_minority": 0.94}, {"recall_minority": 0.93}],
        "importance": [
            {"feature": "TORQUE_DEVIATION", "importance": 0.6},
            {"feature": "ACTUAL_TORQUE", "importance": 0.3},
        ],
    }


def _frame(n: int = 40) -> pd.DataFrame:
    frame = pd.DataFrame(
        {
            "ACTUAL_TORQUE": [25.0 + (i % 5) * 0.2 for i in range(n)],
            "TARGET_TORQUE": [26.0] * n,
            "DECIDE_ONE": [i % 2 for i in range(n)],
            "DECIDE(判定结果)": [(i % 7 == 0) and 1 or 0 for i in range(n)],
        }
    )
    return frame


class RunnerHarness(unittest.TestCase):
    def build(self, monkeypatches: dict, run_kwargs=None, trainer=_trainer_passing, guidance=None):
        """Construct a runner with runner-module LLM functions patched."""
        from app.models.llm_profile import LLMProfile

        with SessionLocal() as db:
            profile = LLMProfile(
                name="runner-" + uuid4().hex[:6],
                api_url="https://api.runner-test-llm.com/v1/chat/completions",
                model_id="glm-4.6",
                is_default=False,
            )
            db.add(profile)
            db.commit()
            profile_id = str(profile.id)
            run_kwargs = dict(run_kwargs or {})
            run_kwargs.setdefault("target_column", "DECIDE(判定结果)")
            run = AgentRun(**run_kwargs)
            db.add(run)
            db.commit()
            run_id = run.id
        # One long-lived session for the run's lifetime (the runner commits).
        db = SessionLocal()
        run = db.get(AgentRun, run_id)
        for target, replacement in monkeypatches.items():
            self.addCleanup(setattr, runner_module, target, getattr(runner_module, target))
            setattr(runner_module, target, replacement)
        runner = runner_module.AgentRunner(
            db,
            run=run,
            config=_config(profile_id),
            profile_report={"row_count": 40},
            dataset_frame=_frame(),
            guidance=guidance,
            trainer=trainer,
        )
        self.addCleanup(db.close)
        return runner, db, run_id


class TestAgentRunner(RunnerHarness, unittest.TestCase):
    def test_accepted_single_round_records_model_and_memory(self):
        calls = {"s1": 0, "s4": 0}

        def fake_s1(db, **kwargs):
            calls["s1"] += 1
            return _REPORT, None, {"total_tokens": 500}

        def fake_s4(db, **kwargs):
            calls["s4"] += 1
            return _verdict("pass"), None, {"total_tokens": 300}

        runner, db, run_id = self.build(
            {"run_s1": fake_s1, "run_s2": lambda db, **kw: (_SCRIPT_OK, None, {"total_tokens": 200}), "run_s4": fake_s4}
        )
        result = runner.run_to_completion()
        self.assertEqual(result.status, "accepted")
        self.assertEqual(result.round_count, 1)
        self.assertEqual(result.llm_model_id, "glm-4.6")
        self.assertIsNotNone(result.llm_profile_id)
        self.assertEqual(result.token_used, 1000)
        self.assertTrue(result.memory_json["rounds"][0]["s2_attempts"][0]["ok"])
        self.assertEqual(calls["s1"], 1)

    def test_stage_artifacts_persist_per_stage_into_round_memory(self):
        """§7 任务档案：S1 分析/S2 特征/S3 训练/S4 门禁与评审逐阶段落 memory。"""
        def fake_s1(db, **kwargs):
            return _REPORT, None, {"total_tokens": 100}

        runner, db, run_id = self.build(
            {
                "run_s1": fake_s1,
                "run_s2": lambda db, **kw: (_SCRIPT_OK, None, {"total_tokens": 100}),
                "run_s4": lambda db, **kw: (_verdict("pass"), None, {"total_tokens": 100}),
            }
        )
        result = runner.run_to_completion()
        self.assertEqual(result.status, "accepted")
        entry = result.memory_json["rounds"][0]
        self.assertEqual(entry["s1"]["domain"], _REPORT.domain_hypothesis)
        self.assertTrue(entry["s1"]["focus_channels"])
        self.assertEqual(entry["s2"]["data_shape"], _SCRIPT_OK.data_shape)
        self.assertTrue(entry["s2"]["generated_columns"])
        self.assertIn("recall_minority", entry["s3"]["metrics"])
        self.assertTrue(entry["s3"]["importance"])
        self.assertTrue(entry["s4"]["gate_passed"])
        self.assertEqual(entry["review"]["verdict"], "pass")
        self.assertIn("readiness", entry["review"])

    def test_s3_trains_on_full_data_replay_not_sandbox_sample(self):
        """回归（85bd8c96）：S3 必须全量重放特征脚本，特征行数=标签行数。

        沙箱验证跑 S2_SAMPLE_ROWS 样本；修复前样本输出被直接喂给训练器，
        与全量标签行数错位 → train_test_split ValueError 崩溃。
        """
        def fake_s1(db, **kwargs):
            return _REPORT, None, {"total_tokens": 100}

        seen_shapes = []

        def trainer(feature_df, y, hints):
            seen_shapes.append((int(feature_df.shape[0]), int(len(y))))
            return {
                "metrics": {"recall_minority": 0.94, "f1": 0.9},
                "topk_metrics": [{"recall_minority": 0.94}],
                "importance": [{"feature": "TORQUE_DEVIATION", "importance": 0.6}],
            }

        runner, db, run_id = self.build(
            {
                "run_s1": fake_s1,
                "run_s2": lambda db, **kw: (_SCRIPT_OK, None, {"total_tokens": 100}),
                "run_s4": lambda db, **kw: (_verdict("pass"), None, {"total_tokens": 100}),
            },
            trainer=trainer,
        )
        result = runner.run_to_completion()
        self.assertEqual(result.status, "accepted")
        # 全量 40 行（_frame 默认）而非 5000 行样本；且特征与标签等长。
        self.assertEqual(seen_shapes[0], (40, 40))

    def test_s3_never_feeds_target_column_into_features(self):
        """回归（真机 7c9415b1）：标签列不得进入特征矩阵。

        target_must_survive 契约下 S2 脚本原样透传目标列（_SCRIPT_OK 不剔除
        DECIDE(判定结果)）；修复前该列随全量重放直接喂训练器 → 标签自泄漏、
        全指标 1.0 假完美。平台侧必须在训练前无条件剥离并留痕。
        """
        seen_columns = []

        def trainer(feature_df, y, hints):
            seen_columns.append(list(feature_df.columns))
            return {
                "metrics": {"recall_minority": 0.94, "f1": 0.9},
                "topk_metrics": [{"recall_minority": 0.94}],
                "importance": [{"feature": "TORQUE_DEVIATION", "importance": 0.6}],
            }

        runner, db, run_id = self.build(
            {
                "run_s1": lambda db, **kw: (_REPORT, None, {"total_tokens": 100}),
                "run_s2": lambda db, **kw: (_SCRIPT_OK, None, {"total_tokens": 100}),
                "run_s4": lambda db, **kw: (_verdict("pass"), None, {"total_tokens": 100}),
            },
            trainer=trainer,
        )
        result = runner.run_to_completion()
        self.assertEqual(result.status, "accepted")
        self.assertNotIn("DECIDE(判定结果)", seen_columns[0])
        # 档案留痕：排障与评审可见"标签列已被平台剥离"。
        with SessionLocal() as db2:
            memory = db2.get(AgentRun, run_id).memory_json
        self.assertEqual(
            memory["rounds"][0]["s3"]["target_excluded_from_features"],
            "DECIDE(判定结果)",
        )

    def test_s4_fail_carries_hints_into_next_round_s1(self):
        seen_memories = []

        def fake_s1(db, **kwargs):
            seen_memories.append(kwargs.get("prior_memory"))
            return _REPORT, None, {"total_tokens": 100}

        verdicts = ["fail", "pass"]

        def fake_s4(db, **kwargs):
            return _verdict(verdicts.pop(0), hints=["补充分组特征"]), None, {"total_tokens": 100}

        runner, db, _ = self.build(
            {
                "run_s1": fake_s1,
                "run_s2": lambda db, **kw: (_SCRIPT_OK, None, {"total_tokens": 100}),
                "run_s4": fake_s4,
            }
        )
        result = runner.run_to_completion()
        self.assertEqual(result.status, "accepted")
        self.assertEqual(result.round_count, 2)
        self.assertIsNone(seen_memories[0])
        self.assertIsNotNone(seen_memories[1])
        self.assertIn("补充分组特征", str(seen_memories[1]["hints"]))

    def test_s2_non_convergence_escalates_with_attempts(self):
        def fake_s2(db, **kwargs):
            return None, "contract_violation: bad", {"total_tokens": 10}

        runner, db, _ = self.build(
            {
                "run_s1": lambda db, **kw: (_REPORT, None, {"total_tokens": 10}),
                "run_s2": fake_s2,
            }
        )
        result = runner.run_to_completion()
        self.assertEqual(result.status, "waiting_escalate")
        self.assertEqual(result.error_code, "AGENT_S2_NOT_CONVERGED")
        self.assertEqual(len(result.memory_json["rounds"][0]["s2_attempts"]), 8)

    def test_same_error_three_times_triggers_meta_hint(self):
        meta_flags = []

        def fake_s2(db, **kwargs):
            meta_flags.append(kwargs.get("meta_hint"))
            return None, "contract_violation: bad", {"total_tokens": 10}

        runner, db, _ = self.build(
            {
                "run_s1": lambda db, **kw: (_REPORT, None, {"total_tokens": 10}),
                "run_s2": fake_s2,
            }
        )
        runner.run_to_completion()
        self.assertEqual(len(meta_flags), 8)
        self.assertFalse(any(meta_flags[:3]))
        self.assertTrue(all(meta_flags[3:]))

    def test_token_budget_fuse_escalates(self):
        runner, db, _ = self.build(
            {
                "run_s1": lambda db, **kw: (_REPORT, None, {"total_tokens": 1000}),
                "run_s2": lambda db, **kw: (_SCRIPT_OK, None, {"total_tokens": 1000}),
            },
            run_kwargs={"token_budget": 1500},
        )
        result = runner.run_to_completion()
        self.assertEqual(result.status, "waiting_escalate")
        self.assertEqual(result.error_code, "AGENT_TOKEN_BUDGET_EXCEEDED")

    def test_s1_llm_failure_gets_distinct_code_and_persisted_detail(self):
        """486ea7f9 回归：LLM 层失败（超时）不得误报为契约失败，且原因必须落档案。"""
        detail = "llm_call_failed: ReadTimeout: timed out"
        runner, db, _ = self.build(
            {"run_s1": lambda db, **kw: (None, detail, {})}
        )
        result = runner.run_to_completion()
        self.assertEqual(result.status, "waiting_escalate")
        self.assertEqual(result.error_code, "AGENT_S1_LLM_FAILED")
        escalation = result.memory_json["escalation"]
        self.assertEqual(escalation["code"], "AGENT_S1_LLM_FAILED")
        self.assertEqual(escalation["detail"], detail)
        self.assertEqual(escalation["round"], 1)

    def test_s1_contract_violation_keeps_code_and_carries_detail(self):
        runner, db, _ = self.build(
            {"run_s1": lambda db, **kw: (None, "contract_violation: missing domain", {})}
        )
        result = runner.run_to_completion()
        self.assertEqual(result.status, "waiting_escalate")
        self.assertEqual(result.error_code, "AGENT_S1_CONTRACT_FAILED")
        self.assertEqual(
            result.memory_json["escalation"]["detail"],
            "contract_violation: missing domain",
        )

    def test_gate_failure_never_consults_review_and_bounded_rounds(self):
        s4_calls = []

        def fake_s4(db, **kwargs):
            s4_calls.append(1)
            return _verdict("pass"), None, {"total_tokens": 10}

        def trainer_weak(feature_df, y, hints):
            return {
                "metrics": {"recall_minority": 0.50},
                "topk_metrics": [{"recall_minority": 0.95}, {"recall_minority": 0.50}],
                "importance": [{"feature": "DECIDE_ONE", "importance": 0.9}],
            }

        runner, db, _ = self.build(
            {
                "run_s1": lambda db, **kw: (_REPORT, None, {"total_tokens": 10}),
                "run_s2": lambda db, **kw: (_SCRIPT_OK, None, {"total_tokens": 10}),
                "run_s4": fake_s4,
            },
            trainer=trainer_weak,
        )
        result = runner.run_to_completion()
        self.assertEqual(result.status, "waiting_escalate")
        self.assertEqual(result.error_code, "AGENT_MAX_ROUNDS")
        self.assertEqual(result.round_count, 3)
        # The review was never consulted: gates veto before the LLM runs.
        self.assertEqual(s4_calls, [])
        hints = result.memory_json["rounds"][0]["hints"]
        self.assertTrue(any("recall_minority" in hint for hint in hints))
        self.assertTrue(any("leakage_in_top10" in hint for hint in hints))


_ANOMALY_REPORT = AnalysisReport(
    domain_hypothesis="tightening",
    domain_reasoning="无监督正常性画像",
    focus_channels=[{"name": "torque", "columns": ["ACTUAL_TORQUE"], "why": "主参数"}],
    expected_important_features=[
        {"name_hint": "ACTUAL_TORQUE", "reason": "主导离群分数", "priority": "high"}
    ],
    leakage_suspects=[{"column": "DECIDE_ONE", "why": "疑似结果标签列，须剔除"}],
    feature_engineering_brief="剔除标签列与常数列，保留数值参数",
)


def _trainer_anomaly_passing(feature_df, y, hints):
    """无监督训练器 fake：形状与 anomaly_trainer 对齐（y 恒 None）。"""
    assert y is None, "无监督任务 S3 必须传 y=None"
    assert hints.get("task_type") == "anomaly"
    from sklearn.ensemble import IsolationForest
    from sklearn.pipeline import Pipeline
    from sklearn.preprocessing import StandardScaler

    model = Pipeline([
        ("scaler", StandardScaler()),
        ("detector", IsolationForest(n_estimators=20, random_state=0)),
    ]).fit(feature_df)
    return {
        "metrics": {
            "synthetic_auc": 0.92,
            "perturbation_recall": 0.55,
            "normal_fpr": 0.01,
            "stability": 0.9,
        },
        "topk_metrics": [{"synthetic_auc": 0.92}, {"synthetic_auc": 0.88}],
        "importance": [],
        "minority_test_count": None,
        "evaluation": {"threshold_score": 0.0},
        "champion_model": model,
        "champion_features": [str(name) for name in feature_df.columns],
        "champion_algorithm": "iforest",
    }


class TestAgentRunnerAnomaly(RunnerHarness, unittest.TestCase):
    """无监督分支（技术方案 §3.4）：范式门禁/hints/y=None 全链。"""

    def build_anomaly(self, trainer=_trainer_anomaly_passing, extra_patches=None):
        patches = {
            "run_s1": lambda db, **kw: (
                (kw.get("task_type") == "anomaly") and _ANOMALY_REPORT or _REPORT,
                None,
                {"total_tokens": 100},
            ),
            "run_s2": lambda db, **kw: (_SCRIPT_OK, None, {"total_tokens": 100}),
            "run_s4": lambda db, **kw: (_verdict("pass"), None, {"total_tokens": 100}),
        }
        patches.update(extra_patches or {})
        return self.build(
            patches,
            run_kwargs={
                "target_column": None,
                "guidance_json": {"task_type": "anomaly", "modeling": {"contamination": 0.02}},
            },
            trainer=trainer,
            # executor 真实链路从 run.guidance_json 读 guidance 传入 runner；
            # harness 直接对齐该形态（guidance 携带范式）。
            guidance={"task_type": "anomaly", "modeling": {"contamination": 0.02}},
        )

    def test_anomaly_task_reaches_accepted_without_target(self):
        """无监督任务全链：无目标列、anomaly 门禁键、范式随 guidance 固化。"""
        runner, db, run_id = self.build_anomaly()
        # 冠军物化依赖 artifact 存储配置——patch 掉（本用例验证全链状态机）
        with mock.patch.object(runner_module.AgentRunner, "_persist_s3_champion", lambda self_, _result: None):
            result = runner.run_to_completion()
        self.assertEqual(result.status, "accepted")
        self.assertIsNone(result.target_column)
        entry = result.memory_json["rounds"][0]
        self.assertEqual(entry["s4"]["gates"].get("synthetic_auc"), 0.85)
        self.assertIn("normal_fpr", entry["s4"]["gates"])
        self.assertNotIn("recall_minority", entry["s4"]["gates"])
        self.assertTrue(entry["s4"]["gate_passed"])

    def test_known_anomaly_rows_validated_after_gate_pass(self):
        """已知异常样本弱监督验证（技术方案 §3.4 S4）：门禁通过后冠军模型
        对样本打分，检出率进 metrics 与 s4 digest 证据（不设一票否决）。"""
        captured = {}

        def fake_s4(db, **kwargs):
            captured["metrics"] = kwargs.get("metrics")
            return _verdict("pass"), None, {"total_tokens": 10}

        runner, db, _ = self.build_anomaly(
            extra_patches={
                "run_s4": lambda db, **kw: (
                    captured.__setitem__("metrics", kw.get("metrics")) or (_verdict("pass"), None, {"total_tokens": 10})
                ),
            },
        )
        # guidance 注入已知异常样本（evaluation 段）
        runner.guidance["evaluation"] = {
            "known_anomaly_rows": [
                {"s1": 9.0, "s2": -8.0, "s3": 1.0, "s4": -1.0},
                {"s1": -7.0, "s2": 6.0, "s3": -1.0, "s4": 1.0},
            ],
        }
        # 冠军物化依赖 artifact 存储配置——本用例只验证检出率进 metrics，patch 掉
        with mock.patch.object(
            runner_module.AgentRunner, "_persist_s3_champion", lambda self_, _result: None,
        ):
            result = runner.run_to_completion()
        self.assertEqual(result.status, "accepted")
        # 检出率进 S4 评审看到的 metrics（LLM 评审与证据面板同源）
        self.assertIn("known_anomaly_detection_rate", captured["metrics"])
        entry = result.memory_json["rounds"][0]
        validation = entry["s4"].get("known_anomaly_validation")
        self.assertIsNotNone(validation)
        self.assertEqual(validation["sample_count"], 2)
        self.assertIn("detection_rate", validation)
        self.assertIn("per_row", validation)

    def test_anomaly_gate_failure_loops_with_anomaly_metric_hint(self):
        """synthetic_auc 门禁未过 → 打回 S1，hints 带 anomaly 指标名。"""
        s4_calls = []

        def trainer_weak(feature_df, y, hints):
            return {
                "metrics": {
                    "synthetic_auc": 0.60,
                    "perturbation_recall": 0.1,
                    "normal_fpr": 0.4,
                    "stability": 0.5,
                },
                "topk_metrics": [{"synthetic_auc": 0.60}],
                "importance": [],
                "minority_test_count": None,
            }

        runner, db, _ = self.build_anomaly(
            trainer=trainer_weak,
            extra_patches={
                "run_s4": lambda db, **kw: (s4_calls.append(1) or (_verdict("pass"), None, {"total_tokens": 10})),
            },
        )
        result = runner.run_to_completion()
        self.assertEqual(result.status, "waiting_escalate")
        self.assertEqual(result.error_code, "AGENT_MAX_ROUNDS")
        # 评审从未被咨询：门禁在 LLM 之前一票否决（与监督侧同语义）。
        self.assertEqual(s4_calls, [])
        hints = result.memory_json["rounds"][0]["hints"]
        self.assertTrue(any("synthetic_auc" in hint for hint in hints))
        self.assertTrue(any("normal_fpr" in hint for hint in hints))

    def test_anomaly_reverse_fpr_gate_blocks_high_false_positive_rate(self):
        """normal_fpr 反向门禁（越低越好）：误报率超阈值必须被拦。"""
        def trainer_leaky(feature_df, y, hints):
            return {
                "metrics": {
                    "synthetic_auc": 0.95,
                    "perturbation_recall": 0.8,
                    "normal_fpr": 0.30,
                    "stability": 0.9,
                },
                "topk_metrics": [{"synthetic_auc": 0.95}],
                "importance": [],
                "minority_test_count": None,
            }

        runner, db, _ = self.build_anomaly(trainer=trainer_leaky)
        result = runner.run_to_completion()
        self.assertEqual(result.status, "waiting_escalate")
        hints = result.memory_json["rounds"][0]["hints"]
        self.assertTrue(any("normal_fpr" in hint for hint in hints))
