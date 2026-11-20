"""
Knowledge Base / Knowledge Graph ORM models.
"""
import uuid
from sqlalchemy import (
    Column, String, Text, Integer, DateTime, Float, Boolean, ForeignKey,
    Index, JSON, UniqueConstraint, func,
)
from sqlalchemy import text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from app.database import Base


class KnowledgeBase(Base):
    __tablename__ = "knowledge_bases"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(128), nullable=False)
    description = Column(Text, default="")
    owner_id = Column(UUID(as_uuid=True), ForeignKey("users.id"))
    # 按库覆盖的实体/关系类型本体（kg_ontology.py）；空 = 用默认工业本体
    kg_ontology = Column(JSON, nullable=True)
    created_at = Column(DateTime, server_default=func.now())

    owner = relationship("User", back_populates="knowledge_bases")
    documents = relationship("Document", back_populates="knowledge_base", cascade="all, delete-orphan")
    entities = relationship("GraphEntity", back_populates="knowledge_base", cascade="all, delete-orphan")


class Document(Base):
    __tablename__ = "kb_documents"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    kb_id = Column(UUID(as_uuid=True), ForeignKey("knowledge_bases.id", ondelete="CASCADE"), nullable=False, index=True)
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
    doc_id = Column(UUID(as_uuid=True), ForeignKey("kb_documents.id", ondelete="CASCADE"), nullable=False, index=True)
    content = Column(Text, nullable=False)
    chunk_index = Column(Integer, default=0)
    embedding = Column(Text, default="")

    document = relationship("Document", back_populates="chunks")


class GraphEntity(Base):
    __tablename__ = "graph_entities"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    kb_id = Column(UUID(as_uuid=True), ForeignKey("knowledge_bases.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(256), nullable=False, index=True)
    entity_type = Column(String(64), default="concept")
    properties = Column(JSON, default=dict)
    # 知识融合：被合并进哪个存活实体（合并后不再出现在图查询里）；
    # 别名来自 LLM 抽取/人工维护，归并判定时视作等价名
    merged_into = Column(UUID(as_uuid=True), ForeignKey("graph_entities.id", ondelete="CASCADE"), nullable=True, index=True)
    aliases = Column(JSON, nullable=False, default=list, server_default=text("'[]'"))
    created_at = Column(DateTime, server_default=func.now())

    knowledge_base = relationship("KnowledgeBase", back_populates="entities")
    source_relations = relationship("GraphRelation", foreign_keys="GraphRelation.source_id", back_populates="source", cascade="all, delete-orphan")
    target_relations = relationship("GraphRelation", foreign_keys="GraphRelation.target_id", back_populates="target", cascade="all, delete-orphan")

    # 同库同名唯一护栏：仅约束存活实体（merged_into IS NULL），与
    # 20261120_103 迁移中的部分唯一索引逐字对齐，否则 schema 漂移门禁拒绝
    __table_args__ = (
        Index(
            "uq_graph_entities_kb_name", "kb_id", "name", unique=True,
            sqlite_where=text("merged_into IS NULL"),
            postgresql_where=text("merged_into IS NULL"),
        ),
    )


class GraphRelation(Base):
    __tablename__ = "graph_relations"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    kb_id = Column(UUID(as_uuid=True), ForeignKey("knowledge_bases.id", ondelete="CASCADE"), nullable=False, index=True)
    source_id = Column(UUID(as_uuid=True), ForeignKey("graph_entities.id", ondelete="CASCADE"), nullable=False, index=True)
    target_id = Column(UUID(as_uuid=True), ForeignKey("graph_entities.id", ondelete="CASCADE"), nullable=False, index=True)
    relation_type = Column(String(64), default="related_to")
    properties = Column(JSON, default=dict)
    created_at = Column(DateTime, server_default=func.now())

    source = relationship("GraphEntity", foreign_keys=[source_id], back_populates="source_relations")
    target = relationship("GraphEntity", foreign_keys=[target_id], back_populates="target_relations")


class ChatSession(Base):
    __tablename__ = "chat_sessions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    kb_id = Column(UUID(as_uuid=True), ForeignKey("knowledge_bases.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    title = Column(String(256), default="")
    created_at = Column(DateTime, server_default=func.now())

    knowledge_base = relationship("KnowledgeBase")
    messages = relationship("ChatMessage", back_populates="session", cascade="all, delete-orphan")


class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id = Column(UUID(as_uuid=True), ForeignKey("chat_sessions.id", ondelete="CASCADE"), nullable=False, index=True)
    role = Column(String(16), nullable=False)
    content = Column(Text, nullable=False)
    sources = Column(JSON, default=list)
    created_at = Column(DateTime, server_default=func.now())

    session = relationship("ChatSession", back_populates="messages")


class KgExtractionJob(Base):
    """LLM 深度抽取的异步任务（kg_tasks.execute_kg_extract 驱动，前端轮询进度）。

    nullable/server_default 须与 20261120_103 迁移一致，否则 schema 漂移门禁
    （alembic command.check）会拒绝。
    """
    __tablename__ = "kg_extraction_jobs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    kb_id = Column(UUID(as_uuid=True), ForeignKey("knowledge_bases.id", ondelete="CASCADE"), nullable=False, index=True)
    mode = Column(String(16), nullable=False, default="llm", server_default="llm")
    # pending / running / succeeded / failed / cancelled
    status = Column(String(16), nullable=False, default="pending", server_default="pending", index=True)
    cancel_requested = Column(Boolean, nullable=False, default=False, server_default=text("0"))
    # {"doc_ids": [...], "max_chunks": 120}
    params = Column(JSON, nullable=False, default=dict, server_default=text("'{}'"))
    total_units = Column(Integer, nullable=False, default=0, server_default=text("0"))
    done_units = Column(Integer, nullable=False, default=0, server_default=text("0"))
    entities_found = Column(Integer, nullable=False, default=0, server_default=text("0"))
    relations_found = Column(Integer, nullable=False, default=0, server_default=text("0"))
    llm_calls = Column(Integer, nullable=False, default=0, server_default=text("0"))
    llm_errors = Column(Integer, nullable=False, default=0, server_default=text("0"))
    error = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    started_at = Column(DateTime, nullable=True)
    finished_at = Column(DateTime, nullable=True)

    knowledge_base = relationship("KnowledgeBase")


class KgUnitResult(Base):
    """单个 chunk 的抽取结果缓存：幂等键 (kb_id, chunk_id, content_hash) 支撑断点续抽。"""
    __tablename__ = "kg_unit_results"
    __table_args__ = (
        UniqueConstraint("kb_id", "chunk_id", "content_hash", name="uq_kg_unit_result"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    kb_id = Column(UUID(as_uuid=True), ForeignKey("knowledge_bases.id", ondelete="CASCADE"), nullable=False, index=True)
    chunk_id = Column(UUID(as_uuid=True), ForeignKey("kb_chunks.id", ondelete="CASCADE"), nullable=True)
    content_hash = Column(String(64), nullable=False, index=True)
    # ok / empty / failed
    status = Column(String(16), nullable=False, default="ok", server_default="ok")
    result = Column(JSON, nullable=True)
    error = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, server_default=func.now())


class KgMergeSuggestion(Base):
    """知识融合建议队列：自动归并留痕（accepted）与待人工审核（pending）。"""
    __tablename__ = "kg_merge_suggestions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    kb_id = Column(UUID(as_uuid=True), ForeignKey("knowledge_bases.id", ondelete="CASCADE"), nullable=False, index=True)
    # merge_entity / attribute_conflict
    type = Column(String(32), nullable=False)
    # pending / accepted / rejected
    status = Column(String(16), nullable=False, default="pending", server_default="pending", index=True)
    # auto / llm / manual
    method = Column(String(16), nullable=False, default="auto", server_default="auto")
    # merge_entity: a=存活方, b=并入方；attribute_conflict: a=实体
    entity_a_id = Column(UUID(as_uuid=True), ForeignKey("graph_entities.id", ondelete="CASCADE"), nullable=True)
    entity_b_id = Column(UUID(as_uuid=True), ForeignKey("graph_entities.id", ondelete="CASCADE"), nullable=True)
    canonical_name = Column(String(256), nullable=True)
    similarity = Column(Float, nullable=True)
    # merge: {reason}；conflict: {attribute, values: [{value, doc_ids}]}
    payload = Column(JSON, nullable=False, default=dict, server_default=text("'{}'"))
    # accept 执行后的审计快照（重指的关系数/合并的别名等）
    apply_record = Column(JSON, nullable=True)
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    decided_at = Column(DateTime, nullable=True)
    decided_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)

    entity_a = relationship("GraphEntity", foreign_keys=[entity_a_id])
    entity_b = relationship("GraphEntity", foreign_keys=[entity_b_id])
