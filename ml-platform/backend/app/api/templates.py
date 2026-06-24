import uuid
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.workflow import Workflow, WorkflowNode, WorkflowEdge
from app.models.user import User
from app.api.auth import get_current_user

router = APIRouter(prefix="/api/templates", tags=["templates"])

TEMPLATES = {
    "weld_quality": {
        "name": "\u710a\u63a5\u8d28\u91cf\u9884\u6d4b",
        "description": "\u57fa\u4e8e\u710a\u63a5\u5de5\u827a\u53c2\u6570\uff08\u7535\u6d41\u3001\u7535\u538b\u3001\u538b\u529b\u3001\u65f6\u95f4\uff09\u9884\u6d4b\u710a\u63a5\u8d28\u91cf\u7b49\u7ea7",
        "scenario": "\u7ed3\u6784\u5316\u6570\u636e\u5206\u7c7b",
        "nodes": [
            {"operator_id": "csv_import", "label": "\u5bfc\u5165\u710a\u63a5\u6570\u636e", "position_x": 50, "position_y": 100, "params": {}},
            {"operator_id": "missing_value_handler", "label": "\u7f3a\u5931\u503c\u5904\u7406", "position_x": 250, "position_y": 100, "params": {"strategy": "mean"}},
            {"operator_id": "label_encoder", "label": "\u7279\u5f81\u7f16\u7801", "position_x": 450, "position_y": 100, "params": {"encoding_type": "label"}},
            {"operator_id": "scaler", "label": "\u7279\u5f81\u7f29\u653e", "position_x": 650, "position_y": 100, "params": {"method": "standard"}},
            {"operator_id": "train_test_split", "label": "\u6570\u636e\u5212\u5206", "position_x": 850, "position_y": 100, "params": {"test_size": 0.2}},
            {"operator_id": "xgboost_train", "label": "XGBoost \u8bad\u7ec3", "position_x": 1050, "position_y": 50, "params": {"n_estimators": 100}},
            {"operator_id": "classification_eval", "label": "\u6a21\u578b\u8bc4\u4f30", "position_x": 1250, "position_y": 50, "params": {}},
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
            {"param_path": "0.params.file_path", "label": "\u6570\u636e\u6587\u4ef6", "ui_type": "file", "required": True},
            {"param_path": "6.params.target_column", "label": "\u76ee\u6807\u5217", "ui_type": "text", "default": "quality"},
            {"param_path": "5.params.n_estimators", "label": "\u6811\u7684\u6570\u91cf", "ui_type": "int", "default": 100},
        ],
    },
    "param_recommend": {
        "name": "\u53c2\u6570\u63a8\u8350\u6d41\u7a0b",
        "description": "\u57fa\u4e8e\u5386\u53f2\u710a\u63a5\u6570\u636e\uff0c\u8bad\u7ec3\u56de\u5f52\u6a21\u578b\u63a8\u8350\u6700\u4f18\u710a\u63a5\u53c2\u6570\uff08\u7535\u6d41\u3001\u538b\u529b\u3001\u65f6\u95f4\uff09",
        "scenario": "\u53c2\u6570\u4f18\u5316\u56de\u5f52",
        "nodes": [
            {"operator_id": "csv_import", "label": "\u5bfc\u5165\u5386\u53f2\u6570\u636e", "position_x": 50, "position_y": 100, "params": {}},
            {"operator_id": "missing_value_handler", "label": "\u6570\u636e\u6e05\u6d17", "position_x": 250, "position_y": 100, "params": {"strategy": "median"}},
            {"operator_id": "scaler", "label": "\u7279\u5f81\u7f29\u653e", "position_x": 450, "position_y": 100, "params": {"method": "minmax"}},
            {"operator_id": "train_test_split", "label": "\u6570\u636e\u5212\u5206", "position_x": 650, "position_y": 100, "params": {"test_size": 0.2}},
            {"operator_id": "random_forest_train", "label": "\u968f\u673a\u68ee\u6797\u56de\u5f52", "position_x": 850, "position_y": 50, "params": {"n_estimators": 200}},
            {"operator_id": "regression_eval", "label": "\u56de\u5f52\u8bc4\u4f30", "position_x": 1050, "position_y": 50, "params": {}},
        ],
        "edges": [
            {"source": 0, "target": 1, "source_port": "data", "target_port": "data"},
            {"source": 1, "target": 2, "source_port": "data", "target_port": "data"},
            {"source": 2, "target": 3, "source_port": "data", "target_port": "data"},
            {"source": 3, "target": 4, "source_port": "train", "target_port": "train"},
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
        "description": "\u5bf9\u710a\u63a5\u751f\u4ea7\u6570\u636e\u8fdb\u884c\u5b9e\u65f6\u5f02\u5e38\u68c0\u6d4b\uff0c\u8bc6\u522b\u504f\u79bb\u6b63\u5e38\u8303\u56f4\u7684\u710a\u63a5\u70b9",
        "scenario": "\u65e0\u76d1\u7763\u5f02\u5e38\u68c0\u6d4b",
        "nodes": [
            {"operator_id": "csv_import", "label": "\u5bfc\u5165\u751f\u4ea7\u6570\u636e", "position_x": 50, "position_y": 100, "params": {}},
            {"operator_id": "missing_value_handler", "label": "\u6570\u636e\u6e05\u6d17", "position_x": 250, "position_y": 100, "params": {"strategy": "drop"}},
            {"operator_id": "scaler", "label": "\u7279\u5f81\u7f29\u653e", "position_x": 450, "position_y": 100, "params": {"method": "standard"}},
            {"operator_id": "pca", "label": "PCA\u964d\u7ef4", "position_x": 650, "position_y": 100, "params": {"n_components": 2}},
            {"operator_id": "distribution_plot", "label": "\u5f02\u5e38\u53ef\u89c6\u5316", "position_x": 850, "position_y": 100, "params": {}},
        ],
        "edges": [
            {"source": 0, "target": 1, "source_port": "data", "target_port": "data"},
            {"source": 1, "target": 2, "source_port": "data", "target_port": "data"},
            {"source": 2, "target": 3, "source_port": "data", "target_port": "data"},
            {"source": 3, "target": 4, "source_port": "data", "target_port": "data"},
        ],
        "user_params": [
            {"param_path": "0.params.file_path", "label": "\u6570\u636e\u6587\u4ef6", "ui_type": "file", "required": True},
            {"param_path": "3.params.n_components", "label": "\u964d\u7ef4\u7ef4\u6570", "ui_type": "int", "default": 2},
        ],
    },
    "full_ml_pipeline": {
        "name": "\u5168\u6d41\u7a0b ML \u5efa\u6a21",
        "description": "\u5b8c\u6574\u7684\u673a\u5668\u5b66\u4e60\u5efa\u6a21\u6d41\u7a0b\uff1a\u6570\u636e\u5bfc\u5165\u2192\u6e05\u6d17\u2192\u7279\u5f81\u5de5\u7a0b\u2192\u591a\u6a21\u578b\u5bf9\u6bd4\u2192\u8bc4\u4f30\u2192\u53ef\u89c6\u5316",
        "scenario": "\u7efc\u5408\u5efa\u6a21\u5bf9\u6bd4",
        "nodes": [
            {"operator_id": "csv_import", "label": "\u5bfc\u5165\u6570\u636e", "position_x": 50, "position_y": 150, "params": {}},
            {"operator_id": "missing_value_handler", "label": "\u7f3a\u5931\u503c\u5904\u7406", "position_x": 230, "position_y": 50, "params": {"strategy": "mean"}},
            {"operator_id": "label_encoder", "label": "\u7f16\u7801", "position_x": 230, "position_y": 200, "params": {"encoding_type": "onehot"}},
            {"operator_id": "scaler", "label": "\u7f29\u653e", "position_x": 410, "position_y": 50, "params": {"method": "standard"}},
            {"operator_id": "train_test_split", "label": "\u5212\u5206", "position_x": 590, "position_y": 150, "params": {"test_size": 0.2}},
            {"operator_id": "random_forest_train", "label": "\u968f\u673a\u68ee\u6797", "position_x": 770, "position_y": 0, "params": {"n_estimators": 200}},
            {"operator_id": "xgboost_train", "label": "XGBoost", "position_x": 770, "position_y": 120, "params": {"n_estimators": 150}},
            {"operator_id": "linear_model_train", "label": "\u7ebf\u6027\u6a21\u578b", "position_x": 770, "position_y": 240, "params": {}},
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
            {"source": 4, "target": 5, "source_port": "train", "target_port": "train"},
            {"source": 4, "target": 6, "source_port": "train", "target_port": "train"},
            {"source": 4, "target": 7, "source_port": "train", "target_port": "train"},
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
    wf = Workflow(project_id=uuid.UUID(project_id), name=tmpl["name"] + " (\u526f\u672c)", type="free", created_by=current_user.id)
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
            n = db.query(WorkflowNode).filter(WorkflowNode.id == uuid.UUID(node_map[node_idx])).first()
            if n:
                p = n.params or {}
                p[param_name] = val
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
