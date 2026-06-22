"""
Knowledge Base / Knowledge Graph ORM models.
"""
import uuid
from sqlalchemy import Column, String, Text, Integer, DateTime, ForeignKey, JSON, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from app.database import Base


class KnowledgeBase(Base):
    __tablename__ = "knowledge_bases"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(128), nullable=False)
    description = Column(Text, default="")
    owner_id = Column(UUID(as_uuid=True), ForeignKey("users.id"))
    created_at = Column(DateTime, server_default=func.now())

    owner = relationship("User", back_populates="knowledge_bases")
    documents = relationship("Document", back_populates="knowledge_base", cascade="all, delete-orphan")
    entities = relationship("GraphEntity", back_populates="knowledge_base", cascade="all, delete-orphan")


class Document(Base):
    __tablename__ = "kb_documents"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    kb_id = Column(UUID(as_uuid=True), ForeignKey("knowledge_bases.id", ondelete="CASCADE"), nullable=False)
    filename = Column(String(256), nullable=False)
    content = Column(Text, default="")
    doc_type = Column(String(32), default="text")
    file_path = Column(String(512))
    chunk_count = Column(Integer, default=0)
    created_at = Column(DateTime, server_default=func.now())

    knowledge_base = relationship("KnowledgeBase", back_populates="documents")
    chunks = relationship("Chunk", back_populates="document", cascade="all, delete-orphan")


class Chunk(Base):
    __tablename__ = "kb_chunks"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    doc_id = Column(UUID(as_uuid=True), ForeignKey("kb_documents.id", ondelete="CASCADE"), nullable=False)
    content = Column(Text, nullable=False)
    chunk_index = Column(Integer, default=0)
    embedding = Column(Text, default="")

    document = relationship("Document", back_populates="chunks")


class GraphEntity(Base):
    __tablename__ = "graph_entities"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    kb_id = Column(UUID(as_uuid=True), ForeignKey("knowledge_bases.id", ondelete="CASCADE"), nullable=False)
    name = Column(String(256), nullable=False, index=True)
    entity_type = Column(String(64), default="concept")
    properties = Column(JSON, default=dict)
    created_at = Column(DateTime, server_default=func.now())

    knowledge_base = relationship("KnowledgeBase", back_populates="entities")
    source_relations = relationship("GraphRelation", foreign_keys="GraphRelation.source_id", back_populates="source", cascade="all, delete-orphan")
    target_relations = relationship("GraphRelation", foreign_keys="GraphRelation.target_id", back_populates="target", cascade="all, delete-orphan")


class GraphRelation(Base):
    __tablename__ = "graph_relations"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    kb_id = Column(UUID(as_uuid=True), ForeignKey("knowledge_bases.id", ondelete="CASCADE"), nullable=False)
    source_id = Column(UUID(as_uuid=True), ForeignKey("graph_entities.id", ondelete="CASCADE"), nullable=False)
    target_id = Column(UUID(as_uuid=True), ForeignKey("graph_entities.id", ondelete="CASCADE"), nullable=False)
    relation_type = Column(String(64), default="related_to")
    properties = Column(JSON, default=dict)
    created_at = Column(DateTime, server_default=func.now())

    source = relationship("GraphEntity", foreign_keys=[source_id], back_populates="source_relations")
    target = relationship("GraphEntity", foreign_keys=[target_id], back_populates="target_relations")


class ChatSession(Base):
    __tablename__ = "chat_sessions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    kb_id = Column(UUID(as_uuid=True), ForeignKey("knowledge_bases.id", ondelete="CASCADE"), nullable=False)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    title = Column(String(256), default="")
    created_at = Column(DateTime, server_default=func.now())

    knowledge_base = relationship("KnowledgeBase")
    messages = relationship("ChatMessage", back_populates="session", cascade="all, delete-orphan")


class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id = Column(UUID(as_uuid=True), ForeignKey("chat_sessions.id", ondelete="CASCADE"), nullable=False)
    role = Column(String(16), nullable=False)
    content = Column(Text, nullable=False)
    sources = Column(JSON, default=list)
    created_at = Column(DateTime, server_default=func.now())

    session = relationship("ChatSession", back_populates="messages")
