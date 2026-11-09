# -*- coding: utf-8 -*-
"""回归测试：cast-deployment engine 模式不得再因函数边界错位静默返回 null。

缺陷史（2026-11-09 发现）：e532aef2 连带提交把 _deploy_s3_champion 插入
cast_deployment 的 s3 分支与 engine 分支之间，engine 触发逻辑（配方解析→
数据集推导→触发重训 job）全部落入 _deploy_s3_champion 的 return 之后成为
死代码——POST /servitize/cast-deployment mode=engine 返回 201+null 且不建
job，E2E 一键部署链路在 engine 重铸路径静默失败。
"""

import ast
import unittest
import uuid
from pathlib import Path

import pytest  # noqa: F401  (仅供 ast 断言语义说明，未直接使用)

from app.database import Base, SessionLocal, engine  # noqa: E402
from app.api.agent_extras import cast_deployment  # noqa: E402

BASE_DIR = Path(__file__).resolve().parents[1]
EXTRAS_PATH = BASE_DIR / "app" / "api" / "agent_extras.py"


class TestCastDeploymentEngineReachable(unittest.TestCase):
    """engine 铸造触发代码必须位于 cast_deployment 函数体内且可达。"""

    @classmethod
    def setUpClass(cls):
        Base.metadata.create_all(bind=engine)

    def test_trigger_retrain_job_inside_cast_deployment(self):
        src = EXTRAS_PATH.read_text(encoding="utf-8")
        tree = ast.parse(src)
        funcs = {}
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                funcs[node.name] = node
        self.assertIn("cast_deployment", funcs)
        self.assertIn("_deploy_s3_champion", funcs)
        cast_src = ast.get_source_segment(src, funcs["cast_deployment"])
        # 触发重训 job 的调用必须在 cast_deployment 内（engine 分支可达）
        self.assertIn("trigger_retrain_job(", cast_src,
                      "engine 铸造触发逻辑不在 cast_deployment 内"
                      "（历史上落入 _deploy_s3_champion 的 return 之后）")
        champion_src = ast.get_source_segment(src, funcs["_deploy_s3_champion"])
        # _deploy_s3_champion 的 return 之后不得再有任何语句（死代码特征）
        last_return = max(
            node.lineno for node in ast.walk(funcs["_deploy_s3_champion"])
            if isinstance(node, ast.Return)
        )
        trailing = [
            node.lineno for node in ast.walk(funcs["_deploy_s3_champion"])
            if isinstance(node, ast.stmt) and node.lineno > last_return
        ]
        self.assertEqual(trailing, [], "_deploy_s3_champion 的 return 后存在死代码")

    def test_engine_mode_missing_recipe_raises_404(self):
        """engine 模式下配方不存在必须 404（证明 engine 分支可达执行）。"""
        db = SessionLocal()
        try:
            user = uuid.uuid4()  # 直接调用时鉴权用户仅用于审计字段
            with self.assertRaises(Exception) as ctx:
                cast_deployment(
                    type("P", (), {
                        "recipe_id": str(uuid.uuid4()),
                        "project_id": str(uuid.uuid4()),
                        "run_id": None,
                        "dataset_artifact_id": None,
                        "max_trials": 5,
                        "force": False,
                        "mode": "engine",
                    })(),
                    db=db,
                    current_user=user,
                )
            detail = getattr(ctx.exception, "detail", None)
            self.assertEqual(
                (getattr(ctx.exception, "status_code", None), detail),
                (404, {"code": "RECIPE_NOT_FOUND"}),
                "engine 分支未按预期执行（历史缺陷：静默返回 201+null）",
            )
        finally:
            db.close()
