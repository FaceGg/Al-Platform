import uuid

from sqlalchemy import Column, String, Text, DateTime, ForeignKey, Integer
from sqlalchemy import JSON
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.database import Base


class WorkflowRun(Base):
    __tablename__ = "workflow_runs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workflow_id = Column(UUID(as_uuid=True), ForeignKey("workflows.id", ondelete="CASCADE"), nullable=False)
    status = Column(String(16), default="pending")
    started_at = Column(DateTime)
    finished_at = Column(DateTime)
    error_message = Column(Text)
    error_code = Column(String(64))
    error_details = Column(JSON)
    workflow_version = Column(Integer)
    workflow_snapshot = Column(JSON)
    logs = Column(JSON, default=list)
    cancel_requested_at = Column(DateTime)
    cancelled_at = Column(DateTime)
    triggered_by = Column(UUID(as_uuid=True), ForeignKey("users.id"))
    task_id = Column(String(128), index=True)
    queue_name = Column(String(64))
    worker_id = Column(String(128))
    heartbeat_at = Column(DateTime)

    workflow = relationship("Workflow", back_populates="runs")
    triggered_by_user = relationship("User", back_populates="triggered_runs")
    node_runs = relationship("NodeRun", back_populates="run", cascade="all, delete-orphan")


class NodeRun(Base):
    __tablename__ = "node_runs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    run_id = Column(UUID(as_uuid=True), ForeignKey("workflow_runs.id", ondelete="CASCADE"), nullable=False)
    node_id = Column(UUID(as_uuid=True), ForeignKey("nodes.id", ondelete="SET NULL"))
    status = Column(String(16), default="pending")
    attempt = Column(Integer, default=1, nullable=False)
    result = Column(JSON)
    output_meta = Column(JSON)
    preview_data = Column(Text)
    error_message = Column(Text)
    error_code = Column(String(64))
    error_details = Column(JSON)
    duration_ms = Column(Integer)
    logs = Column(JSON, default=list)
    started_at = Column(DateTime)
    finished_at = Column(DateTime)

    run = relationship("WorkflowRun", back_populates="node_runs")
    node = relationship("WorkflowNode", back_populates="node_runs")
