"""Experience entry model (spec v0.9 §10.2/§16.5).

The structured thin kernel of the unified knowledge center: distilled entries
start in ``shadow`` (hits counted, not injected) and promote to ``active``
after a cooldown; human-sourced entries (chat save_insight) are directly
active at 0.75. Retirement filters retrieval immediately.
"""

import uuid

from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import UUID

from app.database import Base


class ExperienceEntry(Base):
    __tablename__ = "experience_entries"
    __table_args__ = (
        CheckConstraint(
            "status IN ('shadow','active','retired','superseded')",
            name="ck_experience_entries_status",
        ),
        CheckConstraint(
            "origin IN ('distilled','human')",
            name="ck_experience_entries_origin",
        ),
        CheckConstraint(
            "generality IN ('domain','cross-domain')",
            name="ck_experience_entries_generality",
        ),
        CheckConstraint("confidence >= 0.0 AND confidence <= 1.0",
                        name="ck_experience_entries_confidence"),
        Index(
            "ix_experience_entries_retrieval",
            "domain",
            "status",
            "confidence",
        ),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    domain = Column(String(64), nullable=False, default="cross-domain")
    situation = Column(Text, nullable=False)
    lesson = Column(Text, nullable=False)
    action = Column(Text, nullable=False)
    evidence_json = Column(JSON, nullable=False, default=dict)
    generality = Column(String(16), nullable=False, default="domain")
    confidence = Column(Float, nullable=False, default=0.5)
    origin = Column(String(16), nullable=False, default="distilled")
    status = Column(String(16), nullable=False, default="shadow")
    scope_project_ids = Column(JSON, nullable=False, default=list)
    source_tasks = Column(JSON, nullable=False, default=list)
    hit_count = Column(Integer, nullable=False, default=0)
    human_note = Column(Text, nullable=True)
    created_by = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    updated_at = Column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now()
    )
