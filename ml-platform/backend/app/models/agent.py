import uuid

from sqlalchemy import Column, String, Text, Float, ForeignKey, DateTime, JSON, Boolean, Integer, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.database import Base


class Agent(Base):
    __tablename__ = "agents"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(128), nullable=False)
    agent_type = Column(String(32), default="executor")  # planner/llm/executor/reviewer
    description = Column(Text, default="")
    model_name = Column(String(64), default="")
    config = Column(JSON, default=dict)
    is_active = Column(Boolean, default=True)
    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id"))
    created_at = Column(DateTime, server_default=func.now())

    created_by_user = relationship("User", backref="agents")


class AgentTask(Base):
    __tablename__ = "agent_tasks"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workflow_id = Column(UUID(as_uuid=True), ForeignKey("workflows.id"), nullable=True)
    name = Column(String(256), nullable=False)
    description = Column(Text, default="")
    status = Column(String(16), default="pending")
    parent_task_id = Column(UUID(as_uuid=True), ForeignKey("agent_tasks.id"), nullable=True)
    assigned_agent_id = Column(UUID(as_uuid=True), ForeignKey("agents.id"), nullable=True)
    input_data = Column(JSON, default=dict)
    output_data = Column(JSON, default=dict)
    priority = Column(Integer, default=0)
    requires_review = Column(Boolean, default=False)
    review_status = Column(String(16), default="none")  # none/pending/approved/rejected
    review_comment = Column(Text, default="")
    error_message = Column(Text)
    started_at = Column(DateTime)
    finished_at = Column(DateTime)
    created_at = Column(DateTime, server_default=func.now())

    children = relationship("AgentTask", backref="parent", remote_side="AgentTask.id")
    assigned_agent = relationship("Agent", foreign_keys=[assigned_agent_id], backref="tasks")


class AgentMessage(Base):
    __tablename__ = "agent_messages"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    task_id = Column(UUID(as_uuid=True), ForeignKey("agent_tasks.id"), nullable=False)
    from_agent_id = Column(UUID(as_uuid=True), ForeignKey("agents.id"), nullable=True)
    to_agent_id = Column(UUID(as_uuid=True), ForeignKey("agents.id"), nullable=True)
    message_type = Column(String(32), default="info")  # task/result/question/decision/review/info
    content = Column(Text, default="")
    msg_metadata = Column("metadata", JSON, default=dict)
    created_at = Column(DateTime, server_default=func.now())

    task = relationship("AgentTask", backref="messages")
    from_agent = relationship("Agent", foreign_keys=[from_agent_id], backref="sent_messages")
    to_agent = relationship("Agent", foreign_keys=[to_agent_id], backref="received_messages")
