import uuid

from sqlalchemy import Column, DateTime, ForeignKey, Integer, JSON, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.database import Base


class WorkflowVersion(Base):
    __tablename__ = "workflow_versions"
    __table_args__ = (UniqueConstraint("workflow_id", "version", name="uq_workflow_version"),)

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workflow_id = Column(UUID(as_uuid=True), ForeignKey("workflows.id", ondelete="CASCADE"), nullable=False)
    version = Column(Integer, nullable=False)
    name = Column(String(128), nullable=False)
    description = Column(Text, default="")
    nodes_snapshot = Column(JSON, default=list, nullable=False)
    edges_snapshot = Column(JSON, default=list, nullable=False)
    published_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    published_at = Column(DateTime, server_default=func.now(), nullable=False)

    workflow = relationship("Workflow", back_populates="versions")
