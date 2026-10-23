"""Chat tools whitelist (spec v0.9 §15, Task A6.2).

封闭工具集（tools 注册制）：LLM 无法越出白名单；写操作一律需要用户确认
（``confirmed=True``）；执行走用户本人权限，不提权；每次调用入平台审计；
删除/权限/密钥类工具不存在于注册表——结构上不可能。

洞察沉淀（§16.5）：``save_insight`` 把用户确认的对话洞察写为 L2 经验
（origin=human，confidence=0.75 直接 active），并投影到系统经验分区。
"""

from __future__ import annotations

from types import SimpleNamespace
from uuid import UUID

from sqlalchemy.orm import Session

from app.models.recipe import PipelineRecipeVersion
from app.services.platform_audit import (
    PlatformAuditIntent,
    record_platform_event,
)

READ_TOOLS = {
    "list_datasets",
    "preview_dataset",
    "query_training_status",
    "query_loop_status",
    "get_api_call_example",
    "query_recipe_reports",
    "save_insight",  # 写的是经验沉淀，不是平台资源；仍需确认（16.5）
}
WRITE_TOOLS = {
    "create_automl_task",
    "create_loop_task",
    "create_recipe_task",
    "publish_workflow_api",
    "offline_api",
}
WHITELIST = sorted(READ_TOOLS | WRITE_TOOLS)


class ToolNotInWhitelist(LookupError):
    """Structural boundary: the tool does not exist for the LLM."""


class ToolConfirmationRequired(PermissionError):
    def __init__(self, tool: str) -> None:
        super().__init__("write tool requires explicit confirmation: %s" % tool)
        self.tool = tool


def _audit(db, *, user, tool, params, result, request=None):
    try:
        from types import SimpleNamespace

        if request is None:
            request = SimpleNamespace(state=SimpleNamespace(request_id=None), client=None)
        record_platform_event(
            db,
            actor=user,
            request=request,
            intent=PlatformAuditIntent(
                action="chat_tool.invoke",
                resource_type="chat_tool",
                resource_id=tool,
                changes={"tool": tool, "param_keys": sorted(params.keys())},
            ),
            result=result,
        )
        db.commit()
    except Exception:  # noqa: BLE001 - 审计失败不阻断工具结果
        db.rollback()


def execute_tool(
    db: Session,
    *,
    user,
    tool: str,
    params: dict,
    confirmed: bool = False,
    request=None,
    handlers: dict | None = None,
):
    """Dispatch a whitelisted chat tool.

    ``handlers`` maps tool name → callable(db, user, params); the default
    implementations below cover the always-available read tools and
    save_insight. Unknown tools raise ToolNotInWhitelist — there is no
    execution path outside the registry at all.
    """
    if tool not in WHITELIST:
        raise ToolNotInWhitelist(tool)
    if tool in WRITE_TOOLS and not confirmed:
        raise ToolConfirmationRequired(tool)
    if tool == "save_insight" and not confirmed:
        raise ToolConfirmationRequired(tool)

    registry = dict(handlers or {})
    registry.setdefault("save_insight", _save_insight)
    registry.setdefault("query_recipe_reports", _query_recipe_reports)
    registry.setdefault("get_api_call_example", _get_api_call_example)
    handler = registry.get(tool)
    if handler is None:
        # Platform-backed tools (dataset/training/loop listings) delegate to
        # their existing API services at wiring time; declare the boundary.
        raise LookupError("handler not wired for tool: %s" % tool)
    try:
        payload = handler(db, user, params)
        _audit(db, user=user, tool=tool, params=params, result="success", request=request)
        return payload
    except Exception:
        _audit(db, user=user, tool=tool, params=params, result="failed", request=request)
        raise


def _save_insight(db, user, params):
    from app.services.agent.experience import record_experience
    from app.services.knowledge_center import (
        get_system_partition,
        project_experience_entry,
    )

    text = str(params.get("text") or "").strip()
    if not text:
        raise ValueError("insight text is required")
    domain = str(params.get("domain") or "cross-domain")
    entry = record_experience(
        db,
        domain=domain,
        situation=text[:300],
        lesson=text[:500],
        action=str(params.get("action") or "按洞察在下轮 S1 中参考"),
        evidence={"source": "chat_save_insight", "user": str(user.id)},
        generality="domain" if params.get("project_id") else "cross-domain",
        confidence=0.75,
        origin="human",
        scope_project_ids=[str(params["project_id"])] if params.get("project_id") else [],
        created_by=user.id,
    )
    doc_id = None
    if entry.generality == "cross-domain":
        admin_id = _admin_id(db)
        if admin_id is not None:
            get_system_partition(db, admin_id)  # ensure partition exists
            doc_id = project_experience_entry(db, entry, admin_id)
    return {"entry_id": str(entry.id), "status": entry.status, "projected_doc_id": doc_id}


def _query_recipe_reports(db, user, params):
    recipe_id = params.get("recipe_id")
    version = (
        db.query(PipelineRecipeVersion)
        .filter(
            PipelineRecipeVersion.recipe_id == UUID(str(recipe_id)),
            PipelineRecipeVersion.status == "current",
        )
        .first()
    )
    if version is None:
        raise LookupError("recipe not found")
    content = version.content_json or {}
    return {
        "recipe": str(version.recipe_id),
        "version": version.version,
        "optimization_report": content.get("optimization_report"),
        "analysis_digest": content.get("analysis_digest"),
    }


def _get_api_call_example(db, user, params):
    from app.models.api_model import PlatformAPI

    api = db.get(PlatformAPI, UUID(str(params.get("api_id"))))
    if api is None:
        raise LookupError("api not found")
    example_body = api.request_schema or {}
    return {
        "name": api.name,
        "method": api.method,
        "endpoint": api.endpoint,
        "status": api.status,
        "example_body": example_body,
    }


def _admin_id(db):
    from app.models.user import User

    admin = db.query(User).filter(User.role == "admin").first()
    return admin.id if admin else None
