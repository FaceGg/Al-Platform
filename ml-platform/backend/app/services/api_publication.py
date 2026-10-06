"""Idempotent publication of executable platform resources as internal APIs."""

import uuid
from datetime import datetime, timezone

from app.models.api_model import PlatformAPI
from app.models.model_registry import InferenceDeployment
from app.models.workflow import Workflow
from app.models.workflow_version import WorkflowVersion
from app.services.project_access import ProjectAccessError, ProjectAccessService


class APIPublicationError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


# Serving workflows must not (re)train per invoke call; the model comes from a
# frozen artifact via the load_model_artifact operator instead.
TRAINING_OPERATOR_IDS = frozenset({
    "xgboost_train", "random_forest_train", "random_forest_regression",
    "linear_model_train", "decision_tree", "naive_bayes", "knn", "svm",
    "logistic_regression", "svm_regression", "kmeans_clustering", "dbscan",
    "apriori", "fp_growth", "optimize_grid", "optimize_evolutionary",
})


def _deployment(db, deployment_id: str | uuid.UUID, actor_id: uuid.UUID) -> InferenceDeployment:
    try:
        source_uuid = deployment_id if isinstance(deployment_id, uuid.UUID) else uuid.UUID(str(deployment_id))
    except (TypeError, ValueError) as error:
        raise APIPublicationError("DEPLOYMENT_NOT_FOUND", "Deployment not found") from error
    deployment = db.query(InferenceDeployment).filter(InferenceDeployment.id == source_uuid).first()
    if deployment is None:
        raise APIPublicationError("DEPLOYMENT_NOT_FOUND", "Deployment not found")
    try:
        ProjectAccessService().require(db, deployment.project_id, actor_id, "inference.operate")
    except ProjectAccessError as error:
        code = "DEPLOYMENT_NOT_FOUND" if error.hidden else "DEPLOYMENT_PERMISSION_DENIED"
        raise APIPublicationError(code, "Deployment is not accessible") from error
    return deployment


def publish_deployment(db, deployment_id: str | uuid.UUID, actor_id: uuid.UUID) -> PlatformAPI:
    deployment = _deployment(db, deployment_id, actor_id)
    if deployment.desired_state != "running" or deployment.observed_state != "running":
        raise APIPublicationError("DEPLOYMENT_NOT_READY", "Only running deployments can be published")
    version = deployment.model_version
    api_version = f"v{version.version_number}"
    existing = db.query(PlatformAPI).filter(
        PlatformAPI.source_kind == "model",
        PlatformAPI.source_id == deployment.id,
        PlatformAPI.version == api_version,
    ).first()
    now = datetime.now(timezone.utc)
    if existing is not None:
        existing.status = "published"
        existing.published_at = now
        existing.last_error = None
        db.commit()
        db.refresh(existing)
        return existing
    api = PlatformAPI(
        name=deployment.name, api_type="model", algorithm_type=version.algorithm or "",
        endpoint=f"/api/inference-deployments/{deployment.id}/predict", method="POST",
        version=api_version, status="published", source_kind="model", source_id=deployment.id,
        description=f"Inference API for deployment {deployment.name}",
        request_schema={"records": version.feature_schema or []}, response_schema=version.output_schema or {},
        owner_id=actor_id, is_public=False, published_at=now,
    )
    db.add(api)
    db.commit()
    db.refresh(api)
    return api


def unpublish_deployment(db, deployment_id: str | uuid.UUID, actor_id: uuid.UUID) -> PlatformAPI:
    deployment = _deployment(db, deployment_id, actor_id)
    api = db.query(PlatformAPI).filter(
        PlatformAPI.source_kind == "model", PlatformAPI.source_id == deployment.id,
    ).order_by(PlatformAPI.created_at.desc()).first()
    if api is None:
        raise APIPublicationError("API_NOT_FOUND", "Published deployment API not found")
    api.status = "offline"
    db.commit()
    db.refresh(api)
    return api


def sync_deployment_publication(
    db,
    deployment_id: str | uuid.UUID,
    actor_id: uuid.UUID,
    *,
    running: bool,
) -> PlatformAPI | None:
    """Synchronize the API catalog after a committed runtime state change."""
    if running:
        return publish_deployment(db, deployment_id, actor_id)

    deployment = _deployment(db, deployment_id, actor_id)
    api = db.query(PlatformAPI).filter(
        PlatformAPI.source_kind == "model",
        PlatformAPI.source_id == deployment.id,
    ).order_by(PlatformAPI.created_at.desc()).first()
    if api is None:
        return None
    api.status = "offline"
    db.commit()
    db.refresh(api)
    return api


def _workflow_version(db, workflow_id, version_number, actor_id) -> tuple[Workflow, WorkflowVersion]:
    try:
        workflow_uuid = workflow_id if isinstance(workflow_id, uuid.UUID) else uuid.UUID(str(workflow_id))
    except (TypeError, ValueError) as error:
        raise APIPublicationError("WORKFLOW_NOT_FOUND", "Workflow not found") from error
    workflow = db.query(Workflow).filter(Workflow.id == workflow_uuid).first()
    if workflow is None:
        raise APIPublicationError("WORKFLOW_NOT_FOUND", "Workflow not found")
    try:
        ProjectAccessService().require(db, workflow.project_id, actor_id, "resource.create")
    except ProjectAccessError as error:
        code = "WORKFLOW_NOT_FOUND" if error.hidden else "WORKFLOW_PERMISSION_DENIED"
        raise APIPublicationError(code, "Workflow is not accessible") from error
    version = db.query(WorkflowVersion).filter(
        WorkflowVersion.workflow_id == workflow_uuid,
        WorkflowVersion.version == version_number,
    ).first()
    if version is None:
        raise APIPublicationError("WORKFLOW_VERSION_NOT_FOUND", "Published workflow version not found")
    return workflow, version


def _validate_serving_graph(version: WorkflowVersion) -> None:
    nodes = version.nodes_snapshot or []
    operator_ids = {str(node.get("operator_id") or "") for node in nodes}
    if "api_input" not in operator_ids:
        raise APIPublicationError(
            "SERVING_GRAPH_INVALID",
            "服务图缺少 api_input 节点：编排 API 的每行调用由该节点接收输入",
        )
    if "apply_model" not in operator_ids:
        raise APIPublicationError(
            "SERVING_GRAPH_INVALID",
            "服务图缺少 apply_model 节点：推理由该节点完成",
        )
    training = sorted(operator_ids & TRAINING_OPERATOR_IDS)
    if training:
        raise APIPublicationError(
            "SERVING_GRAPH_HAS_TRAINING",
            "服务图不能包含训练/搜索算子（" + ", ".join(training) + "）；"
            "请用 load_model_artifact 绑定已训练的模型制品",
        )


def publish_workflow_version(
    db, workflow_id, version_number: int, actor_id: uuid.UUID,
) -> PlatformAPI:
    workflow, version = _workflow_version(db, workflow_id, version_number, actor_id)
    # Publication gate = serving-graph shape: the invoke runtime validates the
    # rest at call time, and serving graphs (api_input) can never succeed in a
    # normal canvas run, so a run-record gate would be unreachable here.
    _validate_serving_graph(version)
    api_version = f"v{version_number}"
    existing = db.query(PlatformAPI).filter(
        PlatformAPI.source_kind == "orchestration",
        PlatformAPI.source_id == version.id,
        PlatformAPI.version == api_version,
    ).first()
    now = datetime.now(timezone.utc)
    if existing is not None:
        existing.status = "published"
        existing.published_at = now
        existing.last_error = None
        db.commit()
        db.refresh(existing)
        return existing
    api = PlatformAPI(
        name=f"{workflow.name} {api_version}", api_type="orchestration",
        endpoint=f"/api/platform/apis/orchestration/{version.id}/invoke", method="POST",
        version=api_version, status="published", source_kind="orchestration",
        source_id=version.id, workflow_id=workflow.id,
        description=f"Orchestration invoke API for {workflow.name} {api_version}",
        request_schema={"record": "single row object"},
        response_schema={"records": "output rows", "branch": "taken condition branch"},
        owner_id=actor_id, is_public=False, published_at=now,
    )
    db.add(api)
    db.commit()
    db.refresh(api)
    return api


def unpublish_workflow_version(db, workflow_id, version_number: int, actor_id: uuid.UUID) -> PlatformAPI:
    workflow, version = _workflow_version(db, workflow_id, version_number, actor_id)
    api = db.query(PlatformAPI).filter(
        PlatformAPI.source_kind == "orchestration", PlatformAPI.source_id == version.id,
    ).order_by(PlatformAPI.created_at.desc()).first()
    if api is None:
        raise APIPublicationError("API_NOT_FOUND", "Published workflow API not found")
    api.status = "offline"
    db.commit()
    db.refresh(api)
    return api


def sync_workflow_publication(db, workflow_id) -> int:
    """Take orchestration APIs offline when their workflow disappears.

    Best-effort: used from delete paths where the workflow rows may already be
    gone (PlatformAPI.workflow_id is SET NULL by then, so match by endpoints).
    """
    try:
        workflow_uuid = uuid.UUID(str(workflow_id))
    except (TypeError, ValueError):
        return 0
    apis = db.query(PlatformAPI).filter(
        PlatformAPI.source_kind == "orchestration",
        PlatformAPI.status == "published",
    ).all()
    affected = 0
    for api in apis:
        belongs = api.workflow_id == workflow_uuid
        if not belongs and api.source_id is not None:
            version = db.query(WorkflowVersion).filter(
                WorkflowVersion.id == api.source_id).first()
            belongs = version is None or version.workflow_id == workflow_uuid
        if belongs:
            api.status = "offline"
            affected += 1
    if affected:
        db.commit()
    return affected


def _chat_kb(db, kb_id, actor_id):
    """Owner-checked knowledge-base lookup for chat publication.

    Knowledge bases are owner-private across the knowledge module, so unlike
    deployment/workflow sources there is no project-access indirection here.
    Ownership mismatches return the same hidden 404 as a missing KB, matching
    the knowledge endpoints' convention.
    """
    from app.models.knowledge import KnowledgeBase

    try:
        kb_uuid = kb_id if isinstance(kb_id, uuid.UUID) else uuid.UUID(str(kb_id))
    except (TypeError, ValueError) as error:
        raise APIPublicationError("KNOWLEDGE_BASE_NOT_FOUND", "Knowledge base not found") from error
    kb = db.query(KnowledgeBase).filter(KnowledgeBase.id == kb_uuid).first()
    if kb is None or kb.owner_id != actor_id:
        raise APIPublicationError("KNOWLEDGE_BASE_NOT_FOUND", "Knowledge base not found")
    return kb


def publish_chat_api(db, kb_id, actor_id: uuid.UUID) -> PlatformAPI:
    kb = _chat_kb(db, kb_id, actor_id)
    api_version = "v1"
    existing = db.query(PlatformAPI).filter(
        PlatformAPI.source_kind == "chat",
        PlatformAPI.source_id == kb.id,
        PlatformAPI.version == api_version,
    ).first()
    now = datetime.now(timezone.utc)
    if existing is not None:
        existing.status = "published"
        existing.published_at = now
        existing.last_error = None
        db.commit()
        db.refresh(existing)
        return existing
    api = PlatformAPI(
        name=f"{kb.name} 对话", api_type="chat",
        endpoint=f"/api/platform/apis/chat/{kb.id}/invoke", method="POST",
        version=api_version, status="published", source_kind="chat",
        source_id=kb.id,
        description=f"RAG chat API bound to knowledge base {kb.name}",
        request_schema={
            "message": "string (required, non-empty)",
            "top_k": "integer 1-10 (optional)",
            "system_prompt": "string (optional)",
            "temperature": "number 0-1 (optional)",
        },
        response_schema={"reply": "string", "sources": "list", "usage": "object"},
        owner_id=actor_id, is_public=False, published_at=now,
    )
    db.add(api)
    db.commit()
    db.refresh(api)
    return api


def unpublish_chat_api(db, kb_id, actor_id: uuid.UUID) -> PlatformAPI:
    _chat_kb(db, kb_id, actor_id)
    api = db.query(PlatformAPI).filter(
        PlatformAPI.source_kind == "chat", PlatformAPI.source_id == _chat_source_id(db, kb_id),
    ).order_by(PlatformAPI.created_at.desc()).first()
    if api is None:
        raise APIPublicationError("API_NOT_FOUND", "Published chat API not found")
    api.status = "offline"
    db.commit()
    db.refresh(api)
    return api


def _chat_source_id(db, kb_id) -> uuid.UUID:
    return kb_id if isinstance(kb_id, uuid.UUID) else uuid.UUID(str(kb_id))


def sync_chat_publication(db, kb_id) -> int:
    """Take chat APIs offline when their knowledge base disappears.

    Best-effort: matches by source_id so it also works from delete paths after
    the knowledge-base row is gone.
    """
    try:
        kb_uuid = uuid.UUID(str(kb_id))
    except (TypeError, ValueError):
        return 0
    affected = db.query(PlatformAPI).filter(
        PlatformAPI.source_kind == "chat",
        PlatformAPI.source_id == kb_uuid,
        PlatformAPI.status == "published",
    ).update({"status": "offline"}, synchronize_session=False)
    if affected:
        db.commit()
    return affected
