from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import or_
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.project import Project
from app.models.workflow import Workflow, WorkflowNode, WorkflowEdge
from app.models.user import User
from app.schemas.workflow import WorkflowCreate, WorkflowSave, WorkflowResponse, NodeResponse, EdgeResponse
from app.api.auth import get_current_user
from app.api.project_security import audit_service, require_project_access, resolve_project_access
from app.services.audit import AuditIntent
from app.services.api_publication import sync_workflow_publication
from app.services.project_access import ProjectAccess, ProjectAccessService, ProjectRole

router = APIRouter(prefix="/api/projects", tags=["workflows"])
PROJECT_WRITE_ACTIONS = {
    "POST /api/projects/{project_id}/workflows": "workflow.create",
    "PUT /api/projects/{project_id}/workflows/{workflow_id}": "workflow.update",
    "DELETE /api/projects/{project_id}/workflows/{workflow_id}": "workflow.delete",
}


class TemplateSaveRequest(BaseModel):
    name: str | None = None
    scope: str = "project"  # project=仅当前项目；global=平台通用（需管理员）


class TemplateInstantiateRequest(BaseModel):
    name: str | None = None


def _build_workflow_response(workflow: Workflow) -> WorkflowResponse:
    return WorkflowResponse(
        id=workflow.id,
        project_id=workflow.project_id,
        name=workflow.name,
        description=workflow.description,
        type=workflow.type,
        nodes=[NodeResponse.model_validate(n) for n in workflow.nodes],
        edges=[EdgeResponse.model_validate(e) for e in workflow.edges],
        created_at=workflow.created_at,
        updated_at=workflow.updated_at,
    )


@router.get("/{project_id}/workflows")
def list_workflows(
    project_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    require_project_access(db, project_id, current_user.id, "project.read")
    workflows = db.query(Workflow).filter(
        Workflow.project_id == UUID(project_id),
        Workflow.is_template.is_(False),
    ).all()
    return [{"id": str(w.id), "name": w.name, "description": w.description, "created_at": w.created_at.isoformat() if w.created_at else None} for w in workflows]


# ----------------------------------------------------------------- templates
# 模板即标记 is_template=True 的工作流：保存为模板=复制当前图；从模板创建=
# 复制模板图到新工作流；编辑模板=直接打开画布修改（PUT 保存）——增删改天然支持。
# project_id 为空的是平台通用模板：不归属项目，全部项目可见可实例化；
# 保存/编辑/删除需平台管理员，实例化时清除项目绑定的制品/部署 ID 参数。

# 项目绑定参数：通用模板跨项目实例化时无意义（指向源项目工件），一律清除，
# 用户在画布下拉中重新选择目标项目的数据集/模型/部署。
PROJECT_BOUND_PARAM_KEYS = (
    "dataset_artifact_id",
    "retrain_dataset_artifact_id",
    "model_artifact_id",
    "swap_deployment_id",
)


@router.post("/{project_id}/workflows/{workflow_id}/save-as-template", status_code=201)
def save_workflow_as_template(
    project_id: str,
    workflow_id: str,
    data: TemplateSaveRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    access = resolve_project_access(db, project_id, current_user.id)
    project_uuid = access.project.id if access is not None else UUID(project_id)
    source = db.query(Workflow).filter(
        Workflow.id == UUID(workflow_id),
        Workflow.project_id == project_uuid,
    ).first()
    if not source:
        raise HTTPException(404, "Workflow not found")
    is_global = data.scope == "global"
    if is_global and not ProjectAccessService.is_platform_admin(db, current_user.id):
        raise HTTPException(403, "Only platform administrators can publish global templates")
    if data.scope not in ("project", "global"):
        raise HTTPException(422, "scope must be 'project' or 'global'")
    template = Workflow(
        project_id=None if is_global else project_uuid,
        name=(data.name or f"{source.name}-模板").strip()[:128],
        description=source.description,
        is_template=True,
        created_by=current_user.id,
    )
    db.add(template)
    db.flush()
    # 节点是新建的（新 UUID）：边必须经 源节点id→新节点id 映射转接，
    # 直接照抄源图的节点 id 会指向不存在的节点（连线丢失）。
    node_id_map = {}
    for node in source.nodes:
        copy = WorkflowNode(
            workflow_id=template.id, operator_id=node.operator_id, label=node.label,
            position_x=node.position_x, position_y=node.position_y, params=node.params,
        )
        db.add(copy)
        db.flush()
        node_id_map[node.id] = copy.id
    for edge in source.edges:
        db.add(WorkflowEdge(
            workflow_id=template.id, source_node_id=node_id_map[edge.source_node_id],
            source_port=edge.source_port, target_node_id=node_id_map[edge.target_node_id],
            target_port=edge.target_port,
        ))
    db.commit()
    db.refresh(template)
    return _build_workflow_response(template)


@router.get("/{project_id}/workflow-templates")
def list_workflow_templates(
    project_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    require_project_access(db, project_id, current_user.id, "project.read")
    templates = db.query(Workflow).filter(
        or_(
            Workflow.project_id == UUID(project_id),
            Workflow.project_id.is_(None),
        ),
        Workflow.is_template.is_(True),
    ).order_by(Workflow.created_at.desc()).all()
    return {
        "items": [
            {
                "id": str(t.id),
                "name": t.name,
                "description": t.description,
                "scope": "global" if t.project_id is None else "project",
                "node_count": len(t.nodes),
                "created_at": t.created_at.isoformat() if t.created_at else None,
                "updated_at": t.updated_at.isoformat() if t.updated_at else None,
            }
            for t in templates
        ],
        "total": len(templates),
    }


@router.post("/{project_id}/workflow-templates/{template_id}/instantiate", status_code=201)
def instantiate_workflow_template(
    project_id: str,
    template_id: str,
    data: TemplateInstantiateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    access = resolve_project_access(db, project_id, current_user.id)
    project_uuid = access.project.id if access is not None else UUID(project_id)
    template = db.query(Workflow).filter(
        Workflow.id == UUID(template_id),
        or_(
            Workflow.project_id == project_uuid,
            Workflow.project_id.is_(None),
        ),
        Workflow.is_template.is_(True),
    ).first()
    if not template:
        raise HTTPException(404, "Template not found")
    is_global_template = template.project_id is None
    workflow = Workflow(
        project_id=project_uuid,
        name=(data.name or template.name).strip()[:128],
        description=template.description,
        created_by=current_user.id,
    )
    db.add(workflow)
    db.flush()
    node_id_map = {}
    for node in template.nodes:
        node_params = dict(node.params or {})
        if is_global_template:
            for key in PROJECT_BOUND_PARAM_KEYS:
                node_params.pop(key, None)
        copy = WorkflowNode(
            workflow_id=workflow.id, operator_id=node.operator_id, label=node.label,
            position_x=node.position_x, position_y=node.position_y, params=node_params,
        )
        db.add(copy)
        db.flush()
        node_id_map[node.id] = copy.id
    for edge in template.edges:
        db.add(WorkflowEdge(
            workflow_id=workflow.id, source_node_id=node_id_map[edge.source_node_id],
            source_port=edge.source_port, target_node_id=node_id_map[edge.target_node_id],
            target_port=edge.target_port,
        ))
    db.commit()
    db.refresh(workflow)
    return _build_workflow_response(workflow)


@router.post("/{project_id}/workflows", response_model=WorkflowResponse, status_code=201)
def create_workflow(
    project_id: str,
    data: WorkflowCreate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    access = resolve_project_access(db, project_id, current_user.id)
    project_uuid = access.project.id if access is not None else UUID(project_id)

    with audit_service(db).project_action(
        db,
        request=request,
        actor=current_user,
        access=access,
        permission="resource.create",
        intent=AuditIntent(
            project_id=project_uuid,
            action="workflow.create",
            resource_type="workflow",
            changes={"name": data.name, "description": data.description},
        ),
        allowed_changes={"name", "description"},
    ):
        workflow = Workflow(
            project_id=project_uuid,
            name=data.name,
            description=data.description,
            created_by=current_user.id,
        )
        db.add(workflow)
        db.flush()

        client_id_map = {}
        for node_data in data.nodes:
            node = WorkflowNode(
                workflow_id=workflow.id,
                operator_id=node_data.operator_id,
                label=node_data.label,
                position_x=node_data.position.x,
                position_y=node_data.position.y,
                params=node_data.params,
            )
            db.add(node)
            db.flush()
            client_id_map[node_data.id] = node.id

        for edge_data in data.edges:
            # dict.get 的默认值是急切求值：client id 会被 UUID() 先炸，
            # 必须显式回退（client id 优先，否则按服务端 UUID 解析）。
            source_id = client_id_map.get(edge_data.source) or UUID(edge_data.source)
            target_id = client_id_map.get(edge_data.target) or UUID(edge_data.target)
            edge = WorkflowEdge(
                workflow_id=workflow.id,
                source_node_id=source_id,
                source_port=edge_data.source_port,
                target_node_id=target_id,
                target_port=edge_data.target_port,
            )
            db.add(edge)

    db.refresh(workflow)
    return _build_workflow_response(workflow)


@router.get("/{project_id}/workflows/{workflow_id}", response_model=WorkflowResponse)
def get_workflow(
    project_id: str,
    workflow_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    require_project_access(db, project_id, current_user.id, "project.read")
    workflow = db.query(Workflow).filter(
        Workflow.id == UUID(workflow_id),
        Workflow.project_id == UUID(project_id),
    ).first()
    if not workflow:
        raise HTTPException(404, "Workflow not found")
    return _build_workflow_response(workflow)


@router.put("/{project_id}/workflows/{workflow_id}", response_model=WorkflowResponse)
def save_workflow(
    project_id: str,
    workflow_id: str,
    data: WorkflowSave,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    access = resolve_project_access(db, project_id, current_user.id)
    project_uuid = access.project.id if access is not None else UUID(project_id)
    workflow = db.query(Workflow).filter(
        Workflow.id == UUID(workflow_id),
        Workflow.project_id == project_uuid,
    ).first()
    if not workflow:
        raise HTTPException(404, "Workflow not found")

    with audit_service(db).project_action(
        db,
        request=request,
        actor=current_user,
        access=access,
        permission="resource.update",
        intent=AuditIntent(
            project_id=project_uuid,
            action="workflow.update",
            resource_type="workflow",
            resource_id=str(workflow.id),
            changes=data.model_dump(exclude_none=True),
        ),
        allowed_changes={"name", "description"},
    ):
        if data.name is not None:
            workflow.name = data.name
        if data.description is not None:
            workflow.description = data.description

        db.query(WorkflowEdge).filter(WorkflowEdge.workflow_id == workflow.id).delete()
        db.query(WorkflowNode).filter(WorkflowNode.workflow_id == workflow.id).delete()
        db.flush()

        client_id_map = {}
        for node_data in data.nodes:
            node = WorkflowNode(
                workflow_id=workflow.id,
                operator_id=node_data.operator_id,
                label=node_data.label,
                position_x=node_data.position.x,
                position_y=node_data.position.y,
                params=node_data.params,
            )
            db.add(node)
            db.flush()
            client_id_map[node_data.id] = node.id

        for edge_data in data.edges:
            edge = WorkflowEdge(
                workflow_id=workflow.id,
                source_node_id=client_id_map.get(edge_data.source, edge_data.source),
                source_port=edge_data.source_port,
                target_node_id=client_id_map.get(edge_data.target, edge_data.target),
                target_port=edge_data.target_port,
            )
            db.add(edge)

    db.refresh(workflow)
    return _build_workflow_response(workflow)


@router.delete("/{project_id}/workflows/{workflow_id}", status_code=204)
def delete_workflow(
    project_id: str,
    workflow_id: str,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    access = resolve_project_access(db, project_id, current_user.id)
    project_uuid = access.project.id if access is not None else UUID(project_id)
    workflow = db.query(Workflow).filter(
        Workflow.id == UUID(workflow_id),
        Workflow.project_id == project_uuid,
    ).first()
    if not workflow:
        # 回退平台通用模板：删除权限经审计门校验（管理员放行，普通用户 403）。
        workflow = db.query(Workflow).filter(
            Workflow.id == UUID(workflow_id),
            Workflow.project_id.is_(None),
        ).first()
        if workflow:
            role = ProjectRole.OWNER if ProjectAccessService.is_platform_admin(
                db, current_user.id,
            ) else ProjectRole.VIEWER
            access = ProjectAccess(project=None, role=role)
            project_uuid = None
    if not workflow:
        raise HTTPException(404, "Workflow not found")
    with audit_service(db).project_action(
        db,
        request=request,
        actor=current_user,
        access=access,
        permission="resource.delete",
        intent=AuditIntent(
            project_id=project_uuid,
            action="workflow.delete",
            resource_type="workflow",
            resource_id=str(workflow.id),
        ),
        allowed_changes=set(),
    ):
        sync_workflow_publication(db, workflow.id)
        db.delete(workflow)
