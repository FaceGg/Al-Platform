import uuid

from sqlalchemy import Column, String, Text, BigInteger, DateTime, ForeignKey, func
from sqlalchemy import JSON
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.database import Base


class Artifact(Base):
    __tablename__ = "artifacts"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    name = Column(String(256), nullable=False)
    type = Column(String(32), nullable=False)
    storage_path = Column(String(512), nullable=False)
    file_size = Column(BigInteger)
    format = Column(String(32))
    metadata_ = Column("metadata", JSON, default=dict)
    created_at = Column(DateTime, server_default=func.now())

    project = relationship("Project", back_populates="artifacts")
