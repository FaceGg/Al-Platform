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
            # 与 API 层 LLMProfileUpdate 的 pattern 及 PG 生产约束一致——
            # 此前缺 responses/anthropic，SQLite 按元数据建表即拦合法档案
            "provider IN ('openai_compatible', 'responses', 'anthropic', 'custom')",
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
    # 模型行启用开关：多模型可同时开启（is_default 仅标记平台默认，单选）
    enabled = Column(Boolean, nullable=False, default=True)
    # 供应商组 ID：同组 = 同一供应商下的多个模型（共享 URL/Key 语义）；
    # 重复添加同名供应商模板会生成新组（DeepSeek2 独立条目，不并入已有组）
    provider_group = Column(String(64), nullable=True, index=True)
    # ZCode 风格模型配置（上下文窗口/最大输出/输入类型/能力/推理等级与映射等）
    model_config_json = Column(JSON, nullable=True)
    created_by = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    updated_at = Column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now()
    )
