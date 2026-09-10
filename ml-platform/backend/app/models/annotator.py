"""Independent portal identity and controlled platform mappings."""

import uuid
from sqlalchemy import Column, DateTime, ForeignKey, Index, Integer, JSON, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from app.database import Base


class AnnotatorAccount(Base):
    __tablename__ = "annotator_accounts"
    __table_args__ = (UniqueConstraint("username", name="uq_annotator_accounts_username"), Index("ix_annotator_accounts_subject", "subject_id"))
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    subject_id = Column(UUID(as_uuid=True), nullable=False, unique=True, default=uuid.uuid4)
    username = Column(String(64), nullable=False)
    email = Column(String(320), nullable=True)
    password_hash = Column(String(512), nullable=False)
    status = Column(String(16), nullable=False, default="pending")
    session_version = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    updated_at = Column(DateTime, nullable=False, server_default=func.now(), onupdate=func.now())


class AnnotatorSession(Base):
    __tablename__ = "annotator_sessions"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    account_id = Column(UUID(as_uuid=True), ForeignKey("annotator_accounts.id", ondelete="CASCADE"), nullable=False)
    token_hash = Column(String(128), nullable=False, unique=True)
    session_version = Column(Integer, nullable=False)
    expires_at = Column(DateTime, nullable=False)
    revoked_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    last_seen_at = Column(DateTime, nullable=True)
    __table_args__ = (Index("ix_annotator_sessions_account", "account_id", "revoked_at"),)


class AnnotatorSubjectMapping(Base):
    __tablename__ = "annotator_subject_mappings"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    subject_id = Column(UUID(as_uuid=True), ForeignKey("annotator_accounts.subject_id", ondelete="CASCADE"), nullable=False, unique=True)
    platform_principal_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, nullable=False, server_default=func.now())


class ProjectAnnotatorGrant(Base):
    __tablename__ = "project_annotator_grants"
    __table_args__ = (UniqueConstraint("project_id", "subject_id", name="uq_project_annotator_grants_project_subject"), Index("ix_project_annotator_grants_subject", "subject_id", "status"))
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    subject_id = Column(UUID(as_uuid=True), ForeignKey("annotator_accounts.subject_id", ondelete="CASCADE"), nullable=False)
    status = Column(String(16), nullable=False, default="active")
    granted_by = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    revoked_at = Column(DateTime, nullable=True)
