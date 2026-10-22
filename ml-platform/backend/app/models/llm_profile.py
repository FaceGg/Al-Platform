"""LLM gateway model profiles (AutoML Agent plan, Task A1.2).

A registry of large-language-model endpoints (technical spec v0.9 ch.14).
API keys are stored Fernet-encrypted under ``LLM_MASTER_KEY`` and are
write-only over the API (reads return a masked suffix only).
"""

import uuid

from sqlalchemy import (
    Boolean,
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
    text,
)
from sqlalchemy.dialects.postgresql import UUID

from app.database import Base


class LLMProfile(Base):
    __tablename__ = "llm_profiles"
    __table_args__ = (
        CheckConstraint(
            "provider IN ('openai_compatible', 'custom')",
            name="ck_llm_profiles_provider",
        ),
        CheckConstraint(
            "deployment IN ('cloud', 'private')",
            name="ck_llm_profiles_deployment",
        ),
        Index(
            "ux_llm_profiles_single_default",
            "is_default",
            unique=True,
            sqlite_where=text("is_default = 1"),
            postgresql_where=text("is_default"),
        ),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(64), unique=True, nullable=False, index=True)
    provider = Column(String(32), nullable=False, default="openai_compatible")
    api_url = Column(String(512), nullable=False)
    api_key_encrypted = Column(Text, nullable=True)
    model_id = Column(String(128), nullable=False)
    temperature = Column(Float, nullable=True)
    max_tokens = Column(Integer, nullable=True)
    timeout_seconds = Column(Integer, nullable=False, default=60)
    purpose_tags = Column(JSON, nullable=False, default=list)
    deployment = Column(String(16), nullable=False, default="cloud")
    is_default = Column(Boolean, nullable=False, default=False)
    created_by = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    updated_at = Column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now()
    )
