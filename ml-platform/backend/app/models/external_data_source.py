"""External data source connections (补齐路线第一批 B1-08).

只读外部数据库直连：口令 Fernet 加密存储（独立 datasource_master_key，
D8）；SQL 白名单由 sqlglot 语法解析执行（services/sql_whitelist.py），
「白名单 + 只读账号」双防线——白名单拦 DML/DDL，账号越权读归现场治理
（界面与文档明示）。quality_scenes.data_source_id 绑定列随本表建表后
同批加入（建表与外键约束必须同迁移，避免跨迁移悬空引用）。
"""
import uuid

from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID

from app.database import Base


class ExternalDataSource(Base):
    __tablename__ = "external_data_sources"
    __table_args__ = (
        UniqueConstraint(
            "project_id",
            "name",
            name="uq_external_data_sources_project_name",
        ),
        CheckConstraint(
            "db_type IN ('postgresql', 'mysql')",
            name="ck_external_data_sources_db_type",
        ),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id = Column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name = Column(String(128), nullable=False)
    db_type = Column(String(16), nullable=False)
    host = Column(String(256), nullable=False)
    port = Column(Integer, nullable=False)
    database = Column(String(128), nullable=False)
    username = Column(String(128), nullable=False)
    # Fernet 密文（datasource_master_key）；任何接口不回显（响应 mask 布尔位）
    password_encrypted = Column(Text, nullable=False)
    ssl_mode = Column(String(16), nullable=False, default="prefer")
    # connect_args 白名单键（extra）；口令类键禁止入内
    extra = Column(JSON, nullable=True)
    created_by_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now())
