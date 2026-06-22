import uuid

from sqlalchemy import Column, String, Text, DateTime, ForeignKey, func, BigInteger, Boolean, Float, Integer
from sqlalchemy import JSON
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.database import Base


class TrainingJob(Base):
    __tablename__ = "training_jobs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id"), nullable=False)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    name = Column(String(128), nullable=False)
    operator_id = Column(String(64))
    params = Column(JSON, default=dict)
    dataset_path = Column(String(512))
    status = Column(String(16), default="pending")  # pending/running/completed/failed
    metrics = Column(JSON, default=dict)
    model_path = Column(String(512))
    error_message = Column(Text)
    started_at = Column(DateTime)
    finished_at = Column(DateTime)
    created_at = Column(DateTime, server_default=func.now())
    # 模型训练增强字段
    early_stopping = Column(Boolean, default=False)
    checkpoint_path = Column(String(512), default="")
    model_version = Column(String(32), default="v1")
    epochs_completed = Column(Integer, default=0)
    best_metric_value = Column(Float)

    project = relationship("Project", backref="training_jobs")
    user = relationship("User", backref="training_jobs")
