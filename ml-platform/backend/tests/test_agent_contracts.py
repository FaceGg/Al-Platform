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
    build_s4_messages,
    run_s1,
    run_s4,
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

    def test_review_alignment_coerces_numeric_observed(self):
        """LLM 常把 observed 写成裸数字（真机 7c9415b1 alignment[8..11] 违约）；
        数字/布尔语义无损转字符串收单，结构违约（null/列表/空串）仍拒收。"""
        verdict = validate_contract(
            ReviewVerdict,
            {
                "verdict": "pass",
                "alignment": [
                    {"expected": "RON1 重要性高", "observed": 0.99, "aligned": True},
                    {"expected": "WLD 差值特征", "observed": 2, "aligned": True},
                ],
                "business_readiness": "可上线",
            },
        )
        self.assertEqual(verdict.alignment[0].observed, "0.99")
        self.assertEqual(verdict.alignment[1].observed, "2")
        for bad in (None, ["0.99"], ""):
            with self.assertRaises(AgentContractError):
                validate_contract(
                    ReviewVerdict,
                    {
                        "verdict": "pass",
                        "alignment": [
                            {"expected": "x", "observed": bad, "aligned": True}
                        ],
                        "business_readiness": "可上线",
                    },
                )

    def test_review_verdict_coerces_object_surprises_and_readiness(self):
        """surprises/hints 常被 LLM 写成对象列表、business_readiness 写成
        对象（真机 c79ad389/5e595f92 两轮 S4 契约失败实锤）：提取文本收单，
        只放宽载体形态；verdict 枚举红线不受影响。"""
        verdict = validate_contract(
            ReviewVerdict,
            {
                "verdict": "escalate",
                "surprises": [
                    {"finding": "重要性第一名是日期特征", "severity": "high"},
                    42,
                    "已是字符串的发现",
                ],
                "business_readiness": {"ready": False, "reason": "需人工确认"},
                "next_iteration_hints": [{"hint": "剔除日期列"}],
            },
        )
        self.assertEqual(verdict.verdict, "escalate")
        self.assertTrue(all(isinstance(x, str) for x in verdict.surprises))
        self.assertIn("重要性第一名是日期特征", verdict.surprises[0])
        self.assertIn("42", verdict.surprises[1])
        self.assertIn("需人工确认", verdict.business_readiness)
        self.assertEqual(verdict.next_iteration_hints, ["剔除日期列"])

    def test_review_verdict_still_rejects_broken_readiness(self):
        """business_readiness 为 None（字段缺失）仍拒收；空容器收为 JSON
        文本留档（载体放宽≠内容放行——verdict 枚举红线不受影响）。"""
        with self.assertRaises(AgentContractError):
            validate_contract(
                ReviewVerdict,
                {"verdict": "pass", "business_readiness": None},
            )
        ok = validate_contract(
            ReviewVerdict,
            {"verdict": "pass", "business_readiness": {}},
        )
        self.assertEqual(ok.business_readiness, "{}")

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
            return_value=(reply, {}, None),
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
            return_value=(__import__("json").dumps(broken), {}, None),
        ):
            report, error, _usage = run_s1(
                db, config=self._config(), profile_report={"row_count": 10}
            )
        self.assertIsNone(report)
        self.assertIn("contract_violation", error)

    def test_run_s1_sanitizes_overlong_fields_instead_of_rejecting(self):
        """273368c1 回归：column 字段被塞说明文字（>256 字符）不再整单拒收。"""
        import copy

        rambling = "该列语义说明" * 60  # > 256 字符
        payload = copy.deepcopy(_VALID_ANALYSIS)
        payload["data_quality_actions"].append(
            {"column": rambling, "issue": "说明误填入列名", "action": "drop"}
        )
        payload["leakage_suspects"].append(
            {"column": "OK_COL", "why": "正常条目但理由超长" * 400}
        )
        with SessionLocal() as db, mock.patch(
            "app.services.agent.llm_client.chat_completion",
            return_value=(__import__("json").dumps(payload), {}, None),
        ):
            report, error, _usage = run_s1(
                db, config=self._config(), profile_report={"row_count": 10}
            )
        self.assertIsNone(error)
        # 超长 column 的条目被丢弃；超长 why 被截断保留。
        self.assertEqual(len(report.data_quality_actions), 1)
        self.assertEqual(len(report.leakage_suspects), 2)
        self.assertLessEqual(len(report.leakage_suspects[1].why), 2000)

    def test_run_s1_keeps_one_channel_when_all_malformed(self):
        """必填列表（focus_channels ≥1）全超长时硬截断兜底，不整单拒收。"""
        payload = {
            **_VALID_ANALYSIS,
            "focus_channels": [
                {"name": "通道说明文字" * 30, "columns": ["A"], "why": "ok"}
            ],
        }
        with SessionLocal() as db, mock.patch(
            "app.services.agent.llm_client.chat_completion",
            return_value=(__import__("json").dumps(payload), {}, None),
        ):
            report, error, _usage = run_s1(
                db, config=self._config(), profile_report={"row_count": 10}
            )
        self.assertIsNone(error)
        self.assertEqual(len(report.focus_channels), 1)
        self.assertLessEqual(len(report.focus_channels[0].name), 64)

    def test_run_s1_normalizes_expected_features_without_name_hint(self):
        """c90901d0 回归：模型全部条目缺 name_hint（用 feature 别名）不再整单
        拒收——别名收单 + 纯字符串条目 + reason 别名 why 三种形态都救回。"""
        payload = {
            **_VALID_ANALYSIS,
            "expected_important_features": [
                {"feature": "TORQUE_DEV", "reason": "偏差主导"},          # 别名 feature
                "WLD_INDEX",                                              # 纯字符串
                {"name": "SPIKES", "why": "飞溅尖峰特征"},                # 别名 name + why
                {"reason": "无任何名称字段"},                              # 救不回 → 丢弃
            ],
        }
        with SessionLocal() as db, mock.patch(
            "app.services.agent.llm_client.chat_completion",
            return_value=(__import__("json").dumps(payload), {}, None),
        ):
            report, error, _usage = run_s1(
                db, config=self._config(), profile_report={"row_count": 10}
            )
        self.assertIsNone(error)
        hints = [item.name_hint for item in report.expected_important_features]
        self.assertEqual(hints, ["TORQUE_DEV", "WLD_INDEX", "SPIKES"])
        self.assertEqual(report.expected_important_features[1].reason, "WLD_INDEX")
        self.assertEqual(report.expected_important_features[2].reason, "飞溅尖峰特征")

    def test_run_s1_contract_repair_retry_self_heals(self):
        """契约失败修复回路（系统性方案）：第一次输出缺 name_hint → 把坏输出
        +具体校验错误喂回模型 → 第二次修正 → run_s1 成功；第二次调用必须
        携带修正指令。"""
        # 用「既有宽容归一化救不回」的形态触发修复回路：
        # focus_channels=[]（min_length=1，本地无兜底）
        bad = {**_VALID_ANALYSIS, "focus_channels": [], "expected_important_features": [{"reason": "无名称"}]}
        good = dict(_VALID_ANALYSIS)
        calls = []

        def fake_completion(db, *, config, messages, **kwargs):
            calls.append(messages)
            if len(calls) == 1:
                return (__import__("json").dumps(bad), {"total_tokens": 100}, None)
            # 修复调用：messages 末尾应是 assistant 坏输出 + user 修正指令
            assert messages[-1]["role"] == "user"
            assert "违反了 AnalysisReport 契约" in messages[-1]["content"]
            assert messages[-2]["role"] == "assistant"
            return (__import__("json").dumps(good), {"total_tokens": 50}, None)

        with SessionLocal() as db, mock.patch(
            "app.services.agent.llm_client.chat_completion_with_retry", side_effect=fake_completion
        ):
            report, error, usage = run_s1(
                db, config=self._config(), profile_report={"row_count": 10}
            )
        self.assertIsNone(error)
        self.assertIsNotNone(report)
        self.assertEqual(len(calls), 2)
        self.assertEqual(usage.get("total_tokens"), 150, "两次调用 token 应合并进预算")

    def test_run_s4_contract_repair_failure_keeps_raw_evidence(self):
        """修复重试仍失败：错误信息必须携带两次原始输出（线上可复盘，无需复现）。"""
        # bad1 用归一化救不回的形态：alignment 非列表（无 before-validator）
        bad1 = {"verdict": "pass", "alignment": "oops", "surprises": [], "business_readiness": "ok",
                "next_iteration_hints": []}
        bad2 = {"verdict": " banana", "alignment": [], "surprises": [], "business_readiness": "ok",
                "next_iteration_hints": []}
        calls = []

        def fake_completion(db, *, config, messages, **kwargs):
            calls.append(messages)
            return (__import__("json").dumps(bad1 if len(calls) == 1 else bad2), {}, None)

        with SessionLocal() as db, mock.patch(
            "app.services.agent.llm_client.chat_completion_with_retry", side_effect=fake_completion
        ):
            verdict, error, _usage = run_s4(
                db, config=self._config(), metrics={"recall_minority": 0.9},
                importance=[], expectations=[], gate_failures=[], round_number=1,
            )
        self.assertIsNone(verdict)
        self.assertIn("修复重试仍失败", error)
        self.assertIn("raw_first", error)
        self.assertIn("raw_retry", error)
        self.assertIn("banana", error)
        self.assertEqual(len(calls), 2)

    def test_run_s1_non_json_output_returns_parse_error(self):
        with SessionLocal() as db, mock.patch(
            "app.services.agent.llm_client.chat_completion",
            return_value=("我认为这个数据集很好", {}, None),
        ):
            report, error, _usage = run_s1(
                db, config=self._config(), profile_report={"row_count": 10}
            )
        self.assertIsNone(report)
        self.assertIn("contract_violation", error)
