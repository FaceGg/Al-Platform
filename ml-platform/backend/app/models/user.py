import uuid

from sqlalchemy import Column, String, DateTime, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.database import Base


class User(Base):
    __tablename__ = "users"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    username = Column(String(64), unique=True, nullable=False, index=True)
    password_hash = Column(String(256), nullable=False)
    role = Column(String(16), default="engineer")
    created_at = Column(DateTime, server_default=func.now())

    projects = relationship("Project", back_populates="owner")
    created_workflows = relationship("Workflow", back_populates="created_by_user")
    triggered_runs = relationship("WorkflowRun", back_populates="triggered_by_user")
    knowledge_bases = relationship("KnowledgeBase", back_populates="owner")
