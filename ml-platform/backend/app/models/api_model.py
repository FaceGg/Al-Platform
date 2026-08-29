"""API management model for platform APIs."""
import uuid
from sqlalchemy import Column, String, Text, Integer, DateTime, JSON, Boolean, ForeignKey, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from app.database import Base


class PlatformAPI(Base):
    __tablename__ = "platform_apis"
    __table_args__ = (
        UniqueConstraint(
            "source_kind",
            "source_id",
            "version",
            name="uq_platform_api_source_version",
        ),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(256), nullable=False)
    api_type = Column(String(32), default="model")  # model, orchestration, custom
    algorithm_type = Column(String(64), default="")
    endpoint = Column(String(512), default="")
    method = Column(String(16), default="POST")
    version = Column(String(32), default="v1")
    status = Column(String(16), default="published")  # published, offline, failed
    source_kind = Column(String(32), default="custom", nullable=False)
    source_id = Column(UUID(as_uuid=True), nullable=True)
    model_id = Column(UUID(as_uuid=True), ForeignKey("model_library.id", ondelete="SET NULL"), nullable=True)
    workflow_id = Column(UUID(as_uuid=True), ForeignKey("workflows.id", ondelete="SET NULL"), nullable=True)
    description = Column(Text, default="")
    request_schema = Column(JSON, default=dict)
    response_schema = Column(JSON, default=dict)
    total_calls = Column(Integer, default=0)
    success_calls = Column(Integer, default=0)
    failed_calls = Column(Integer, default=0)
    owner_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    is_public = Column(Boolean, default=False)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, onupdate=func.now())
    published_at = Column(DateTime, nullable=True)
    last_error = Column(Text, nullable=True)
