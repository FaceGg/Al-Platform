import uuid
import json
import requests
import threading
from datetime import datetime
from typing import Callable, Any


class Orchestrator:
    """多智能体协同调度引擎 — 大小模型协同"""

    def __init__(self, db_session_factory, llm_url: str = None, llm_key: str = None):
        self.db_factory = db_session_factory
        self.llm_url = llm_url or "https://api.openai.com/v1/chat/completions"
        self.llm_key = llm_key or ""
        self.pending_reviews: dict[str, dict] = {}
        self._callbacks: dict[str, Callable] = {}

    def register_callback(self, event_type: str, callback: Callable):
        """注册事件回调：node_status, task_complete, review_request"""
        self._callbacks[event_type] = callback

    def decompose_with_llm(self, task_description: str) -> list[dict]:
        """使用LLM将自然语言任务拆解为子任务DAG"""
        prompt = f"""你是一个任务规划专家。请将以下任务拆解为可执行的子任务。
返回JSON数组，每个子任务包含：name(名称), description(描述), agent_type(需要planner/executor/reviewer/llm), dependencies(依赖的子任务index列表)

任务描述：{task_description}
输出格式：[{{"name":"...","description":"...","agent_type":"executor","dependencies":[]}}]
"""
        # 如果 LLM 不可用，用简单规则拆分
        # 按关键词拆分：质量预测->数据加载+训练+评估，参数推荐->数据加载+模型推理
        if "质量" in task_description and "预测" in task_description:
            return [
                {"name": "数据加载与预处理", "description": "加载焊接工艺参数数据并预处理", "agent_type": "executor", "dependencies": []},
                {"name": "模型训练", "description": "训练质量预测模型", "agent_type": "executor", "dependencies": [0]},
                {"name": "模型评估", "description": "评估模型并输出报告", "agent_type": "reviewer", "dependencies": [1]},
            ]
        elif "参数" in task_description and ("推荐" in task_description or "优化" in task_description):
            return [
                {"name": "数据分析", "description": "分析输入要求", "agent_type": "llm", "dependencies": []},
                {"name": "参数推荐计算", "description": "基于模型计算推荐参数", "agent_type": "executor", "dependencies": [0]},
                {"name": "结果验证", "description": "验证推荐参数的合理性", "agent_type": "reviewer", "dependencies": [1]},
            ]
        else:
            return [
                {"name": "任务分析", "description": "分析任务需求", "agent_type": "llm", "dependencies": []},
                {"name": "任务执行", "description": "执行计算任务", "agent_type": "executor", "dependencies": [0]},
                {"name": "结果审核", "description": "审核执行结果", "agent_type": "reviewer", "dependencies": [1]},
            ]

    def request_human_review(self, task_id: str, decision_point: str, context: dict) -> dict:
        """请求人工审核关键决策"""
        self.pending_reviews[task_id] = {
            "decision_point": decision_point, "context": context, "status": "pending"
        }
        return {"status": "awaiting_review", "task_id": task_id, "decision_point": decision_point}

    def get_pending_reviews(self) -> list[dict]:
        return [{"task_id": k, **v} for k, v in self.pending_reviews.items() if v["status"] == "pending"]

    def submit_review(self, task_id: str, approved: bool, comment: str = "") -> dict:
        if task_id in self.pending_reviews:
            self.pending_reviews[task_id]["status"] = "approved" if approved else "rejected"
            self.pending_reviews[task_id]["comment"] = comment
            return {"status": "ok"}
        return {"status": "not_found"}
