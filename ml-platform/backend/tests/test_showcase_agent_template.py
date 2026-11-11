# -*- coding: utf-8 -*-
"""回归测试：servitize 智能体编排模板的实时大屏支持。

背景（2026-11-09 点焊 E2E）：servitize/publish 产出的编排是六算子智能体链
（api_input→python_script→load_deployment_model→apply_model→
append_error_dataset→agent_retrain_threshold），而 showcase-status 只认可
引擎七算子模板——大屏「编排 API 实时」连接即 409 SHOWCASE_NOT_ELIGIBLE。
修复：算子集合双白名单（引擎/智能体），报错行判定回退到回流节点
error_matched，重训引用兼容配方重放 AgentRun，阈值行读取 agent 节点参数。
"""

import pathlib
import unittest

BACKEND = pathlib.Path(__file__).resolve().parents[1]
PLATFORM_API = BACKEND / "app" / "api" / "platform_api.py"

AGENT_SET = {
    "api_input", "python_script", "load_deployment_model", "apply_model",
    "append_error_dataset", "agent_retrain_threshold",
}


class TestShowcaseAgentTemplate(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import app.operators  # noqa: F401  触发算子注册（独立子进程运行时注册表为空）
        from app.api.platform_api import (
            SHOWCASE_OPERATOR_SET, SHOWCASE_OPERATOR_SET_AGENT, _showcase_eligible,
        )
        cls.legacy_set = SHOWCASE_OPERATOR_SET
        cls.agent_set = SHOWCASE_OPERATOR_SET_AGENT
        cls.eligible = staticmethod(_showcase_eligible)

    def test_agent_operator_set_supported(self):
        self.assertEqual(self.agent_set, AGENT_SET)
        nodes = [{"operator_id": op} for op in sorted(self.agent_set)]
        self.assertTrue(self.eligible(nodes))

    def test_legacy_operator_set_still_supported(self):
        nodes = [{"operator_id": op} for op in sorted(self.legacy_set)]
        self.assertTrue(self.eligible(nodes))

    def test_mutated_graph_rejected(self):
        nodes = [{"operator_id": op} for op in sorted(self.agent_set)]
        nodes.append({"operator_id": "notify_admins"})
        self.assertFalse(self.eligible(nodes))
        self.assertFalse(self.eligible([]))

    def test_error_row_hit_falls_back_to_reflow_results(self):
        """invoke 留痕：无 condition 节点时由回流节点 error_matched 判定。"""
        src = PLATFORM_API.read_text(encoding="utf-8")
        self.assertIn("error_matched", src)
        self.assertIn('"append_error_dataset"', src)
        self.assertIn('"agent_retrain_threshold"', src)

    def test_threshold_rows_reads_agent_node(self):
        from app.api.platform_api import _threshold_rows
        nodes = [{"operator_id": "agent_retrain_threshold",
                  "params": {"threshold_rows": 12}}]
        self.assertEqual(_threshold_rows(nodes), 12)
        self.assertEqual(_threshold_rows([{"operator_id": "other"}]), 3)

    def test_publish_strips_stale_template_params(self):
        """模板行先于算子参数改动创建时遗留未声明参数（实测 error_classes），
        实例化必须按算子当前参数集防御性过滤——invoke DAG 校验曾每次失败。"""
        src = (BACKEND / "app" / "services" / "agent" / "orchestration_publish.py").read_text(encoding="utf-8")
        self.assertIn("OperatorRegistry.get(node.operator_id)", src)
        # 剔除逻辑出现在 publish 的节点拷贝循环里（而非仅 import）
        self.assertIn("unknown", src)
        # 根契约：append_error_dataset 参数封闭集不含 error_classes
        from app.engine.registry import OperatorRegistry
        operator = OperatorRegistry.get("append_error_dataset")
        declared = {spec.name for spec in (operator.parameters or [])}
        self.assertNotIn("error_classes", declared)


if __name__ == "__main__":
    unittest.main()
