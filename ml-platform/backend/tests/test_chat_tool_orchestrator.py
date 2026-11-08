"""白名单工具自然语言编排测试（mock LLM 网关，不发出真实调用）。

覆盖：名称解析（唯一/多义/零命中）、缺参追问往返、写类确认/取消、
复杂写类页面指引、路由失败降级普通聊天。
"""
import os
import unittest
from types import SimpleNamespace
from unittest import mock

os.environ.setdefault("LLM_MASTER_KEY", __import__(
    "cryptography.fernet", fromlist=["Fernet"]
).Fernet.generate_key().decode("ascii"))

from app.services import chat_tool_orchestrator as orch  # noqa: E402
from app.services.chat_tools import TOOL_PAGE_GUIDES  # noqa: E402


def _config():
    from app.services.llm_gateway import GatewayLLMConfig

    return GatewayLLMConfig(
        api_url="https://api.example.com/v1/x",
        api_key="sk-test",
        model_id="m1",
        temperature=None,
        timeout_seconds=60,
        profile_id=None,
        profile_name="t",
        provider="openai_compatible",
    )


def _user():
    return SimpleNamespace(id="00000000-0000-0000-0000-000000000001")


def _project_row(pid="00000000-0000-0000-0000-0000000000aa", name="点焊"):
    return SimpleNamespace(id=pid, name=name)


class TestResolvers(unittest.TestCase):
    def test_pick_unique(self):
        out = orch._pick([_project_row()], "点焊", "project_id", "项目")
        self.assertEqual(out["id"], "00000000-0000-0000-0000-0000000000aa")
        self.assertEqual(out["name"], "点焊")
        self.assertNotIn("question", out)

    def test_pick_zero_asks_back(self):
        out = orch._pick([], "拧紧", "project_id", "项目")
        self.assertIn("question", out)
        self.assertIn("拧紧", out["question"])

    def test_pick_multiple_lists_candidates(self):
        rows = [_project_row("1" * 32, "点焊"), _project_row("2" * 32, "点焊-2")]
        out = orch._pick(rows, "点焊", "project_id", "项目")
        self.assertIn("question", out)
        self.assertIn("点焊-2", out["question"])

    def test_extract_json_tolerates_wrapped_output(self):
        self.assertEqual(orch._extract_json('思考中... {"tool": "list_datasets", "params": {}}'), {"tool": "list_datasets", "params": {}})
        self.assertIsNone(orch._extract_json("no json here"))
        self.assertIsNone(orch._extract_json(""))


class TestOrchestrateFlow(unittest.TestCase):
    def setUp(self):
        self.user = _user()
        self.config = _config()
        # 启停配置读 DB；单测里无库，固定为全量可用（含 guided 复杂写类）
        self._enabled = mock.patch.object(
            orch, "_enabled_tools",
            return_value=set(orch.TOOL_PARAM_SPECS) | set(orch.TOOL_PAGE_GUIDES),
        )
        self._enabled.start()
        self.addCleanup(self._enabled.stop)

    def _route(self, tool=None, params=None):
        """Mock 意图路由 LLM 输出。"""
        payload = {"tool": tool, "params": params or {}}
        return mock.patch.object(
            orch, "_route_intent", return_value=payload if tool else {},
        )

    def _no_summary(self):
        return mock.patch.object(orch, "_summarize", side_effect=lambda *a, **k: "摘要文本")

    def test_chat_mode_when_route_misses(self):
        with self._route(None):
            out = orch.orchestrate(mock.MagicMock(), config=self.config, user=self.user,
                                   message="今天天气怎么样", tool_context=None)
        self.assertEqual(out.mode, "chat")

    def test_missing_required_param_clarifies(self):
        db = mock.MagicMock()
        with self._route("list_datasets", {}):
            out = orch.orchestrate(db, config=self.config, user=self.user,
                                   message="查一下数据集", tool_context=None)
        self.assertEqual(out.mode, "clarify")
        self.assertIn("项目", out.reply)
        self.assertEqual(out.tool_call["tool"], "list_datasets")
        self.assertEqual(out.tool_call["status"], "clarify")

    def test_name_resolution_failure_goes_back_as_question(self):
        db = mock.MagicMock()
        with self._route("list_datasets", {"project": "不存在的项目"}), \
             mock.patch.object(orch, "_resolve_project", return_value={"missing_value": "不存在的项目", "question": "没有找到名为「不存在的项目」的项目，请确认名称。"}):
            out = orch.orchestrate(db, config=self.config, user=self.user,
                                   message="看不存在的项目的数据集", tool_context=None)
        self.assertEqual(out.mode, "clarify")
        self.assertIn("没有找到", out.reply)

    def test_read_tool_executes_and_summarizes(self):
        db = mock.MagicMock()
        resolved = {"id": "9" * 32, "project_id": "9" * 32, "name": "点焊"}
        with self._route("list_datasets", {"project": "点焊"}), \
             mock.patch.object(orch, "_resolve_project", return_value=resolved), \
             self._no_summary(), \
             mock.patch.object(orch, "execute_tool", return_value={"items": [], "total": 0}) as exec_mock:
            out = orch.orchestrate(db, config=self.config, user=self.user,
                                   message="看点焊项目的数据集", tool_context=None)
        self.assertEqual(out.mode, "done")
        self.assertEqual(out.reply, "摘要文本")
        exec_mock.assert_called_once()
        self.assertEqual(exec_mock.call_args.kwargs["tool"], "list_datasets")
        self.assertEqual(exec_mock.call_args.kwargs["params"], {"project_id": "9" * 32})

    def test_write_tool_requires_confirm_then_confirmed_word_executes(self):
        db = mock.MagicMock()
        resolved = {"id": "8" * 32, "api_id": "8" * 32, "name": "点焊预测"}
        with self._route("offline_api", {"api": "点焊预测"}), \
             mock.patch.object(orch, "_resolve_api", return_value=resolved):
            out = orch.orchestrate(db, config=self.config, user=self.user,
                                   message="下线点焊预测这个API", tool_context=None)
        self.assertEqual(out.mode, "confirm")
        self.assertIn("确认", out.reply)
        # 用户回复「确认」→ 执行
        with self._no_summary(), \
             mock.patch.object(orch, "execute_tool", return_value={"api": "点焊预测", "status": "offline", "changed": True}) as exec_mock:
            out2 = orch.orchestrate(db, config=self.config, user=self.user, message="确认",
                                    tool_context=out.tool_call)
        self.assertEqual(out2.mode, "done")
        exec_mock.assert_called_once()
        self.assertTrue(exec_mock.call_args.kwargs["confirmed"])

    def test_write_tool_confirm_cancelled_by_word(self):
        db = mock.MagicMock()
        with mock.patch.object(orch, "execute_tool") as exec_mock:
            out = orch.orchestrate(db, config=self.config, user=self.user, message="取消",
                                   tool_context={"tool": "offline_api", "params": {"api_id": "8" * 32}, "status": "confirm"})
        self.assertEqual(out.mode, "clarify")
        self.assertIn("已取消", out.reply)
        exec_mock.assert_not_called()

    def test_complex_write_tool_returns_page_guide(self):
        db = mock.MagicMock()
        with self._route("create_automl_task", {}):
            out = orch.orchestrate(db, config=self.config, user=self.user,
                                   message="帮我创建一个自动建模任务", tool_context=None)
        self.assertEqual(out.mode, "guided")
        self.assertIn(TOOL_PAGE_GUIDES["create_automl_task"][:12], out.reply)

    def test_clarify_context_merges_params_across_turns(self):
        db = mock.MagicMock()
        # 第二轮：用户回答「点焊」，路由只带回 project
        with self._route("list_datasets", {"project": "点焊"}), \
             mock.patch.object(orch, "_resolve_project", return_value={"id": "7" * 32, "project_id": "7" * 32, "name": "点焊"}), \
             self._no_summary(), \
             mock.patch.object(orch, "execute_tool", return_value={"items": [{"name": "d1"}], "total": 1}) as exec_mock:
            out = orch.orchestrate(db, config=self.config, user=self.user, message="点焊",
                                   tool_context={"tool": "list_datasets", "params": {}, "status": "clarify"})
        self.assertEqual(out.mode, "done")
        self.assertEqual(exec_mock.call_args.kwargs["params"], {"project_id": "7" * 32})


if __name__ == "__main__":
    unittest.main()
