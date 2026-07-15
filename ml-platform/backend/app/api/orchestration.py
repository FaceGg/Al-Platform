import uuid

from fastapi import APIRouter, Depends, HTTPException, Body
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.user import User
from app.api.auth import get_current_user
from app.models.agent import Agent, AgentTask, AgentMessage
from app.engine.orchestrator import Orchestrator

router = APIRouter(prefix="/api/orchestration", tags=["orchestration"])

_orchestrator = None


def get_orchestrator():
    global _orchestrator
    if _orchestrator is None:
        from app.config import settings
        _orchestrator = Orchestrator(None, settings.llm_api_url, settings.llm_api_key)
    return _orchestrator


@router.post("/plan")
def plan_task(data: dict = Body(...), current_user=Depends(get_current_user)):
    orch = get_orchestrator()
    subtasks = orch.decompose_with_llm(data.get("task_description", ""))
    return {"subtasks": subtasks}


@router.get("/reviews")
def list_pending_reviews(current_user=Depends(get_current_user)):
    orch = get_orchestrator()
    return {"reviews": orch.get_pending_reviews()}


@router.post("/reviews/{task_id}")
def submit_review(task_id: str, data: dict = Body(...), db=Depends(get_db)):
    orch = get_orchestrator()
    result = orch.submit_review(task_id, data.get("approved", False), data.get("comment", ""))
    if result["status"] == "ok":
        task = db.query(AgentTask).filter(AgentTask.id == uuid.UUID(task_id)).first()
        if task:
            task.review_status = "approved" if data.get("approved") else "rejected"
            task.review_comment = data.get("comment", "")
            if data.get("approved"):
                task.status = "in_progress"
            db.commit()
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
def list_task_messages(task_id: str, db=Depends(get_db)):
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
def send_agent_message(task_id: str, data: dict = Body(...), db=Depends(get_db)):
    msg = AgentMessage(
        task_id=uuid.UUID(task_id),
        from_agent_id=uuid.UUID(data["from_agent_id"]) if data.get("from_agent_id") else None,
        to_agent_id=uuid.UUID(data["to_agent_id"]) if data.get("to_agent_id") else None,
        message_type=data.get("message_type", "info"),
        content=data.get("content", ""),
    )
    db.add(msg)
    db.commit()
    db.refresh(msg)
    return {"id": str(msg.id), "status": "sent"}


@router.put("/agents/{agent_id}")
def update_agent(agent_id: str, data: dict = Body(...), db=Depends(get_db)):
    agent = db.query(Agent).filter(Agent.id == uuid.UUID(agent_id)).first()
    if not agent:
        raise HTTPException(404, "Agent not found")
    for key in ["name", "description", "model_name", "is_active", "config"]:
        if key in data:
            setattr(agent, key, data[key])
    db.commit()
    return {"status": "ok"}


@router.delete("/agents/{agent_id}")
def delete_agent(agent_id: str, db=Depends(get_db)):
    agent = db.query(Agent).filter(Agent.id == uuid.UUID(agent_id)).first()
    if not agent:
        raise HTTPException(404, "Agent not found")
    db.delete(agent)
    db.commit()
    return {"status": "deleted"}


@router.put("/tasks/{task_id}")
def update_task(task_id: str, data: dict = Body(...), db=Depends(get_db)):
    task = db.query(AgentTask).filter(AgentTask.id == uuid.UUID(task_id)).first()
    if not task:
        raise HTTPException(404, "Task not found")
    for key in ["name", "description", "status", "priority", "assigned_agent_id", "requires_review"]:
        if key in data:
            if key == "assigned_agent_id" and data[key]:
                setattr(task, key, uuid.UUID(data[key]))
            else:
                setattr(task, key, data[key])
    db.commit()
    return {"status": "ok"}


@router.delete("/tasks/{task_id}")
def delete_task(task_id: str, db=Depends(get_db)):
    task = db.query(AgentTask).filter(AgentTask.id == uuid.UUID(task_id)).first()
    if not task:
        raise HTTPException(404, "Task not found")
    db.delete(task)
    db.commit()
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
def create_agent_task(data: dict = Body(...), db=Depends(get_db), current_user=Depends(get_current_user)):
    task = AgentTask(
        name=data["name"],
        description=data.get("description", ""),
        workflow_id=data.get("workflow_id"),
        input_data=data.get("input_data", {}),
        priority=data.get("priority", 0),
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    return {"id": str(task.id), "name": task.name, "status": task.status}


@router.get("/tasks")
def list_agent_tasks(workflow_id: str = None, db=Depends(get_db), current_user=Depends(get_current_user)):
    q = db.query(AgentTask)
    if workflow_id:
        q = q.filter(AgentTask.workflow_id == uuid.UUID(workflow_id))
    tasks = q.order_by(AgentTask.created_at.desc()).all()
    return [
        {"id": str(t.id), "name": t.name, "status": t.status, "review_status": t.review_status}
        for t in tasks
    ]


@router.get("/tasks/{task_id}")
def get_task_detail(task_id: str, db=Depends(get_db)):
    task = db.query(AgentTask).filter(AgentTask.id == uuid.UUID(task_id)).first()
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
def send_message(data: dict = Body(...), db=Depends(get_db)):
    msg = AgentMessage(
        task_id=uuid.UUID(data["task_id"]),
        from_agent_id=data.get("from_agent_id"),
        to_agent_id=data.get("to_agent_id"),
        message_type=data.get("message_type", "info"),
        content=data.get("content", ""),
    )
    db.add(msg)
    db.commit()
    return {"id": str(msg.id)}



from pydantic import BaseModel
from typing import List

class BatchDeleteRequest(BaseModel):
    ids: List[str]

@router.post("/batch-delete", status_code=200)
def batch_delete_agent_tasks(
    data: BatchDeleteRequest,
    db: Session = Depends(get_db),
):
    deleted = 0
    for tid_str in data.ids:
        try:
            uid = uuid.UUID(tid_str)
        except ValueError:
            continue
        task = db.query(AgentTask).filter(AgentTask.id == uid).first()
        if not task:
            continue
        db.query(AgentMessage).filter(AgentMessage.task_id == uid).delete()
        db.delete(task)
        deleted += 1
    db.commit()
    return {"deleted": deleted}

@router.post("/agents/batch-delete", status_code=200)
def batch_delete_agents(
    data: BatchDeleteRequest,
    db: Session = Depends(get_db),
):
    deleted = 0
    for aid_str in data.ids:
        try:
            uid = uuid.UUID(aid_str)
        except ValueError:
            continue
        agent = db.query(Agent).filter(Agent.id == uid).first()
        if not agent:
            continue
        db.delete(agent)
        deleted += 1
    db.commit()
    return {"deleted": deleted}
