import uuid
from contextlib import contextmanager

from fastapi import APIRouter, Depends, HTTPException, Body, Request
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.user import User
from app.api.auth import get_current_user
from app.models.agent import Agent, AgentTask, AgentMessage
from app.engine.orchestrator import Orchestrator
from app.api.project_security import audit_service, resolve_workflow_access
from app.services.audit import AuditIntent

router = APIRouter(prefix="/api/orchestration", tags=["orchestration"])
PROJECT_WRITE_ACTIONS = {
    "POST /api/orchestration/reviews/{task_id}": "agent_task.review",
    "POST /api/orchestration/tasks/{task_id}/messages": "agent_task.message",
    "PUT /api/orchestration/tasks/{task_id}": "agent_task.update",
    "DELETE /api/orchestration/tasks/{task_id}": "agent_task.delete",
    "POST /api/orchestration/tasks": "agent_task.create",
    "POST /api/orchestration/messages": "agent_task.message",
    "POST /api/orchestration/batch-delete": "agent_task.batch_delete",
}

_orchestrator = None


def get_orchestrator():
    global _orchestrator
    if _orchestrator is None:
        from app.config import settings
        _orchestrator = Orchestrator(None, settings.llm_api_url, settings.llm_api_key)
    return _orchestrator


def _task_for_user(db, task_id, user):
    task = db.query(AgentTask).filter(AgentTask.id == uuid.UUID(str(task_id))).first()
    if task is None:
        return None
    if task.workflow_id is not None:
        try:
            resolve_workflow_access(db, task.workflow_id, user.id)
        except HTTPException:
            return None
    return task


@contextmanager
def _task_action(db, task, request, actor, permission, action, changes=None):
    if task.workflow_id is None:
        yield
        db.commit()
        return
    workflow, access = resolve_workflow_access(db, task.workflow_id, actor.id)
    with audit_service(db).project_action(
        db, request=request, actor=actor, access=access, permission=permission,
        intent=AuditIntent(
            project_id=workflow.project_id, action=action,
            resource_type="agent_task", resource_id=str(task.id),
            changes=changes or {},
        ),
        allowed_changes=set((changes or {}).keys()),
    ):
        yield


@router.post("/plan")
def plan_task(
    data: dict = Body(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    task_description = str(data.get("task_description") or "").strip()
    task_id = data.get("task_id")
    if task_id:
        task = _task_for_user(db, task_id, current_user)
        if task is None:
            raise HTTPException(404, "Task not found")
        task_description = task_description or task.description.strip() or task.name.strip()
    if not task_description:
        raise HTTPException(422, "Task description is required")
    orch = get_orchestrator()
    subtasks = orch.decompose_with_llm(task_description)
    return {"task_id": str(task_id) if task_id else None, "subtasks": subtasks}


@router.get("/reviews")
def list_pending_reviews(current_user=Depends(get_current_user)):
    orch = get_orchestrator()
    return {"reviews": orch.get_pending_reviews()}


@router.post("/reviews/{task_id}")
def submit_review(
    task_id: str,
    request: Request,
    data: dict = Body(...),
    db=Depends(get_db),
    current_user=Depends(get_current_user),
):
    task = _task_for_user(db, task_id, current_user)
    if task is None:
        raise HTTPException(404, "Task not found")
    orch = get_orchestrator()
    with _task_action(
        db, task, request, current_user, "execution.operate", "agent_task.review",
        {"approved": bool(data.get("approved"))},
    ):
        result = orch.submit_review(
            task_id, data.get("approved", False), data.get("comment", ""),
        )
        if result["status"] == "ok":
            task.review_status = "approved" if data.get("approved") else "rejected"
            task.review_comment = data.get("comment", "")
            if data.get("approved"):
                task.status = "in_progress"
    return result


@router.post("/agents")
def create_agent(data: dict = Body(...), db=Depends(get_db), current_user=Depends(get_current_user)):
    agent = Agent(
        name=data["name"],
        agent_type=data.get("agent_type", "executor"),
        description=data.get("description", ""),
        model_name=data.get("model_name", ""),
        config=data.get("config", {}),
        created_by=current_user.id,
    )
    db.add(agent)
    db.commit()
    db.refresh(agent)
    return {"id": str(agent.id), "name": agent.name, "agent_type": agent.agent_type}



# --------------------------------------------------------------------------
# Agent Communication (Message) Endpoints
# --------------------------------------------------------------------------

@router.get("/tasks/{task_id}/messages")
def list_task_messages(
    task_id: str, db=Depends(get_db), current_user=Depends(get_current_user),
):
    task = _task_for_user(db, task_id, current_user)
    if task is None:
        raise HTTPException(404, "Task not found")
    msgs = db.query(AgentMessage).filter(AgentMessage.task_id == uuid.UUID(task_id)).order_by(AgentMessage.created_at.asc()).all()
    return {"items": [
        {
            "id": str(m.id), "task_id": str(m.task_id),
            "from_agent_id": str(m.from_agent_id) if m.from_agent_id else None,
            "to_agent_id": str(m.to_agent_id) if m.to_agent_id else None,
            "message_type": m.message_type, "content": m.content,
            "metadata": m.msg_metadata, "created_at": m.created_at.isoformat() if m.created_at else None,
        } for m in msgs
    ]}


@router.post("/tasks/{task_id}/messages")
def send_agent_message(
    task_id: str,
    request: Request,
    data: dict = Body(...),
    db=Depends(get_db),
    current_user=Depends(get_current_user),
):
    task = _task_for_user(db, task_id, current_user)
    if task is None:
        raise HTTPException(404, "Task not found")
    msg = AgentMessage(
        task_id=uuid.UUID(task_id),
        from_agent_id=uuid.UUID(data["from_agent_id"]) if data.get("from_agent_id") else None,
        to_agent_id=uuid.UUID(data["to_agent_id"]) if data.get("to_agent_id") else None,
        message_type=data.get("message_type", "info"),
        content=data.get("content", ""),
    )
    with _task_action(
        db, task, request, current_user, "execution.operate", "agent_task.message",
        {"message_type": msg.message_type},
    ):
        db.add(msg)
    db.refresh(msg)
    return {"id": str(msg.id), "status": "sent"}


def _agent_for_user(db: Session, agent_id: str, user_id):
    try:
        identifier = uuid.UUID(str(agent_id))
    except (TypeError, ValueError, AttributeError):
        return None
    return db.query(Agent).filter(
        Agent.id == identifier,
        Agent.created_by == user_id,
    ).first()


def _delete_agent(db: Session, agent: Agent) -> None:
    db.query(AgentTask).filter(AgentTask.assigned_agent_id == agent.id).update(
        {AgentTask.assigned_agent_id: None}, synchronize_session=False,
    )
    db.query(AgentMessage).filter(AgentMessage.from_agent_id == agent.id).update(
        {AgentMessage.from_agent_id: None}, synchronize_session=False,
    )
    db.query(AgentMessage).filter(AgentMessage.to_agent_id == agent.id).update(
        {AgentMessage.to_agent_id: None}, synchronize_session=False,
    )
    db.delete(agent)


@router.put("/agents/{agent_id}")
def update_agent(
    agent_id: str,
    data: dict = Body(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    agent = _agent_for_user(db, agent_id, current_user.id)
    if not agent:
        raise HTTPException(404, "Agent not found")
    for key in ["name", "description", "model_name", "is_active", "config"]:
        if key in data:
            setattr(agent, key, data[key])
    db.commit()
    return {"status": "ok"}


@router.delete("/agents/{agent_id}")
def delete_agent(
    agent_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    agent = _agent_for_user(db, agent_id, current_user.id)
    if not agent:
        raise HTTPException(404, "Agent not found")
    _delete_agent(db, agent)
    db.commit()
    return {"status": "deleted"}


@router.put("/tasks/{task_id}")
def update_task(
    task_id: str,
    request: Request,
    data: dict = Body(...),
    db=Depends(get_db),
    current_user=Depends(get_current_user),
):
    task = _task_for_user(db, task_id, current_user)
    if not task:
        raise HTTPException(404, "Task not found")
    keys = {"name", "description", "status", "priority", "assigned_agent_id", "requires_review"}
    changes = {key: data[key] for key in keys if key in data}
    with _task_action(
        db, task, request, current_user, "execution.operate", "agent_task.update", changes,
    ):
        for key, value in changes.items():
            setattr(task, key, uuid.UUID(value) if key == "assigned_agent_id" and value else value)
    return {"status": "ok"}


@router.delete("/tasks/{task_id}")
def delete_task(
    task_id: str,
    request: Request,
    db=Depends(get_db),
    current_user=Depends(get_current_user),
):
    task = _task_for_user(db, task_id, current_user)
    if not task:
        raise HTTPException(404, "Task not found")
    with _task_action(
        db, task, request, current_user, "execution.operate", "agent_task.delete",
    ):
        db.delete(task)
    return {"status": "deleted"}
@router.get("/agents")
def list_agents(db=Depends(get_db), current_user=Depends(get_current_user)):
    agents = db.query(Agent).filter(Agent.created_by == current_user.id).all()
    return [
        {
            "id": str(a.id),
            "name": a.name,
            "agent_type": a.agent_type,
            "is_active": a.is_active,
            "model_name": a.model_name,
        }
        for a in agents
    ]


@router.post("/tasks")
def create_agent_task(
    request: Request,
    data: dict = Body(...),
    db=Depends(get_db),
    current_user=Depends(get_current_user),
):
    workflow_id = uuid.UUID(data["workflow_id"]) if data.get("workflow_id") else None
    task = AgentTask(
        id=uuid.uuid4(),
        name=data["name"],
        description=data.get("description", ""),
        workflow_id=workflow_id,
        input_data=data.get("input_data", {}),
        priority=data.get("priority", 0),
    )
    if workflow_id is None:
        db.add(task)
        db.commit()
    else:
        workflow, access = resolve_workflow_access(db, workflow_id, current_user.id)
        with audit_service(db).project_action(
            db, request=request, actor=current_user, access=access,
            permission="execution.operate",
            intent=AuditIntent(
                project_id=workflow.project_id, action="agent_task.create",
                resource_type="agent_task", resource_id=str(task.id),
                changes={"name": task.name},
            ),
            allowed_changes={"name"},
        ):
            db.add(task)
    db.refresh(task)
    return {"id": str(task.id), "name": task.name, "status": task.status}


@router.get("/tasks")
def list_agent_tasks(workflow_id: str = None, db=Depends(get_db), current_user=Depends(get_current_user)):
    q = db.query(AgentTask)
    if workflow_id:
        workflow, _ = resolve_workflow_access(db, workflow_id, current_user.id)
        q = q.filter(AgentTask.workflow_id == workflow.id)
    tasks = q.order_by(AgentTask.created_at.desc()).all()
    if workflow_id is None:
        tasks = [task for task in tasks if _task_for_user(db, task.id, current_user)]
    return [
        {
            "id": str(t.id),
            "name": t.name,
            "description": t.description or "",
            "status": t.status,
            "review_status": t.review_status,
            "priority": t.priority,
            "assigned_agent_id": str(t.assigned_agent_id) if t.assigned_agent_id else None,
            "requires_review": bool(t.requires_review),
            "created_at": t.created_at.isoformat() if t.created_at else None,
        }
        for t in tasks
    ]


@router.get("/tasks/{task_id}")
def get_task_detail(
    task_id: str, db=Depends(get_db), current_user=Depends(get_current_user),
):
    task = _task_for_user(db, task_id, current_user)
    if not task:
        raise HTTPException(404)
    messages = db.query(AgentMessage).filter(AgentMessage.task_id == task.id).all()
    return {
        "id": str(task.id),
        "name": task.name,
        "status": task.status,
        "input": task.input_data,
        "output": task.output_data,
        "messages": [
            {"id": str(m.id), "type": m.message_type, "content": m.content} for m in messages
        ],
    }


@router.post("/messages")
def send_message(
    request: Request,
    data: dict = Body(...),
    db=Depends(get_db),
    current_user=Depends(get_current_user),
):
    task = _task_for_user(db, data["task_id"], current_user)
    if task is None:
        raise HTTPException(404, "Task not found")
    msg = AgentMessage(
        task_id=uuid.UUID(data["task_id"]),
        from_agent_id=uuid.UUID(data["from_agent_id"]) if data.get("from_agent_id") else None,
        to_agent_id=uuid.UUID(data["to_agent_id"]) if data.get("to_agent_id") else None,
        message_type=data.get("message_type", "info"),
        content=data.get("content", ""),
    )
    with _task_action(
        db, task, request, current_user, "execution.operate", "agent_task.message",
        {"message_type": msg.message_type},
    ):
        db.add(msg)
    return {"id": str(msg.id)}



from pydantic import BaseModel
from typing import List

class BatchDeleteRequest(BaseModel):
    ids: List[str]

@router.post("/batch-delete", status_code=200)
def batch_delete_agent_tasks(
    data: BatchDeleteRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    deleted = 0
    for tid_str in data.ids:
        try:
            uid = uuid.UUID(tid_str)
        except ValueError:
            continue
        task = _task_for_user(db, uid, current_user)
        if not task:
            continue
        with _task_action(
            db, task, request, current_user, "execution.operate", "agent_task.batch_delete",
        ):
            db.query(AgentMessage).filter(AgentMessage.task_id == uid).delete()
            db.delete(task)
        deleted += 1
    return {"deleted": deleted}

@router.post("/agents/batch-delete", status_code=200)
def batch_delete_agents(
    data: BatchDeleteRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    deleted = 0
    for aid_str in data.ids:
        try:
            uid = uuid.UUID(aid_str)
        except ValueError:
            continue
        agent = db.query(Agent).filter(
            Agent.id == uid,
            Agent.created_by == current_user.id,
        ).first()
        if not agent:
            continue
        _delete_agent(db, agent)
        deleted += 1
    db.commit()
    return {"deleted": deleted}
