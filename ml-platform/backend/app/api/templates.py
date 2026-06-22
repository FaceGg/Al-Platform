from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.workflow import Workflow, WorkflowNode, WorkflowEdge
from app.models.user import User
from app.api.auth import get_current_user

router = APIRouter(prefix="/api/templates", tags=["templates"])

TEMPLATES = {
    "weld_quality": {
        "name": "焊接质量预测",
        "description": "基于焊接工艺参数（电流、电压、压力、时间）预测焊接质量等级（合格/不合格）",
        "scenario": "结构化数据分类",
        "nodes": [
            {"operator_id": "csv_import", "label": "导入焊接数据", "position_x": 50, "position_y": 100, "params": {}},
            {"operator_id": "missing_value_handler", "label": "缺失值处理", "position_x": 250, "position_y": 100, "params": {"strategy": "mean"}},
            {"operator_id": "label_encoder", "label": "特征编码", "position_x": 450, "position_y": 100, "params": {"encoding_type": "label"}},
            {"operator_id": "scaler", "label": "特征缩放", "position_x": 650, "position_y": 100, "params": {"method": "standard"}},
            {"operator_id": "train_test_split", "label": "数据划分", "position_x": 850, "position_y": 100, "params": {"test_size": 0.2}},
            {"operator_id": "xgboost_train", "label": "XGBoost 训练", "position_x": 1050, "position_y": 50, "params": {"n_estimators": 100}},
            {"operator_id": "classification_eval", "label": "模型评估", "position_x": 1250, "position_y": 50, "params": {}},
        ],
        "edges": [
            {"source": 0, "target": 1, "source_port": "data", "target_port": "data"},
            {"source": 1, "target": 2, "source_port": "data", "target_port": "data"},
            {"source": 2, "target": 3, "source_port": "data", "target_port": "data"},
            {"source": 3, "target": 4, "source_port": "data", "target_port": "data"},
            {"source": 4, "target": 5, "source_port": "train", "target_port": "train"},
            {"source": 4, "target": 6, "source_port": "test", "target_port": "test"},
            {"source": 5, "target": 6, "source_port": "model", "target_port": "model"},
        ],
        "user_params": [
            {"param_path": "0.params.file_path", "label": "数据文件", "ui_type": "file", "required": True},
            {"param_path": "6.params.target_column", "label": "目标列", "ui_type": "text", "default": "quality"},
            {"param_path": "5.params.n_estimators", "label": "树的数量", "ui_type": "int", "default": 100},
        ],
    },
}

TEMPLATE_META = {k: {"id": k, "name": v["name"], "description": v["description"], "scenario": v.get("scenario", "")} for k, v in TEMPLATES.items()}


@router.get("")
def list_templates():
    return {"items": list(TEMPLATE_META.values()), "total": len(TEMPLATE_META)}


@router.get("/{template_id}")
def get_template(template_id: str):
    if template_id not in TEMPLATES:
        raise HTTPException(404, "Template not found")
    return {"id": template_id, **TEMPLATES[template_id]}


@router.post("/{template_id}/instantiate")
def instantiate_template(
    template_id: str,
    project_id: str,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if template_id not in TEMPLATES:
        raise HTTPException(404, "Template not found")
    tmpl = TEMPLATES[template_id]
    wf = Workflow(project_id=project_id, name=tmpl["name"] + " (副本)", type="free", created_by=current_user.id)
    db.add(wf)
    db.commit()

    node_map = {}
    for i, ndef in enumerate(tmpl["nodes"]):
        params = ndef["params"].copy()
        node = WorkflowNode(
            workflow_id=wf.id, operator_id=ndef["operator_id"],
            label=ndef["label"], position_x=ndef["position_x"],
            position_y=ndef["position_y"], params=params,
        )
        db.add(node)
        db.flush()
        node_map[i] = str(node.id)

    # Apply user params from query params
    user_params = dict(request.query_params)
    for up in tmpl.get("user_params", []):
        param_path = up["param_path"]
        if param_path in user_params:
            parts = param_path.split(".")
            node_idx = int(parts[0])
            param_name = parts[2]
            val = user_params[param_path]
            n = db.query(WorkflowNode).filter(WorkflowNode.id == node_map[node_idx]).first()
            if n:
                p = n.params or {}
                p[param_name] = val
                n.params = p

    for edef in tmpl["edges"]:
        edge = WorkflowEdge(
            workflow_id=wf.id,
            source_node_id=node_map[edef["source"]],
            source_port=edef["source_port"],
            target_node_id=node_map[edef["target"]],
            target_port=edef["target_port"],
        )
        db.add(edge)

    db.commit()
    return {"workflow_id": str(wf.id), "message": "Template instantiated"}
