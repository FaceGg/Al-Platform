import uuid

from sqlalchemy import Column, DateTime, ForeignKey, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.database import Base


class Experiment(Base):
    __tablename__ = "experiments"
    __table_args__ = (
        UniqueConstraint("project_id", "name", name="uq_experiments_project_name"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id = Column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    name = Column(String(128), nullable=False)
    description = Column(Text, default="")
    mlflow_experiment_id = Column(String(64), nullable=False, unique=True, index=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    project = relationship("Project", backref="experiments")
    created_by_user = relationship("User", backref="created_experiments")
    training_jobs = relationship("TrainingJob", back_populates="experiment")
    automl_binding = relationship(
        "ExperimentAutoMLBinding",
        back_populates="experiment",
        cascade="all, delete-orphan",
        passive_deletes=True,
        uselist=False,
    )

    @property
    def automl_used(self) -> bool:
        return self.automl_binding is not None

    @property
    def automl_job_id(self):
        return self.automl_binding.job_id if self.automl_binding is not None else None


class ExperimentAutoMLBinding(Base):
    __tablename__ = "experiment_automl_bindings"

    experiment_id = Column(
        UUID(as_uuid=True),
        ForeignKey("experiments.id", ondelete="CASCADE"),
        primary_key=True,
    )
    job_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    created_at = Column(DateTime, nullable=False, server_default=func.now())

    experiment = relationship("Experiment", back_populates="automl_binding")
