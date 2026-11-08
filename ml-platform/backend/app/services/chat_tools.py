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

# 工具目录（中文展示名 + 分组）：对话面板据此渲染按钮，管理员配置页
# 据此列出可启停项。函数名是调用契约不能改，展示层用业务语义名。
TOOL_CATALOG: dict[str, dict] = {
    "list_datasets": {"label": "查看数据集列表", "kind": "read"},
    "preview_dataset": {"label": "预览数据集", "kind": "read"},
    "query_training_status": {"label": "查询训练状态", "kind": "read"},
    "query_loop_status": {"label": "查询闭环任务状态", "kind": "read"},
    "get_api_call_example": {"label": "获取 API 调用示例", "kind": "read"},
    "query_recipe_reports": {"label": "查询配方报告", "kind": "read"},
    "save_insight": {"label": "沉淀对话洞察为经验", "kind": "insight"},
    "create_automl_task": {"label": "创建自动建模任务", "kind": "write"},
    "create_loop_task": {"label": "创建闭环任务", "kind": "write"},
    "create_recipe_task": {"label": "按配方创建任务", "kind": "write"},
    "publish_workflow_api": {"label": "发布工作流为 API", "kind": "write"},
    "offline_api": {"label": "下线 API", "kind": "write"},
}

# 参数规范（对话自然语言编排用）：声明每个工具的参数、是否必填、追问
# 话术与取值类型。kind 决定名称→ID 的确定性解析方式（见编排器）；
# create_automl_task/create_loop_task/publish_workflow_api 参数面复杂
# （实验/幂等键/编排拓扑），不做对话编排，由编排器返回页面指引。
TOOL_PARAM_SPECS: dict[str, dict[str, dict]] = {
    "list_datasets": {
        "project": {"required": True, "kind": "project", "question": "要查看哪个项目的数据集？"},
    },
    "preview_dataset": {
        "project": {"required": True, "kind": "project", "question": "数据集在哪个项目下？"},
        "dataset": {"required": True, "kind": "dataset", "question": "要预览哪个数据集？"},
        "rows": {"required": False, "kind": "int", "question": "预览前几行？"},
    },
    "query_training_status": {
        "project": {"required": True, "kind": "project", "question": "要查询哪个项目的训练任务状态？"},
    },
    "query_loop_status": {
        "project": {"required": True, "kind": "project", "question": "要查询哪个项目的闭环任务状态？"},
    },
    "query_recipe_reports": {
        "recipe": {"required": True, "kind": "recipe", "question": "要查询哪个配方的报告？"},
    },
    "get_api_call_example": {
        "api": {"required": True, "kind": "api", "question": "要查看哪个 API 的调用示例？"},
    },
    "save_insight": {
        "text": {"required": True, "kind": "text", "question": "要沉淀的洞察内容是什么？"},
        "domain": {"required": False, "kind": "domain", "question": "属于哪个领域？"},
    },
    "create_recipe_task": {
        "recipe": {"required": True, "kind": "recipe", "question": "按哪个配方创建任务？"},
        "project": {"required": True, "kind": "project", "question": "任务建在哪个项目下？"},
    },
    "offline_api": {
        "api": {"required": True, "kind": "api", "question": "要下线哪个 API？"},
    },
}

# 对话编排不做执行的复杂写类 → 明确指引（不假支持）
TOOL_PAGE_GUIDES: dict[str, str] = {
    "create_automl_task": "参数面较复杂（实验、搜索预算、算法白名单等），请到「算法平台 / 自动建模」或「智能体中心 / 新建任务」向导中创建。",
    "create_loop_task": "需要部署模型、回流与重训完整配置，请到「算法平台 / 闭环自动化」中创建。",
    "publish_workflow_api": "需要选择编排与端口配置，请到「算法平台 / 应用编排」的发布入口操作。",
}


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
    registry.setdefault("list_datasets", _list_datasets)
    registry.setdefault("preview_dataset", _preview_dataset)
    registry.setdefault("query_training_status", _query_training_status)
    registry.setdefault("query_loop_status", _query_loop_status)
    registry.setdefault("create_recipe_task", _create_recipe_task)
    registry.setdefault("offline_api", _offline_api)
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


def _list_datasets(db, user, params):
    """项目下数据集清单（Artifact type=dataset + 最新版本行列统计）。

    与官方列表端点同口径：source=normalized 是导入管道的内部归一化
    工件（normalized.csv），不属于用户数据集，一律过滤。
    """
    from app.models.artifact import Artifact
    from app.models.data_version import DatasetVersion

    artifacts = [
        artifact for artifact in (
            db.query(Artifact)
            .filter(
                Artifact.project_id == UUID(str(params["project_id"])),
                Artifact.type == "dataset",
                Artifact.archived_at.is_(None),
            )
            .order_by(Artifact.created_at.desc())
            .limit(40)
            .all()
        )
        if (artifact.metadata_ or {}).get("source") != "normalized"
    ][:20]
    versions = {}
    if artifacts:
        rows = (
            db.query(DatasetVersion)
            .filter(DatasetVersion.original_artifact_id.in_([a.id for a in artifacts]))
            .order_by(DatasetVersion.created_at.desc())
            .all()
        )
        for row in rows:
            versions.setdefault(row.original_artifact_id, row)
    items = [
        {
            "id": str(a.id),
            "name": a.name,
            "rows": versions[a.id].row_count if a.id in versions else None,
            "columns": versions[a.id].column_count if a.id in versions else None,
            "created_at": a.created_at.isoformat() if a.created_at else None,
        }
        for a in artifacts
    ]
    return {"items": items, "total": len(items)}


def _preview_dataset(db, user, params):
    """数据集前 N 行预览（默认 5 行；走 DatasetVersion→DatasetSample）。"""
    from app.models.artifact import Artifact
    from app.models.data_version import DatasetSample, DatasetVersion

    artifact = db.get(Artifact, UUID(str(params["dataset_id"])))
    if artifact is None or artifact.type != "dataset":
        raise LookupError("dataset not found")
    version = (
        db.query(DatasetVersion)
        .filter(DatasetVersion.original_artifact_id == artifact.id)
        .order_by(DatasetVersion.version.desc())
        .first()
    )
    if version is None:
        return {"name": artifact.name, "columns": [], "rows": [], "note": "该数据集尚无解析版本"}
    try:
        limit = max(1, min(int(params.get("rows") or 5), 20))
    except (TypeError, ValueError):
        limit = 5
    samples = (
        db.query(DatasetSample)
        .filter(DatasetSample.dataset_version_id == version.id)
        .order_by(DatasetSample.row_index.asc())
        .limit(limit)
        .all()
    )
    rows = [s.values or {} for s in samples]
    columns = list((rows[0] if rows else {}).keys())
    return {
        "name": artifact.name,
        "version": version.version,
        "row_count": version.row_count,
        "column_count": version.column_count,
        "columns": columns,
        "rows": rows,
    }


def _query_training_status(db, user, params):
    """项目最近训练任务状态（AutoML/普通训练各条 job 的当前态）。"""
    from app.models.training import TrainingJob

    jobs = (
        db.query(TrainingJob)
        .filter(TrainingJob.project_id == UUID(str(params["project_id"])))
        .order_by(TrainingJob.created_at.desc())
        .limit(8)
        .all()
    )
    return {
        "items": [
            {
                "id": str(j.id),
                "name": j.name,
                "operator": j.operator_id,
                "status": j.status,
                "task_id": j.task_id,
                "created_at": j.created_at.isoformat() if j.created_at else None,
            }
            for j in jobs
        ],
        "total": len(jobs),
    }


def _query_loop_status(db, user, params):
    """项目闭环任务状态 + 每任务最近事件流。"""
    from app.models.demo_loop import DemoLoopConfig, DemoLoopEvent

    configs = (
        db.query(DemoLoopConfig)
        .filter(DemoLoopConfig.project_id == UUID(str(params["project_id"])))
        .order_by(DemoLoopConfig.created_at.desc())
        .limit(5)
        .all()
    )
    items = []
    for config in configs:
        events = (
            db.query(DemoLoopEvent)
            .filter(DemoLoopEvent.config_id == config.id)
            .order_by(DemoLoopEvent.created_at.desc())
            .limit(3)
            .all()
        )
        items.append({
            "id": str(config.id),
            "name": config.name,
            "error_classes": config.error_classes or [],
            "last_events": [
                {
                    "type": e.event_type,
                    "severity": e.severity,
                    "message": e.message,
                    "created_at": e.created_at.isoformat() if e.created_at else None,
                }
                for e in events
            ],
        })
    return {"items": items, "total": len(items)}


def _create_recipe_task(db, user, params):
    """按配方重放智能体任务：以配方 current 版本固化的 guidance 快照新建
    AgentRun 并启动执行（P1 闭环重训同款重放路径）。

    数据集解析：配方 content/guidance 里固化的 dataset_artifact_id 优先
    （向导固化时不一定写入）；缺失时兜底目标项目下最新的用户数据集
    （排除内部归一化工件）——没有可用数据集时明确报错，不静默造出
    dataset_artifact_id=None 的必崩 run（executor 对 None 直接 CRASHED）。
    """
    from app.models.agent_run import AgentRun
    from app.models.artifact import Artifact
    from app.models.recipe import PipelineRecipe
    from app.services.agent.recipe import get_current_version

    recipe = db.get(PipelineRecipe, UUID(str(params["recipe_id"])))
    if recipe is None:
        raise LookupError("recipe not found")
    version = get_current_version(db, recipe.id)
    content = version.content_json or {}
    guidance = dict(content.get("guidance") or {})
    if not guidance:
        raise LookupError("该配方缺少可重放的 guidance 快照（旧版配方请在向导中重建任务）")
    dataset_artifact_raw = (
        content.get("dataset_artifact_id")
        or guidance.get("dataset_artifact_id")
        or (guidance.get("inputs") or {}).get("dataset_artifact_id")
    )
    if not dataset_artifact_raw:
        fallback = [
            a for a in (
                db.query(Artifact)
                .filter(
                    Artifact.project_id == UUID(str(params["project_id"])),
                    Artifact.type == "dataset",
                    Artifact.archived_at.is_(None),
                )
                .order_by(Artifact.created_at.desc())
                .limit(10)
                .all()
            )
            if (a.metadata_ or {}).get("source") != "normalized"
        ]
        if not fallback:
            raise LookupError("目标项目下没有可用数据集，无法按配方创建任务")
        dataset_artifact_raw = str(fallback[0].id)
    run = AgentRun(
        project_id=UUID(str(params["project_id"])),
        dataset_artifact_id=UUID(str(dataset_artifact_raw)),
        target_column=recipe.target_column or (guidance.get("inputs") or {}).get("target_column"),
        llm_profile_id=version.llm_profile_id,
        token_budget=8000,
        status="pending",
        current_stage="s1",
        memory_json={},
        result_json={},
        guidance_json=guidance,
        created_by=user.id,
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    from app.services.agent.executor import AgentRunNotExecutable, launch_agent_run

    try:
        launch_agent_run(run.id, actor_id=user.id)
    except AgentRunNotExecutable as error:
        run.status = "waiting_escalate"
        run.error_code = "AGENT_RUN_NOT_EXECUTABLE"
        run.result_json = {"executor_error": str(error)}
        db.commit()
        db.refresh(run)
    return {"run_id": str(run.id), "status": run.status, "recipe": recipe.name, "version": version.version}


def _offline_api(db, user, params):
    """下线已发布 API（状态 published→offline，幂等）。"""
    from app.models.api_model import PlatformAPI

    api = db.get(PlatformAPI, UUID(str(params["api_id"])))
    if api is None:
        raise LookupError("api not found")
    if api.status == "offline":
        return {"api": api.name, "status": "offline", "changed": False}
    api.status = "offline"
    db.commit()
    return {"api": api.name, "status": "offline", "changed": True}


def _admin_id(db):
    from app.models.user import User

    admin = db.query(User).filter(User.role == "admin").first()
    return admin.id if admin else None
