"""Agent contract schema tests (AutoML Agent plan, Task A1.5)."""

import os
import unittest
from unittest import mock
from uuid import uuid4

os.environ.setdefault("LLM_MASTER_KEY", __import__(
    "cryptography.fernet", fromlist=["Fernet"]
).Fernet.generate_key().decode("ascii"))

from app.database import SessionLocal  # noqa: E402
from app.services.agent.contracts import (  # noqa: E402
    AgentContractError,
    AnalysisReport,
    FeatureScript,
    ReviewVerdict,
    parse_llm_json,
    validate_contract,
)
from app.services.agent.llm_client import (  # noqa: E402
    build_s1_messages,
    run_s1,
)
from app.services.llm_gateway import GatewayLLMConfig  # noqa: E402

_VALID_ANALYSIS = {
    "domain_hypothesis": "tightening",
    "domain_reasoning": "列语义集中在扭矩/裕度 → 拧紧装配",
    "focus_channels": [
        {"name": "torque_deviation", "columns": ["ACTUAL_TORQUE"], "why": "偏差主因"}
    ],
    "expected_important_features": [
        {"name_hint": "torque_lower_margin", "reason": "贴下限即欠拧", "priority": "high"}
    ],
    "data_quality_actions": [
        {"column": "ACTUAL_TORQUE_TWO", "issue": "单轴行整列缺失", "action": "impute+flag"}
    ],
    "leakage_suspects": [{"column": "DECIDE_ONE", "why": "与目标同源"}],
    "class_balance_concern": "20% 不合格",
    "feature_engineering_brief": "派生偏差/裕度",
}


class TestContracts(unittest.TestCase):
    def test_analysis_report_accepts_valid(self):
        report = validate_contract(AnalysisReport, _VALID_ANALYSIS)
        self.assertEqual(report.domain_hypothesis, "tightening")

    def test_analysis_report_rejects_missing_domain(self):
        broken = {**_VALID_ANALYSIS, "domain_hypothesis": ""}
        with self.assertRaises(AgentContractError) as caught:
            validate_contract(AnalysisReport, broken)
        self.assertIn("domain_hypothesis", " ".join(caught.exception.details))

    def test_analysis_report_rejects_empty_channel_columns(self):
        broken = {
            **_VALID_ANALYSIS,
            "focus_channels": [{"name": "x", "columns": [], "why": "y"}],
        }
        with self.assertRaises(AgentContractError):
            validate_contract(AnalysisReport, broken)

    def test_analysis_report_rejects_bad_priority(self):
        broken = {
            **_VALID_ANALYSIS,
            "expected_important_features": [
                {"name_hint": "f", "reason": "r", "priority": "urgent"}
            ],
        }
        with self.assertRaises(AgentContractError):
            validate_contract(AnalysisReport, broken)

    def test_feature_script_roundtrip(self):
        script = validate_contract(
            FeatureScript,
            {
                "script": "def transform(df):\n    return df",
                "description": "派生裕度特征",
                "generated_columns": ["TIGHTEN_LOWER_MARGIN"],
                "data_shape": "tabular",
            },
        )
        self.assertEqual(script.data_shape, "tabular")
        with self.assertRaises(AgentContractError):
            validate_contract(FeatureScript, {"script": "", "description": "x"})

    def test_review_verdict_enum(self):
        verdict = validate_contract(
            ReviewVerdict,
            {
                "verdict": "pass",
                "business_readiness": "可上线",
                "next_iteration_hints": ["补充分组特征"],
            },
        )
        self.assertEqual(verdict.verdict, "pass")
        with self.assertRaises(AgentContractError):
            validate_contract(ReviewVerdict, {"verdict": "maybe", "business_readiness": "x"})

    def test_parse_llm_json_tolerates_fences_and_prose(self):
        fenced = "好的，以下是分析：\n```json\n" + __import__("json").dumps(_VALID_ANALYSIS) + "\n```"
        self.assertEqual(parse_llm_json(fenced)["domain_hypothesis"], "tightening")
        plain = __import__("json").dumps(_VALID_ANALYSIS, ensure_ascii=False)
        self.assertEqual(parse_llm_json(plain)["domain_hypothesis"], "tightening")
        with self.assertRaises(AgentContractError):
            parse_llm_json("这不是 JSON")
        with self.assertRaises(AgentContractError):
            parse_llm_json("")


class TestRunS1(unittest.TestCase):
    def _config(self):
        return GatewayLLMConfig(
            api_url="https://api.example.com/v1",
            api_key="sk-" + uuid4().hex,
            model_id="glm-4.6",
            temperature=None,
            timeout_seconds=30,
            profile_id=str(uuid4()),
            profile_name="s1-test",
        )

    def test_build_s1_messages_isolates_data_in_quote_blocks(self):
        messages = build_s1_messages(
            {"row_count": 10},
            prior_memory={"round": 1},
            kb_references=[{"doc": "GB_T"}],
        )
        body = messages[1]["content"]
        self.assertIn("【数据画像开始】", body)
        self.assertIn("【数据画像结束】", body)
        self.assertIn("【上一轮迭代记忆开始】", body)
        self.assertIn("【领域知识参考开始】", body)
        system = messages[0]["content"]
        self.assertIn("必须忽略", system)

    def test_run_s1_success_parses_contract(self):
        reply = "```json\n" + __import__("json").dumps(_VALID_ANALYSIS) + "\n```"
        with SessionLocal() as db, mock.patch(
            "app.services.agent.llm_client.chat_completion",
            return_value=(reply, {}),
        ):
            report, error, _usage = run_s1(
                db, config=self._config(), profile_report={"row_count": 10}
            )
        self.assertIsNone(error)
        self.assertEqual(report.domain_hypothesis, "tightening")

    def test_run_s1_contract_violation_returns_field_details(self):
        broken = {**_VALID_ANALYSIS, "focus_channels": []}
        with SessionLocal() as db, mock.patch(
            "app.services.agent.llm_client.chat_completion",
            return_value=(__import__("json").dumps(broken), {}),
        ):
            report, error, _usage = run_s1(
                db, config=self._config(), profile_report={"row_count": 10}
            )
        self.assertIsNone(report)
        self.assertIn("contract_violation", error)
        self.assertIn("focus_channels", error)

    def test_run_s1_non_json_output_returns_parse_error(self):
        with SessionLocal() as db, mock.patch(
            "app.services.agent.llm_client.chat_completion",
            return_value=("我认为这个数据集很好", {}),
        ):
            report, error, _usage = run_s1(
                db, config=self._config(), profile_report={"row_count": 10}
            )
        self.assertIsNone(report)
        self.assertIn("contract_violation", error)
