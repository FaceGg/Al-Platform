import uuid
from dataclasses import asdict
from pathlib import Path

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.workflow import Workflow, WorkflowNode, WorkflowEdge
from app.models.user import User
from app.api.auth import get_current_user
from app.engine.operator_contract import validate_operator_params
from app.engine.registry import OperatorRegistry
from app.services.artifact_service import ArtifactAccessError, ArtifactService
from app.templates.contract import TemplateContractError, validate_template
from app.templates.industrial import INDUSTRIAL_TEMPLATES

router = APIRouter(prefix="/api/templates", tags=["templates"])

TEMPLATES = {
    "weld_quality": {
        "name": "\u710a\u63a5\u8d28\u91cf\u9884\u6d4b",
        "description": "\u57fa\u4e8e\u710a\u63a5\u5de5\u827a\u53c2\u6570\u9884\u6d4b\u710a\u63a5\u8d28\u91cf\u7b49\u7ea7",
        "scenario": "\u7ed3\u6784\u5316\u6570\u636e\u5206\u7c7b",
        "nodes": [
            {"operator_id": "csv_import", "label": "\u5bfc\u5165\u710a\u63a5\u6570\u636e", "position_x": 50, "position_y": 100, "params": {}},
            {"operator_id": "missing_value_handler", "label": "\u7f3a\u5931\u503c\u5904\u7406", "position_x": 250, "position_y": 100, "params": {"strategy": "mean"}},
            {"operator_id": "label_encoder", "label": "\u7279\u5f81\u7f16\u7801", "position_x": 450, "position_y": 100, "params": {"encoding_type": "label"}},
            {"operator_id": "scaler", "label": "\u7279\u5f81\u7f29\u653e", "position_x": 650, "position_y": 100, "params": {"method": "standard", "target_column": "quality"}},
            {"operator_id": "train_test_split", "label": "\u6570\u636e\u5212\u5206", "position_x": 850, "position_y": 100, "params": {"test_size": 0.2}},
            {"operator_id": "xgboost_train", "label": "XGBoost \u8bad\u7ec3", "position_x": 1050, "position_y": 50, "params": {"n_estimators": 100}},
            {"operator_id": "classification_eval", "label": "\u6a21\u578b\u8bc4\u4f30", "position_x": 1250, "position_y": 50, "params": {}},
        ],
        "edges": [
            {"source": 0, "target": 1, "source_port": "data", "target_port": "data"},
            {"source": 1, "target": 2, "source_port": "data", "target_port": "data"},
            {"source": 2, "target": 3, "source_port": "data", "target_port": "data"},
            {"source": 3, "target": 4, "source_port": "data", "target_port": "data"},
            {"source": 4, "target": 5, "source_port": "train", "target_port": "data"},
            {"source": 4, "target": 6, "source_port": "test", "target_port": "test"},
            {"source": 5, "target": 6, "source_port": "model", "target_port": "model"},
        ],
        "user_params": [
            {"param_path": "0.params.file_path", "label": "\u6570\u636e\u6587\u4ef6", "ui_type": "file", "required": True},
            {"param_path": "6.params.target_column", "label": "\u76ee\u6807\u5217", "ui_type": "text", "default": "quality"},
            {"param_path": "5.params.target_column", "label": "\u76ee\u6807\u5217", "ui_type": "text", "default": "quality"},
            {"param_path": "5.params.n_estimators", "label": "\u6811\u7684\u6570\u91cf", "ui_type": "int", "default": 100},
        ],
    },
    "param_recommend": {
        "name": "\u53c2\u6570\u63a8\u8350\u6d41\u7a0b",
        "description": "\u57fa\u4e8e\u5386\u53f2\u710a\u63a5\u6570\u636e\u8bad\u7ec3\u56de\u5f52\u6a21\u578b\u63a8\u8350\u6700\u4f18\u53c2\u6570",
        "scenario": "\u53c2\u6570\u4f18\u5316\u56de\u5f52",
        "nodes": [
            {"operator_id": "csv_import", "label": "\u5bfc\u5165\u5386\u53f2\u6570\u636e", "position_x": 50, "position_y": 100, "params": {}},
            {"operator_id": "missing_value_handler", "label": "\u6570\u636e\u6e05\u6d17", "position_x": 250, "position_y": 100, "params": {"strategy": "median"}},
            {"operator_id": "scaler", "label": "\u7279\u5f81\u7f29\u653e", "position_x": 450, "position_y": 100, "params": {"method": "minmax", "target_column": "target"}},
            {"operator_id": "train_test_split", "label": "\u6570\u636e\u5212\u5206", "position_x": 650, "position_y": 100, "params": {"test_size": 0.2}},
            {"operator_id": "random_forest_train", "label": "\u968f\u673a\u68ee\u6797\u56de\u5f52", "position_x": 850, "position_y": 50, "params": {"n_estimators": 200}},
            {"operator_id": "regression_eval", "label": "\u56de\u5f52\u8bc4\u4f30", "position_x": 1050, "position_y": 50, "params": {}},
        ],
        "edges": [
            {"source": 0, "target": 1, "source_port": "data", "target_port": "data"},
            {"source": 1, "target": 2, "source_port": "data", "target_port": "data"},
            {"source": 2, "target": 3, "source_port": "data", "target_port": "data"},
            {"source": 3, "target": 4, "source_port": "train", "target_port": "data"},
            {"source": 3, "target": 5, "source_port": "test", "target_port": "test"},
            {"source": 4, "target": 5, "source_port": "model", "target_port": "model"},
        ],
        "user_params": [
            {"param_path": "0.params.file_path", "label": "\u6570\u636e\u6587\u4ef6", "ui_type": "file", "required": True},
            {"param_path": "4.params.n_estimators", "label": "\u6811\u7684\u6570\u91cf", "ui_type": "int", "default": 200},
        ],
    },
    "anomaly_detect": {
        "name": "\u5f02\u5e38\u68c0\u6d4b\u6d41\u7a0b",
        "description": "\u68c0\u6d4b\u710a\u63a5\u8fc7\u7a0b\u4e2d\u7684\u5f02\u5e38\u6570\u636e\u70b9",
        "scenario": "\u5f02\u5e38\u68c0\u6d4b",
        "nodes": [
            {"operator_id": "csv_import", "label": "\u5bfc\u5165\u710a\u63a5\u6570\u636e", "position_x": 50, "position_y": 100, "params": {}},
            {"operator_id": "scaler", "label": "\u7279\u5f81\u7f29\u653e", "position_x": 250, "position_y": 100, "params": {"method": "standard"}},
            {"operator_id": "mlp_train", "label": "MLP\u81ea\u7f16\u7801\u5668", "position_x": 450, "position_y": 100, "params": {"hidden_layers": [64, 32, 64]}},
            {"operator_id": "distribution_plot", "label": "\u91cd\u6784\u8bef\u5dee\u5206\u5e03", "position_x": 650, "position_y": 100, "params": {}},
        ],
        "edges": [
            {"source": 0, "target": 1, "source_port": "data", "target_port": "data"},
            {"source": 1, "target": 2, "source_port": "data", "target_port": "data"},
            {"source": 2, "target": 3, "source_port": "data", "target_port": "data"},
        ],
        "user_params": [
            {"param_path": "0.params.file_path", "label": "\u6570\u636e\u6587\u4ef6", "ui_type": "file", "required": True},
            {"param_path": "2.params.hidden_layers", "label": "\u9690\u85cf\u5c42", "ui_type": "text", "default": "64,32,64"},
        ],
    },
    "full_ml_pipeline": {
        "name": "\u5168\u6d41\u7a0bML\u5efa\u6a21",
        "description": "\u5b8c\u6574\u673a\u5668\u5b66\u4e60\u7ba1\u9053\uff1a\u6570\u636e\u5bfc\u5165\u2192\u9884\u5904\u7406\u2192\u591a\u6a21\u578b\u5bf9\u6bd4\u2192\u53ef\u89c6\u5316",
        "scenario": "\u5168\u6d41\u7a0b\u5bf9\u6bd4",
        "nodes": [
            {"operator_id": "csv_import", "label": "\u5bfc\u5165\u6570\u636e", "position_x": 50, "position_y": 100, "params": {}},
            {"operator_id": "missing_value_handler", "label": "\u7f3a\u5931\u503c\u5904\u7406", "position_x": 230, "position_y": 100, "params": {"strategy": "mean"}},
            {"operator_id": "label_encoder", "label": "\u7279\u5f81\u7f16\u7801", "position_x": 410, "position_y": 100, "params": {"encoding_type": "label"}},
            {"operator_id": "scaler", "label": "\u7279\u5f81\u7f29\u653e", "position_x": 590, "position_y": 100, "params": {"method": "standard"}},
            {"operator_id": "train_test_split", "label": "\u6570\u636e\u5212\u5206", "position_x": 770, "position_y": 100, "params": {"test_size": 0.2}},
            {"operator_id": "random_forest_train", "label": "\u968f\u673a\u68ee\u6797", "position_x": 950, "position_y": -80, "params": {"n_estimators": 200}},
            {"operator_id": "xgboost_train", "label": "XGBoost", "position_x": 950, "position_y": 40, "params": {"n_estimators": 150}},
            {"operator_id": "linear_model_train", "label": "\u903b\u8f91\u56de\u5f52", "position_x": 950, "position_y": 160, "params": {}},
            {"operator_id": "classification_eval", "label": "\u8bc4\u4f30 RF", "position_x": 950, "position_y": 0, "params": {}},
            {"operator_id": "classification_eval", "label": "\u8bc4\u4f30 XGB", "position_x": 950, "position_y": 120, "params": {}},
            {"operator_id": "classification_eval", "label": "\u8bc4\u4f30 LR", "position_x": 950, "position_y": 240, "params": {}},
            {"operator_id": "feature_importance", "label": "\u7279\u5f81\u91cd\u8981\u6027", "position_x": 1130, "position_y": 100, "params": {}},
            {"operator_id": "roc_curve", "label": "ROC\u66f2\u7ebf", "position_x": 1130, "position_y": 250, "params": {}},
        ],
        "edges": [
            {"source": 0, "target": 1, "source_port": "data", "target_port": "data"},
            {"source": 1, "target": 2, "source_port": "data", "target_port": "data"},
            {"source": 2, "target": 3, "source_port": "data", "target_port": "data"},
            {"source": 3, "target": 4, "source_port": "data", "target_port": "data"},
            {"source": 4, "target": 5, "source_port": "train", "target_port": "data"},
            {"source": 4, "target": 6, "source_port": "train", "target_port": "data"},
            {"source": 4, "target": 7, "source_port": "train", "target_port": "data"},
            {"source": 4, "target": 8, "source_port": "test", "target_port": "test"},
            {"source": 4, "target": 9, "source_port": "test", "target_port": "test"},
            {"source": 4, "target": 10, "source_port": "test", "target_port": "test"},
            {"source": 5, "target": 8, "source_port": "model", "target_port": "model"},
            {"source": 6, "target": 9, "source_port": "model", "target_port": "model"},
            {"source": 7, "target": 10, "source_port": "model", "target_port": "model"},
            {"source": 8, "target": 11, "source_port": "data", "target_port": "data"},
            {"source": 9, "target": 11, "source_port": "data", "target_port": "data"},
            {"source": 10, "target": 12, "source_port": "data", "target_port": "data"},
        ],
        "user_params": [
            {"param_path": "0.params.file_path", "label": "\u6570\u636e\u6587\u4ef6", "ui_type": "file", "required": True},
            {"param_path": "5.params.n_estimators", "label": "RF\u6811\u6570\u91cf", "ui_type": "int", "default": 200},
            {"param_path": "6.params.n_estimators", "label": "XGB\u6811\u6570\u91cf", "ui_type": "int", "default": 150},
        ],
    },
    "condition_branch": {
        "name": "Condition Branch",
        "description": "Auto-branch based on data quality: qualified data goes to evaluation, unqualified goes to re-cleaning",
        "scenario": "Conditional Branch Control",
        "nodes": [
            {"operator_id": "csv_import", "label": "Import Data", "position_x": 50, "position_y": 100, "params": {}},
            {"operator_id": "data_stats", "label": "Data Quality Check", "position_x": 230, "position_y": 100, "params": {}},
            {"operator_id": "condition", "label": "Quality Gate (missing<10%?)", "position_x": 420, "position_y": 100, "params": {"condition": "missing_rate < 0.1"}},
            {"operator_id": "missing_value_handler", "label": "Fill Missing", "position_x": 420, "position_y": 260, "params": {"strategy": "mean"}},
            {"operator_id": "scaler", "label": "Scale (Cleaned)", "position_x": 600, "position_y": 260, "params": {"method": "standard"}},
            {"operator_id": "scaler", "label": "Scale (Qualified)", "position_x": 600, "position_y": 100, "params": {"method": "standard"}},
            {"operator_id": "merge", "label": "Merge Flow", "position_x": 780, "position_y": 180, "params": {}},
            {"operator_id": "train_test_split", "label": "Train/Test Split", "position_x": 950, "position_y": 180, "params": {"test_size": 0.2}},
            {"operator_id": "xgboost_train", "label": "XGBoost Train", "position_x": 1130, "position_y": 120, "params": {"n_estimators": 100}},
            {"operator_id": "classification_eval", "label": "Evaluation", "position_x": 1130, "position_y": 240, "params": {}},
        ],
        "edges": [
            {"source": 0, "target": 1, "source_port": "data", "target_port": "data"},
            {"source": 1, "target": 2, "source_port": "data", "target_port": "data"},
            {"source": 2, "target": 3, "source_port": "false", "target_port": "data"},
            {"source": 3, "target": 4, "source_port": "data", "target_port": "data"},
            {"source": 2, "target": 5, "source_port": "true", "target_port": "data"},
            {"source": 4, "target": 6, "source_port": "data", "target_port": "data1"},
            {"source": 5, "target": 6, "source_port": "data", "target_port": "data2"},
            {"source": 6, "target": 7, "source_port": "data", "target_port": "data"},
            {"source": 7, "target": 8, "source_port": "train", "target_port": "data"},
            {"source": 7, "target": 9, "source_port": "test", "target_port": "test"},
            {"source": 8, "target": 9, "source_port": "model", "target_port": "model"},
        ],
        "user_params": [
            {"param_path": "0.params.file_path", "label": "CSV File", "ui_type": "file", "required": True},
            {"param_path": "8.params.n_estimators", "label": "XGB n_estimators", "ui_type": "int", "default": 100},
        ],
    },
    "loop_optimize": {
        "name": "Loop Optimization",
        "description": "Iteratively optimize parameters until convergence criteria are met",
        "scenario": "Iterative Optimization Loop",
        "nodes": [
            {"operator_id": "csv_import", "label": "Import Data", "position_x": 50, "position_y": 100, "params": {}},
            {"operator_id": "scaler", "label": "Scale Features", "position_x": 230, "position_y": 100, "params": {"method": "standard"}},
            {"operator_id": "loop", "label": "Parameter Loop (max 10)", "position_x": 420, "position_y": 100, "params": {"max_iterations": 10}},
            {"operator_id": "train_test_split", "label": "Train/Test Split", "position_x": 650, "position_y": 60, "params": {"test_size": 0.2}},
            {"operator_id": "xgboost_train", "label": "XGBoost Train", "position_x": 650, "position_y": 180, "params": {"n_estimators": 100}},
            {"operator_id": "classification_eval", "label": "Iteration Eval", "position_x": 860, "position_y": 120, "params": {}},
            {"operator_id": "classification_eval", "label": "Final Evaluation", "position_x": 860, "position_y": 260, "params": {}},
        ],
        "edges": [
            {"source": 0, "target": 1, "source_port": "data", "target_port": "data"},
            {"source": 1, "target": 2, "source_port": "data", "target_port": "data"},
            {"source": 2, "target": 3, "source_port": "data", "target_port": "data"},
            {"source": 3, "target": 4, "source_port": "train", "target_port": "data"},
            {"source": 3, "target": 5, "source_port": "test", "target_port": "test"},
            {"source": 4, "target": 5, "source_port": "model", "target_port": "model"},
            {"source": 2, "target": 6, "source_port": "result", "target_port": "data"},
        ],
        "user_params": [
            {"param_path": "0.params.file_path", "label": "CSV File", "ui_type": "file", "required": True},
            {"param_path": "2.params.max_iterations", "label": "Max Iterations", "ui_type": "int", "default": 10},
        ],
    },
    "multi_agent_quality": {
        "name": "Multi-Agent Quality Analysis",
        "description": "Planner decomposes task -> Executor trains models -> Reviewer confirms -> LLM generates report",
        "scenario": "Multi-Agent Collaboration",
        "nodes": [
            {"operator_id": "csv_import", "label": "Import Weld Data", "position_x": 50, "position_y": 150, "params": {}},
            {"operator_id": "missing_value_handler", "label": "Preprocess", "position_x": 230, "position_y": 150, "params": {"strategy": "mean"}},
            {"operator_id": "scaler", "label": "Scale Features", "position_x": 420, "position_y": 150, "params": {"method": "standard"}},
            {"operator_id": "train_test_split", "label": "Train/Test Split", "position_x": 650, "position_y": 40, "params": {"test_size": 0.2}},
            {"operator_id": "random_forest_train", "label": "RF Train (Executor)", "position_x": 650, "position_y": 150, "params": {"n_estimators": 200}},
            {"operator_id": "xgboost_train", "label": "XGB Train (Backup)", "position_x": 650, "position_y": 260, "params": {"n_estimators": 100}},
            {"operator_id": "classification_eval", "label": "Eval RF", "position_x": 860, "position_y": 100, "params": {}},
            {"operator_id": "classification_eval", "label": "Eval XGB", "position_x": 860, "position_y": 220, "params": {}},
            {"operator_id": "model_comparison", "label": "Compare (Reviewer)", "position_x": 1080, "position_y": 160, "params": {}},
        ],
        "edges": [
            {"source": 0, "target": 1, "source_port": "data", "target_port": "data"},
            {"source": 1, "target": 2, "source_port": "data", "target_port": "data"},
            {"source": 2, "target": 3, "source_port": "data", "target_port": "data"},
            {"source": 3, "target": 4, "source_port": "train", "target_port": "data"},
            {"source": 3, "target": 5, "source_port": "train", "target_port": "data"},
            {"source": 3, "target": 6, "source_port": "test", "target_port": "test"},
            {"source": 3, "target": 7, "source_port": "test", "target_port": "test"},
            {"source": 4, "target": 6, "source_port": "model", "target_port": "model"},
            {"source": 5, "target": 7, "source_port": "model", "target_port": "model"},
            {"source": 6, "target": 8, "source_port": "data", "target_port": "data1"},
            {"source": 7, "target": 8, "source_port": "data", "target_port": "data2"},
        ],
        "user_params": [
            {"param_path": "0.params.file_path", "label": "CSV File", "ui_type": "file", "required": True},
            {"param_path": "4.params.n_estimators", "label": "RF n_estimators", "ui_type": "int", "default": 200},
        ],
    },
}

TEMPLATE_META = {k: {"id": k, "name": v["name"], "description": v["description"], "scenario": v.get("scenario", "")} for k, v in TEMPLATES.items()}


class IndustrialTemplateInstantiateRequest(BaseModel):
    project_id: str
    dataset_artifact_id: str
    parameters: dict = Field(default_factory=dict)


def _industrial_template_dict(template):
    return asdict(template)


@router.get("")
def list_templates():
    items = dict(TEMPLATE_META)
    items.update({
        template_id: {
            "id": template_id, "name": template.name,
            "description": template.description, "scenario": template.scenario,
            "task_type": template.task_type, "target_column": template.target_column,
        }
        for template_id, template in INDUSTRIAL_TEMPLATES.items()
    })
    return {"items": list(items.values()), "total": len(items)}


@router.get("/{template_id}")
def get_template(template_id: str):
    if template_id in INDUSTRIAL_TEMPLATES:
        return _industrial_template_dict(INDUSTRIAL_TEMPLATES[template_id])
    if template_id not in TEMPLATES:
        raise HTTPException(404, "Template not found")
    return {"id": template_id, **TEMPLATES[template_id]}


@router.post("/{template_id}/instantiate")
def instantiate_template(
    template_id: str,
    request: Request,
    data: IndustrialTemplateInstantiateRequest | None = Body(default=None),
    project_id: str | None = Query(default=None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if template_id in INDUSTRIAL_TEMPLATES:
        if data is None:
            raise HTTPException(400, {
                "code": "TEMPLATE_REQUEST_INVALID", "message": "JSON request body is required",
            })
        return _instantiate_industrial_template(template_id, data, db, current_user)
    if template_id not in TEMPLATES:
        raise HTTPException(404, "Template not found")
    if not project_id:
        raise HTTPException(400, "project_id is required")
    tmpl = TEMPLATES[template_id]
    wf = Workflow(project_id=uuid.UUID(project_id), name=tmpl["name"] + " (copy)", type="free", created_by=current_user.id)
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

    user_params = dict(request.query_params)
    for up in tmpl.get("user_params", []):
        param_path = up["param_path"]
        parts = param_path.split(".")
        node_idx = int(parts[0])
        param_name = parts[2]
        val = user_params.get(param_path, up.get("default"))
        if val is not None:
            n = db.query(WorkflowNode).filter(WorkflowNode.id == uuid.UUID(node_map[node_idx])).first()
            if n:
                p = n.params or {}
                p[param_name] = val
                n.params = p
    # Propagate target_column from eval/training nodes to all ML nodes that need it
    target_col = user_params.get("6.params.target_column") or user_params.get("5.params.target_column")
    if not target_col:
        for up in tmpl.get("user_params", []):
            if up["param_path"].endswith(".target_column") and up.get("default"):
                target_col = up["default"]
                break
    if target_col:
        for idx in node_map:
            spec = tmpl["nodes"][idx]
            if spec["operator_id"] in ("xgboost_train", "random_forest_train", "linear_model_train", "scaler",
                                       "classification_eval", "classification_eval_detailed", "regression_eval"):
                n = db.query(WorkflowNode).filter(WorkflowNode.id == uuid.UUID(node_map[idx])).first()
                if n:
                    p = n.params or {}
                    p["target_column"] = target_col
                    n.params = p

    for edef in tmpl["edges"]:
        edge = WorkflowEdge(
            workflow_id=wf.id,
            source_node_id=uuid.UUID(node_map[edef["source"]]),
            source_port=edef["source_port"],
            target_node_id=uuid.UUID(node_map[edef["target"]]),
            target_port=edef["target_port"],
        )
        db.add(edge)

    db.commit()
    return {"workflow_id": str(wf.id), "message": "Template instantiated"}


def _instantiate_industrial_template(template_id, data, db, current_user):
    from app.models.project import Project

    try:
        project_uuid = uuid.UUID(data.project_id)
        artifact_uuid = uuid.UUID(data.dataset_artifact_id)
    except ValueError as exc:
        raise HTTPException(400, {
            "code": "TEMPLATE_REQUEST_INVALID", "message": "Invalid project or Artifact ID",
        }) from exc
    project = db.query(Project).filter(
        Project.id == project_uuid, Project.owner_id == current_user.id,
    ).first()
    if not project:
        raise HTTPException(404, "Project not found")

    artifact_root = Path(__file__).resolve().parents[1] / "artifact_store"
    try:
        artifact = ArtifactService(db, artifact_root).resolve(
            artifact_uuid, project_uuid, expected_type="dataset",
        )
    except (ArtifactAccessError, ValueError) as exc:
        raise HTTPException(400, {
            "code": "TEMPLATE_DATASET_INVALID", "message": str(exc),
        }) from exc

    template = validate_template(INDUSTRIAL_TEMPLATES[template_id])
    known_parameters = {parameter.key: parameter for parameter in template.parameters}
    unknown = set(data.parameters) - set(known_parameters)
    if unknown:
        raise HTTPException(400, {
            "code": "TEMPLATE_PARAMETER_INVALID",
            "message": f"Unknown template parameters: {sorted(unknown)}",
        })

    node_params = {node.key: dict(node.params) for node in template.nodes}
    for key, parameter in known_parameters.items():
        value = data.parameters.get(key, parameter.default)
        if parameter.required and value in (None, ""):
            raise HTTPException(400, {
                "code": "TEMPLATE_PARAMETER_REQUIRED", "message": f"Parameter '{key}' is required",
            })
        for node_key, param_name in parameter.node_params:
            node_params[node_key][param_name] = value
    node_params["import"].update({"source": "local", "file_path": artifact.storage_path})

    try:
        for node in template.nodes:
            operator = OperatorRegistry.get(node.operator_id)
            node_params[node.key] = validate_operator_params(operator.parameters, node_params[node.key])
    except Exception as exc:
        raise HTTPException(400, {
            "code": "TEMPLATE_PARAMETER_INVALID", "message": str(exc),
        }) from exc

    try:
        workflow = Workflow(
            project_id=project_uuid, name=template.name + " (copy)", type="industrial",
            created_by=current_user.id,
        )
        db.add(workflow)
        db.flush()
        node_map = {}
        for node_spec in template.nodes:
            node = WorkflowNode(
                workflow_id=workflow.id, operator_id=node_spec.operator_id,
                label=node_spec.label, position_x=node_spec.position_x,
                position_y=node_spec.position_y, params=node_params[node_spec.key],
            )
            db.add(node)
            db.flush()
            node_map[node_spec.key] = node.id
        for edge_spec in template.edges:
            db.add(WorkflowEdge(
                workflow_id=workflow.id,
                source_node_id=node_map[edge_spec.source], source_port=edge_spec.source_port,
                target_node_id=node_map[edge_spec.target], target_port=edge_spec.target_port,
            ))
        db.commit()
    except Exception:
        db.rollback()
        raise
    return {
        "workflow_id": str(workflow.id), "template_id": template_id,
        "dataset_artifact_id": str(artifact.id), "message": "Template instantiated",
    }
