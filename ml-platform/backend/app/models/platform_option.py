"""Platform options KV store.

管理员级全局配置（首个消费者：AI 对话白名单工具启停）。key 唯一、
value JSON；读写均经服务层 helper，避免各处手写查询。
"""

from sqlalchemy import JSON, Column, DateTime, String, func

from app.database import Base


class PlatformOption(Base):
    __tablename__ = "platform_options"

    key = Column(String(64), primary_key=True)
    value = Column(JSON, nullable=False, default=dict)
    updated_at = Column(DateTime, nullable=False, server_default=func.now(), onupdate=func.now())


def get_option(db, key: str, default=None):
    row = db.get(PlatformOption, key)
    return row.value if row is not None else default


def set_option(db, key: str, value) -> None:
    row = db.get(PlatformOption, key)
    if row is None:
        row = PlatformOption(key=key, value=value)
        db.add(row)
    else:
        row.value = value
    db.commit()
