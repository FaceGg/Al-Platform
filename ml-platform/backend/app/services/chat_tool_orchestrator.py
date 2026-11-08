"""对话工具自然语言编排（白名单工具 §15 的对话入口）。

用户在 AI 对话里用自然语言发起白名单工具操作（例：「查一下点焊项目的数据
集」）。编排器负责：

1. 意图路由：LLM 结构化输出判断是否命中工具目录并抽取参数；
2. 参数补齐：缺必填参数时生成追问（前端把 tool_call 状态带回，用户回答
   合并后重新校验）；
3. 名称解析：把用户口中的名称（「点焊」「train_v2_full」）确定性解析成
   平台 ID（DB 参数绑定查询；解析不到或歧义时追问）；
4. 执行与总结：读类直接执行；写类必须经过一轮显式文字确认；工具结果再
   由 LLM 总结成自然语言答复。

不做对话执行的复杂写类（create_automl_task/create_loop_task/
publish_workflow_api）返回页面指引——诚实降级，不假支持。
"""
from __future__ import annotations

import json
import re
from uuid import UUID

from sqlalchemy.orm import Session

from app.services.chat_tools import (
    TOOL_CATALOG,
    TOOL_PAGE_GUIDES,
    TOOL_PARAM_SPECS,
    execute_tool,
)

# 用户确认/取消的词表（confirm 状态下不走 LLM，行为确定）
CONFIRM_WORDS = {"确认", "确定", "执行", "是", "是的", "好", "好的", "可以", "对", "继续", "yes", "ok", "y"}
CANCEL_WORDS = {"取消", "算了", "不", "不用", "不了", "取消掉", "no", "cancel"}


class ToolOrchestration:
    """编排结果：mode 决定 /chat 的分支，reply 为给用户的答复文本。"""

    def __init__(self, mode: str, reply: str, tool_call: dict | None = None):
        self.mode = mode  # chat | clarify | confirm | done | guided
        self.reply = reply
        self.tool_call = tool_call


def _enabled_tools(db: Session) -> set[str]:
    """管理员停用的工具不进编排目录（与执行层同一份配置）。"""
    from app.models.platform_option import get_option

    disabled = set(get_option(db, "chat_tools_disabled", []) or [])
    return set(TOOL_PARAM_SPECS) - disabled


def _routing_prompt(message: str, pending: dict | None) -> str:
    lines = ["你可以调用以下白名单工具（tool: 参数说明）："]
    for tool in sorted(TOOL_PARAM_SPECS):
        specs = TOOL_PARAM_SPECS[tool]
        params = ", ".join(
            f"{name}({'必填' if spec.get('required') else '可选'})" for name, spec in specs.items()
        )
        lines.append(f"- {tool}（{TOOL_CATALOG[tool]['label']}）：{params}")
    lines += [
        "- create_automl_task（创建自动建模任务）/ create_loop_task（创建闭环任务）/ publish_workflow_api（发布工作流为API）：参数复杂，同样识别意图",
        "",
        "根据用户消息判断：命中工具则输出 JSON（只输出 JSON，不要多余文字）：",
        '{"tool": "<tool名>", "params": {"<参数名>": "<从用户消息抽取的值，抽取不到就不要写该键>"}}',
        "未命中任何工具则输出：{\"tool\": null}",
        "",
        "注意：参数值用用户原话中的名称/文本，不要自己编造 ID。",
    ]
    if pending:
        lines += [
            "",
            f"当前有一个待补全的工具调用：{pending.get('tool')}，已收集参数：{json.dumps(pending.get('params') or {}, ensure_ascii=False)}。"
            "用户这条消息很可能是在回答缺的参数——优先并入该工具的参数后输出。",
        ]
    lines += ["", f"用户消息：{message}"]
    return "\n".join(lines)


def _extract_json(text: str) -> dict | None:
    """宽容解析 LLM 输出中的 JSON 对象（推理型模型可能带前后缀文本）。"""
    if not text:
        return None
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        return None
    try:
        data = json.loads(match.group(0))
        return data if isinstance(data, dict) else None
    except ValueError:
        return None


def _route_intent(db: Session, config, message: str, pending: dict | None, actor) -> dict:
    """LLM 意图路由：{tool, params} 或空。LLM 不可用时返回 {}（走普通聊天）。"""
    from app.services.llm_gateway import chat_completion

    try:
        reply, _usage = chat_completion(
            db,
            config=config,
            messages=[
                {"role": "system", "content": "你是工具路由器，只输出 JSON。"},
                {"role": "user", "content": _routing_prompt(message, pending)},
            ],
            temperature=0.1,
            max_tokens=400,
            purpose="chat_tool_route",
            actor=actor,
        )
    except Exception:  # noqa: BLE001 - 路由失败降级普通聊天，不阻断对话
        return {}
    data = _extract_json(reply or "")
    if not data or not data.get("tool"):
        return {}
    tool = str(data.get("tool"))
    if tool not in TOOL_PARAM_SPECS:
        return {}
    params = data.get("params") if isinstance(data.get("params"), dict) else {}
    clean = {str(k): v for k, v in params.items() if v not in (None, "")}
    return {"tool": tool, "params": clean}


def _summarize(db: Session, config, actor, tool: str, params: dict, result) -> str:
    """工具结果 → 自然语言汇报；总结失败时回退 JSON 摘要（不吞结果）。"""
    from app.services.llm_gateway import chat_completion

    digest = json.dumps(result, ensure_ascii=False, default=str)[:6000]
    label = TOOL_CATALOG[tool]["label"]
    try:
        reply, _usage = chat_completion(
            db,
            config=config,
            messages=[
                {
                    "role": "system",
                    "content": "你是平台助手。把工具执行结果整理成简洁中文汇报：先一句话结论，再列关键条目（最多 8 条）。不要编造结果里没有的信息。",
                },
                {"role": "user", "content": f"工具「{label}」参数 {json.dumps(params, ensure_ascii=False)} 执行结果：\n{digest}"},
            ],
            temperature=0.3,
            max_tokens=800,
            purpose="chat_tool_summary",
            actor=actor,
        )
        if reply and reply.strip():
            return reply.strip()
    except Exception:  # noqa: BLE001 - 总结失败回退原文摘要
        pass
    return f"「{label}」执行完成：\n{digest}"


# ---------------------------------------------------------------------------
# 名称 → ID 的确定性解析（DB 参数绑定查询；精确名优先，前缀模糊兜底）
# ---------------------------------------------------------------------------

def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", r"\%").replace("_", r"\_")


def _resolve_project(db: Session, user, value: str) -> dict:
    from app.models.project import Project

    rows = (
        db.query(Project)
        .filter(Project.owner_id == user.id, Project.name == value)
        .all()
    ) or (
        db.query(Project)
        .filter(
            Project.owner_id == user.id,
            Project.name.ilike(f"{_escape_like(value)}%", escape="\\"),
        )
        .order_by(Project.created_at.asc())
        .limit(5)
        .all()
    )
    return _pick(rows, value, "project_id", "项目")


def _resolve_dataset(db: Session, user, value: str, project_id=None) -> dict:
    from app.models.artifact import Artifact

    query = db.query(Artifact).filter(
        Artifact.type == "dataset",
        Artifact.archived_at.is_(None),
        Artifact.name == value,
    )
    if project_id:
        query = query.filter(Artifact.project_id == UUID(str(project_id)))
    rows = query.limit(5).all()
    if not rows:
        query = db.query(Artifact).filter(
            Artifact.type == "dataset",
            Artifact.archived_at.is_(None),
            Artifact.name.ilike(f"{_escape_like(value)}%", escape="\\"),
        )
        if project_id:
            query = query.filter(Artifact.project_id == UUID(str(project_id)))
        rows = query.order_by(Artifact.created_at.desc()).limit(5).all()
    return _pick(rows, value, "dataset_id", "数据集")


def _resolve_recipe(db: Session, user, value: str) -> dict:
    from app.models.recipe import PipelineRecipe

    rows = db.query(PipelineRecipe).filter(PipelineRecipe.name == value).limit(5).all()
    if not rows:
        rows = (
            db.query(PipelineRecipe)
            .filter(PipelineRecipe.name.ilike(f"{_escape_like(value)}%", escape="\\"))
            .order_by(PipelineRecipe.updated_at.desc())
            .limit(5)
            .all()
        )
    return _pick(rows, value, "recipe_id", "配方")


def _resolve_api(db: Session, user, value: str) -> dict:
    from app.models.api_model import PlatformAPI

    rows = db.query(PlatformAPI).filter(PlatformAPI.name == value).limit(5).all()
    if not rows:
        rows = (
            db.query(PlatformAPI)
            .filter(PlatformAPI.name.ilike(f"{_escape_like(value)}%", escape="\\"))
            .order_by(PlatformAPI.created_at.desc())
            .limit(5)
            .all()
        )
    return _pick(rows, value, "api_id", "API")


def _pick(rows, value: str, id_field: str, label: str) -> dict:
    """解析裁决：唯一命中→ID；多命中/零命中→追问（带候选名列表）。"""
    if len(rows) == 1:
        row = rows[0]
        return {"id": str(getattr(row, "id")), id_field: str(getattr(row, "id")), "name": row.name}
    if not rows:
        return {"missing_value": value, "question": f"没有找到名为「{value}」的{label}，请确认名称。"}
    names = "、".join(r.name for r in rows[:5])
    return {"missing_value": value, "question": f"「{value}」匹配到多个{label}：{names}，请说明是哪一个。"}


_RESOLVERS = {
    "project": _resolve_project,
    "dataset": _resolve_dataset,
    "recipe": _resolve_recipe,
    "api": _resolve_api,
}


def _normalize_message(message: str) -> str:
    return re.sub(r"[\s！!。.，,？?]+", "", message or "").lower()


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------

def orchestrate(db: Session, *, config, user, message: str, tool_context: dict | None) -> ToolOrchestration:
    """/chat 的工具编排分支。返回 mode=chat 表示未命中工具，走普通对话。"""
    enabled = _enabled_tools(db)
    pending = tool_context or {}

    # 1) 上一轮是写类确认 → 本轮文字就是确认/取消（不走 LLM，行为确定）
    if pending.get("status") == "confirm" and pending.get("tool") in enabled:
        tool = pending["tool"]
        params = pending.get("params") or {}
        normalized = _normalize_message(message)
        if normalized in CANCEL_WORDS:
            return ToolOrchestration(
                "clarify", f"已取消「{TOOL_CATALOG[tool]['label']}」操作。", None,
            )
        if normalized in CONFIRM_WORDS:
            return _execute_and_summarize(db, config, user, tool, params, confirmed=True)
        return ToolOrchestration(
            "confirm",
            f"请回复「确认」执行，或「取消」放弃。（工具：{TOOL_CATALOG[tool]['label']}，参数：{json.dumps(params, ensure_ascii=False)}）",
            {"tool": tool, "params": params, "status": "confirm"},
        )

    # 2) 意图路由（含 clarify 补参合并）
    routed = _route_intent(db, config, message, pending if pending.get("status") == "clarify" else None, user)
    if not routed:
        return ToolOrchestration("chat", "")
    tool = routed["tool"]
    if tool not in enabled:
        return ToolOrchestration("chat", "")

    # 复杂写类 → 页面指引（不假支持）
    if tool in TOOL_PAGE_GUIDES:
        return ToolOrchestration(
            "guided",
            f"「{TOOL_CATALOG[tool]['label']}」{TOOL_PAGE_GUIDES[tool]}",
            {"tool": tool, "status": "guided"},
        )

    specs = TOOL_PARAM_SPECS[tool]
    collected = dict(pending.get("params") or {}) if pending.get("tool") == tool else {}
    collected.update(routed["params"])

    # 3) 名称解析（project 先行，dataset 依赖 project 过滤）
    resolved: dict = {}
    display: dict = {}
    questions: list[str] = []
    project_id = None
    for name in ("project", "recipe", "api", "dataset"):
        spec = specs.get(name)
        if not spec or name not in collected:
            continue
        value = str(collected.pop(name))
        if name == "dataset":
            outcome = _resolve_dataset(db, user, value, project_id=project_id)
        else:
            outcome = _RESOLVERS[spec["kind"]](db, user, value)
        if "question" in outcome:
            questions.append(outcome["question"])
            continue
        resolved[name] = outcome["id"]
        display[name] = outcome["name"]
        if name == "project":
            project_id = outcome["id"]

    # 4) 必填校验（名称型查 resolved；直接值型查 collected；解析失败已在 questions）
    _ID_KEYS = {"project": "project_id", "dataset": "dataset_id", "recipe": "recipe_id", "api": "api_id"}
    for name, spec in specs.items():
        if name in _ID_KEYS:
            present = bool(resolved.get(name))
        else:
            present = bool(collected.get(name))
        if spec.get("required") and not present:
            questions.append(spec["question"])
    if questions:
        merged_params = {**display, **collected}
        return ToolOrchestration(
            "clarify",
            questions[0],
            {"tool": tool, "params": merged_params, "status": "clarify"},
        )

    # 5) 传给 handler 的最终参数：解析出的 ID 键 + 直接值（text/rows/domain）
    handler_params: dict = {}
    for name in specs:
        if name in _ID_KEYS:
            if name in resolved:
                handler_params[_ID_KEYS[name]] = resolved[name]
        elif name in collected:
            handler_params[name] = collected[name]
    display_final = {**display, **collected}

    # 6) 写类（save_insight/create_recipe_task/offline_api）→ 显式确认
    from app.services.chat_tools import WRITE_TOOLS

    if tool in WRITE_TOOLS:
        return ToolOrchestration(
            "confirm",
            f"即将执行「{TOOL_CATALOG[tool]['label']}」，参数：{json.dumps(display_final, ensure_ascii=False)}。回复「确认」执行，或「取消」放弃。",
            {"tool": tool, "params": handler_params, "status": "confirm"},
        )
    return _execute_and_summarize(db, config, user, tool, handler_params, confirmed=False)


def _execute_and_summarize(db: Session, config, user, tool: str, params: dict, *, confirmed: bool) -> ToolOrchestration:
    label = TOOL_CATALOG[tool]["label"]
    try:
        result = execute_tool(db, user=user, tool=tool, params=params, confirmed=confirmed)
    except Exception as error:  # noqa: BLE001 - 工具失败以对话语言回报，不裸抛
        return ToolOrchestration(
            "done", f"「{label}」执行失败：{str(error)[:300]}", {"tool": tool, "status": "done", "ok": False},
        )
    summary = _summarize(db, config, user, tool, params, result)
    return ToolOrchestration(
        "done", summary, {"tool": tool, "status": "done", "ok": True},
    )
