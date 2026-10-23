"""Knowledge base binding model (spec v0.9 §16.2, AutoML Agent Task A6.1).

Per-KB configuration layer for the unified knowledge center: total switch,
scopes (projects / agent tasks / chat / agent S1), retrieval parameters and
experience-sync policy. The system partition (平台经验) cannot be disabled.
"""

import uuid

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    JSON,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID

from app.database import Base


class KBBinding(Base):
    __tablename__ = "kb_bindings"
    __table_args__ = (
        UniqueConstraint("kb_id", name="ux_kb_bindings_kb"),
        CheckConstraint(
            "retrieval_trigger IN ('auto','explicit')",
            name="ck_kb_bindings_trigger",
        ),
        CheckConstraint(
            "sync_human_review IN ('auto','pending')",
            name="ck_kb_bindings_human_review",
        ),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    kb_id = Column(
        UUID(as_uuid=True),
        ForeignKey("knowledge_bases.id", ondelete="CASCADE"),
        nullable=False,
    )
    is_system = Column(Boolean, nullable=False, default=False)
    enabled = Column(Boolean, nullable=False, default=True)
    scope_projects = Column(JSON, nullable=False, default=list)   # ["*"] or project ids
    scope_agent_tasks = Column(String(16), nullable=False, default="all")  # inherit|all|explicit
    scope_agent_task_ids = Column(JSON, nullable=False, default=list)
    scope_chat = Column(Boolean, nullable=False, default=True)
    scope_agent_s1 = Column(Boolean, nullable=False, default=True)
    retrieval_top_k = Column(Integer, nullable=False, default=5)
    retrieval_max_total_chars = Column(Integer, nullable=False, default=6000)
    retrieval_min_score = Column(Float, nullable=False, default=0.15)
    retrieval_trigger = Column(String(16), nullable=False, default="auto")
    sync_receive_experience = Column(Boolean, nullable=False, default=False)
    sync_experience_min_confidence = Column(Float, nullable=False, default=0.85)
    sync_human_review = Column(String(16), nullable=False, default="auto")
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    updated_at = Column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now()
    )
