# -*- coding: utf-8 -*-
"""「闭环服务模板」的构建与实例化发布（④ 发布为应用编排）。

模板图（6 节点服务链，参数占位）：
  api_input（接收单行）→ python_script（S2 特征脚本 result 桥接变换）
  → load_deployment_model（按部署引用绑定，换模自动跟随）+ apply_model
  → append_error_dataset（报错行回流）→ agent_retrain_threshold
  （增量阈值→配方重放→铸造→换模；护栏与闭环自动化同语义）。

④ 发布编排 = ensure 模板 → 实例化到项目 → 参数全量替换（真实部署/配方/
脚本/阈值/白名单/集成）→ 发布工作流 v1 → publish_workflow_version
（服务图校验 + IO schema 提取 + 市场 API published）。模板本身幂等
（无节点时才建），项目模板名固定「闭环服务模板」。
"""
from __future__ import annotations

import logging
import uuid

from sqlalchemy.orm import Session

from app.models.workflow import Workflow, WorkflowEdge, WorkflowNode
from app.services.agent.servitize import _bridge_feature_script

logger = logging.getLogger(__name__)

TEMPLATE_NAME = "闭环服务模板"

# 模板占位参数键（实例化时全部替换为真实值）
P_DEPLOYMENT = "__DEPLOYMENT_ID__"
P_ERROR_DATASET = "__ERROR_DATASET_ID__"
P_ACCUM_DATASET = "__ACCUM_DATASET_ID__"
P_RETRAIN_DATASET = "__RETRAIN_DATASET_ID__"
P_RECIPE = "__RECIPE_ID__"
P_TARGET = "__TARGET_COLUMN__"
P_SCRIPT = "__FEATURE_SCRIPT__"
P_THRESHOLD = "__THRESHOLD_ROWS__"

# 模板节点定义：(键, operator_id, label, x, y, params 占位)
_TEMPLATE_NODES = [
    ("api_in", "api_input", "API 输入", 60, 200, {}),
    ("fe", "python_script", "S2 特征变换", 260, 200,
     {"script": P_SCRIPT, "auto_install": True}),
    ("model", "load_deployment_model", "部署模型（跟随换模）", 460, 120,
     {"deployment_id": P_DEPLOYMENT}),
    ("predict", "apply_model", "行预测", 640, 200, {}),
    ("reflow", "append_error_dataset", "报错回流", 830, 200,
     {"dataset_artifact_id": P_ERROR_DATASET,
      "error_classes": ["__ERROR_CLASSES__"]}),
    ("retrain", "agent_retrain_threshold", "智能体重训阈值触发", 1030, 200,
     {"dataset_artifact_id": P_ACCUM_DATASET,
      "retrain_dataset_artifact_id": P_RETRAIN_DATASET,
      "retrain_target_column": P_TARGET,
      "agent_recipe_id": P_RECIPE,
      "swap_deployment_id": P_DEPLOYMENT,
      "threshold_rows": P_THRESHOLD,
      "retrain_max_trials": 8,
      "retrain_ensemble_enabled": "__ENSEMBLE_ENABLED__",
      "retrain_ensemble_top_k": 3,
      "retrain_algorithm_ids": "__ALGORITHM_IDS__",
      "retrain_input_columns": "__INPUT_COLUMNS__"}),
]

# 模板边：(源键, 源端口, 目标键, 目标端口)
_TEMPLATE_EDGES = [
    ("api_in", "data", "fe", "data"),
    ("fe", "data", "predict", "data"),
    ("model", "model", "predict", "model"),
    ("predict", "data", "reflow", "data"),
    ("reflow", "data", "retrain", "data"),
]


def ensure_closed_loop_template(db: Session, actor_id) -> Workflow:
    """幂等确保平台模板存在且含 6 节点服务图（无节点/缺关键算子时重建）。"""
    template = (
        db.query(Workflow)
        .filter(Workflow.name == TEMPLATE_NAME, Workflow.is_template.is_(True))
        .first()
    )
    if template is None:
        template = Workflow(
            project_id=None, name=TEMPLATE_NAME, is_template=True,
            description="智能体服务化编排模板：API 输入→特征变换→部署模型预测"
                        "→报错回流→智能体重训（重放验收→铸造→换模）",
            created_by=actor_id,
        )
        db.add(template)
        db.flush()
    existing_ops = {
        node.operator_id for node in
        db.query(WorkflowNode).filter(WorkflowNode.workflow_id == template.id).all()
    }
    required = {"api_input", "python_script", "load_deployment_model",
                "apply_model", "append_error_dataset", "agent_retrain_threshold"}
    if existing_ops >= required:
        return template
    # 空壳/缺算子：清残留后重建（边先删防 FK）
    db.query(WorkflowEdge).filter(WorkflowEdge.workflow_id == template.id).delete()
    db.query(WorkflowNode).filter(WorkflowNode.workflow_id == template.id).delete()
    db.flush()
    node_ids: dict[str, uuid.UUID] = {}
    for key, operator_id, label, x, y, params in _TEMPLATE_NODES:
        node = WorkflowNode(
            workflow_id=template.id, operator_id=operator_id, label=label,
            position_x=x, position_y=y, params=params,
        )
        db.add(node)
        db.flush()
        node_ids[key] = node.id
    for source_key, source_port, target_key, target_port in _TEMPLATE_EDGES:
        db.add(WorkflowEdge(
            workflow_id=template.id,
            source_node_id=node_ids[source_key], source_port=source_port,
            target_node_id=node_ids[target_key], target_port=target_port,
        ))
    db.commit()
    db.refresh(template)
    return template


def publish_orchestration_from_recipe(
    db: Session, *, project_id, actor_id, recipe_id, deployment_id,
    feature_script: str, target_column: str, error_classes: list[str],
    threshold_rows: int, retrain_dataset_id: str, accum_dataset_id: str,
    error_dataset_id: str, ensemble_enabled: bool, algorithm_ids: list[str],
    input_columns: list[str],
):
    """实例化模板→参数替换→发布工作流 v1→发布编排 API（幂等复用）。

    返回 PlatformAPI（published）；同名项目工作流已发布过则直接复用其
    最新版本的 API（对同一配方重复发布不堆叠）。"""
    from app.models.api_model import PlatformAPI
    from app.services.api_publication import (
        APIPublicationError,
        publish_workflow_version,
    )

    template = ensure_closed_loop_template(db, actor_id)
    project_uuid = uuid.UUID(str(project_id))
    recipe_uuid = uuid.UUID(str(recipe_id))

    # 幂等：同项目同配方已有编排工作流（按描述标记）→ 复用并重发布最新版
    marker = f"agent-servitize:{recipe_uuid}"
    existing_wf = (
        db.query(Workflow)
        .filter(
            Workflow.project_id == project_uuid,
            Workflow.description.contains(marker),
        )
        .order_by(Workflow.created_at.desc())
        .first()
    )
    if existing_wf is not None:
        from app.api.workflow_versions import _snapshot
        from app.models.workflow_version import WorkflowVersion

        latest = (
            db.query(WorkflowVersion)
            .filter(WorkflowVersion.workflow_id == existing_wf.id)
            .order_by(WorkflowVersion.version.desc())
            .first()
        )
        if latest is not None:
            api = (
                db.query(PlatformAPI)
                .filter(
                    PlatformAPI.source_kind == "orchestration",
                    PlatformAPI.source_id == latest.id,
                )
                .first()
            )
            if api is not None and api.status == "published":
                return api, existing_wf

    # 实例化（新节点+边，参数替换占位符）
    workflow = Workflow(
        project_id=project_uuid,
        name=f"智能体闭环-{str(recipe_uuid)[:8]}",
        description=f"服务化编排（{marker}）：API→特征变换→预测→回流→智能体重训",
        created_by=actor_id,
    )
    db.add(workflow)
    db.flush()
    id_map: dict[uuid.UUID, uuid.UUID] = {}
    source_nodes = (
        db.query(WorkflowNode)
        .filter(WorkflowNode.workflow_id == template.id)
        .order_by(WorkflowNode.position_x.asc())
        .all()
    )
    replacement = {
        P_DEPLOYMENT: str(deployment_id),
        P_ERROR_DATASET: str(error_dataset_id),
        P_ACCUM_DATASET: str(accum_dataset_id),
        P_RETRAIN_DATASET: str(retrain_dataset_id),
        P_RECIPE: str(recipe_uuid),
        P_TARGET: target_column,
        P_SCRIPT: _bridge_feature_script(feature_script),
        P_THRESHOLD: str(max(1, int(threshold_rows))),
    }
    for node in source_nodes:
        params = dict(node.params or {})
        for key, value in replacement.items():
            for param_key, param_value in list(params.items()):
                if isinstance(param_value, str) and param_value == key:
                    params[param_key] = value
        # 复合占位（列表/布尔）按算子参数名替换
        if node.operator_id == "append_error_dataset":
            params["error_classes"] = list(error_classes)
        if node.operator_id == "agent_retrain_threshold":
            params["retrain_ensemble_enabled"] = bool(ensemble_enabled)
            params["retrain_algorithm_ids"] = ", ".join(algorithm_ids)
            params["retrain_input_columns"] = ", ".join(input_columns)
        copy = WorkflowNode(
            workflow_id=workflow.id, operator_id=node.operator_id,
            label=node.label, position_x=node.position_x,
            position_y=node.position_y, params=params,
        )
        db.add(copy)
        db.flush()
        id_map[node.id] = copy.id
    for edge in (
        db.query(WorkflowEdge)
        .filter(WorkflowEdge.workflow_id == template.id)
        .all()
    ):
        db.add(WorkflowEdge(
            workflow_id=workflow.id,
            source_node_id=id_map[edge.source_node_id],
            source_port=edge.source_port,
            target_node_id=id_map[edge.target_node_id],
            target_port=edge.target_port,
        ))
    db.commit()

    # 发布 v1 + 市场 API（服务图校验在 publish_workflow_version 内）
    from app.api.workflow_versions import _snapshot

    nodes_snapshot, edges_snapshot = _snapshot(db, workflow)
    from app.models.workflow_version import WorkflowVersion

    version = WorkflowVersion(
        workflow_id=workflow.id, version=1, name=workflow.name,
        description=workflow.description or "",
        nodes_snapshot=nodes_snapshot, edges_snapshot=edges_snapshot,
        published_by=actor_id,
    )
    db.add(version)
    db.commit()
    try:
        api = publish_workflow_version(db, workflow.id, 1, actor_id)
    except APIPublicationError as error:
        db.rollback()
        raise ValueError(f"编排发布失败：{error.message}") from error
    return api, workflow
