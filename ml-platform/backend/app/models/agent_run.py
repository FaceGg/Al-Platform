"""Agent run model (AutoML Agent plan, Task A2.2).

One row per agent task execution: state machine, L1 run memory (per-round
digest the next round must carry), token accounting with budget fuse, and the
recorded LLM profile/model used (spec v0.9 §14.2 强制记录).
"""

import uuid

from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    func,
)
from sqlalchemy.dialects.postgresql import UUID

from app.database import Base


class AgentRun(Base):
    __tablename__ = "agent_runs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending','running','waiting_guidance','waiting_escalate',"
            "'accepted','failed','cancelled')",
            name="ck_agent_runs_status",
        ),
        CheckConstraint(
            "current_stage IN ('s1','s2','s3','s4','done')",
            name="ck_agent_runs_stage",
        ),
        Index("ix_agent_runs_project_created", "project_id", "created_at"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id = Column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="SET NULL"),
        nullable=True,
    )
    dataset_artifact_id = Column(UUID(as_uuid=True), nullable=True)
    target_column = Column(String(256), nullable=True)
    llm_profile_id = Column(
        UUID(as_uuid=True),
        ForeignKey("llm_profiles.id", ondelete="SET NULL"),
        nullable=True,
    )
    llm_model_id = Column(String(128), nullable=True)
    status = Column(String(32), nullable=False, default="pending")
    current_stage = Column(String(16), nullable=False, default="s1")
    round_count = Column(Integer, nullable=False, default=0)
    token_used = Column(Integer, nullable=False, default=0)
    token_budget = Column(Integer, nullable=True)
    error_code = Column(String(64), nullable=True)
    memory_json = Column(JSON, nullable=False, default=dict)
    result_json = Column(JSON, nullable=False, default=dict)
    # UserGuidance captured at submission time (spec §11): analysis/feature/
    # modeling/evaluation sections plus the step-by-step pause plan.
    guidance_json = Column(JSON, nullable=True)
    # Liveness heartbeat refreshed by the in-process executor; NULL marks rows
    # written before the column existed (swept as stale by recovery).
    heartbeat_at = Column(DateTime, nullable=True)
    created_by = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    updated_at = Column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now()
    )
