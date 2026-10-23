"""Skill revision model (AutoML Agent plan, Task A4.1 — bounded RSI).

One row per SKILL.md revision proposal: debounce (single active proposal),
offline regression against a representative recipe sample, risk-tiered
approval, versioned activation with one-click rollback. Tightening-only is
enforced at proposal time (spec v0.9 §10.3).
"""

import uuid

from sqlalchemy import (
    Boolean,
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


class SkillRevision(Base):
    __tablename__ = "skill_revisions"
    __table_args__ = (
        CheckConstraint(
            "status IN ('proposed','regression_running','regression_failed',"
            "'pending_approval','auto_activated','activated','rejected','rolled_back')",
            name="ck_skill_revisions_status",
        ),
        CheckConstraint(
            "risk_level IN ('low','medium','high')",
            name="ck_skill_revisions_risk",
        ),
        Index("ix_skill_revisions_skill_status", "skill_name", "status"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    skill_name = Column(String(64), nullable=False, default="automl-agent")
    base_version = Column(Integer, nullable=False)
    new_version = Column(Integer, nullable=True)
    status = Column(String(32), nullable=False, default="proposed")
    risk_level = Column(String(16), nullable=False, default="medium")
    regression_passed = Column(Boolean, nullable=True)
    proposal_json = Column(JSON, nullable=False, default=dict)
    regression_json = Column(JSON, nullable=False, default=dict)
    basis_entries = Column(JSON, nullable=False, default=list)
    approved_by = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    updated_at = Column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now()
    )
