import uuid

from sqlalchemy import Column, String, Text, DateTime, ForeignKey, func, BigInteger, Boolean, Float, Integer
from sqlalchemy import JSON
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.database import Base


TERMINAL_TRAINING_STATUSES = frozenset({"completed", "failed", "cancelled"})


class TrainingJob(Base):
    __tablename__ = "training_jobs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    name = Column(String(128), nullable=False)
    operator_id = Column(String(64))
    params = Column(JSON, default=dict)
    dataset_path = Column(String(512))
    dataset_artifact_id = Column(UUID(as_uuid=True), ForeignKey("artifacts.id"), nullable=True)
    status = Column(String(16), default="pending")  # pending/running/completed/failed
    metrics = Column(JSON, default=dict)
    model_path = Column(String(512))
    model_artifact_id = Column(UUID(as_uuid=True), ForeignKey("artifacts.id"), nullable=True)
    model_library_id = Column(UUID(as_uuid=True), ForeignKey("model_library.id"), nullable=True)
    feature_schema = Column(JSON, default=list)
    target_schema = Column(JSON, default=dict)
    preprocessing = Column(JSON, default=dict)
    error_code = Column(String(64))
    error_details = Column(JSON)
    logs = Column(JSON, default=list)
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

    experiment_id = Column(
        UUID(as_uuid=True),
        ForeignKey("experiments.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    mlflow_run_id = Column(String(64), nullable=True, index=True)
    task_id = Column(String(128), nullable=True, index=True)
    worker_id = Column(String(128), nullable=True)
    heartbeat_at = Column(DateTime, nullable=True, index=True)
    attempt = Column(Integer, nullable=False, default=0)
    resumed_from_job_id = Column(
        UUID(as_uuid=True),
        ForeignKey("training_jobs.id", ondelete="SET NULL"),
        nullable=True,
    )
    resumed_from_run_id = Column(String(64), nullable=True)
    resume_checkpoint_uri = Column(String(1024), nullable=True)
    latest_checkpoint_uri = Column(String(1024), nullable=True)
    best_checkpoint_uri = Column(String(1024), nullable=True)
    current_epoch = Column(Integer, nullable=False, default=0)
    total_epochs = Column(Integer, nullable=True)
    monitor_name = Column(String(64), nullable=True)
    monitor_mode = Column(String(8), nullable=True)
    early_stopping_patience = Column(Integer, nullable=True)
    early_stopping_min_delta = Column(Float, nullable=True)
    restore_best = Column(Boolean, nullable=False, default=True)

    project = relationship("Project", backref="training_jobs")
    user = relationship("User", backref="training_jobs")
    experiment = relationship("Experiment", back_populates="training_jobs")
    resumed_from_job = relationship(
        "TrainingJob",
        remote_side=[id],
        foreign_keys=[resumed_from_job_id],
        backref="resumed_jobs",
    )
