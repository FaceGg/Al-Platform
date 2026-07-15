"""Trained model library ORM model."""
import uuid
from sqlalchemy import Column, String, Text, Float, DateTime, JSON, Boolean, ForeignKey, Integer, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from app.database import Base


class ModelLibrary(Base):
    __tablename__ = "model_library"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(256), nullable=False)
    algorithm_id = Column(UUID(as_uuid=True), ForeignKey("algorithms.id", ondelete="SET NULL"), nullable=True)
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id"), nullable=True)
    owner_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    version = Column(String(32), default="v1")
    status = Column(String(32), default="training")
    framework = Column(String(64), default="")
    backbone = Column(String(128), default="")
    description = Column(Text, default="")
    metrics = Column(JSON, default=dict)
    params = Column(JSON, default=dict)
    model_path = Column(String(512), default="")
    training_job_id = Column(UUID(as_uuid=True), ForeignKey("training_jobs.id"), nullable=True)
    dataset_artifact_id = Column(UUID(as_uuid=True), ForeignKey("artifacts.id"), nullable=True)
    model_artifact_id = Column(UUID(as_uuid=True), ForeignKey("artifacts.id"), nullable=True)
    file_size = Column(Integer, default=0)
    format = Column(String(32), default="pth")
    tags = Column(JSON, default=list)
    progress = Column(Float, default=0.0)
    is_public = Column(Boolean, default=False)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, onupdate=func.now())

    owner = relationship("User", backref="model_library_entries")
    algorithm = relationship("Algorithm", backref="trained_models")
    project = relationship("Project", backref="trained_models")
