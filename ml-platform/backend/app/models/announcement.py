"""Platform announcement (首页门户「平台公告」板一块的数据源).

管理员在系统管理中维护，登录用户在门户读取；creator 只存用户名以便公告
在账号删除后仍然保留归属痕迹之外的展示连续性。
"""

import uuid

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Index,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import UUID

from app.database import Base


class Announcement(Base):
    __tablename__ = "announcements"
    __table_args__ = (
        Index("ix_announcements_created", "created_at"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    title = Column(String(200), nullable=False)
    content = Column(Text, nullable=False, default="")
    pinned = Column(Boolean, nullable=False, default=False)
    created_by = Column(String(128), nullable=True)
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    updated_at = Column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now()
    )
