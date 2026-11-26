"""Ingest events (补齐路线第一批 F5b, B1-07).

实时接入通道的事件层（技术方案 §9A.2，D50–D51）：接入契约（E18）的落库层。
- business_event_id 在来源内唯一：同 ID 同内容幂等跳过；同 ID 不同内容落 rejected
  行可追查（不覆盖、不静默）；
- payload 即原始记录（含可选波形编码串，D53）；重放位置由 (topic, partition, offset) 表达；
- 心跳不在此表（写 PlatformOption，见 services/ingest.py）。

Kafka 不是默认栈的一部分（compose profile，D48）：本表不依赖 Kafka——
手动发布端点与测试可在无 Kafka 环境走同一契约校验路径。
"""
import uuid

from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID

from app.database import Base


# 接入契约版本（D50）：pydantic 校验层同步维护
INGEST_PAYLOAD_VERSIONS = ("v1",)

INGEST_EVENT_STATUSES = ("accepted", "rejected", "duplicate")


class IngestEvent(Base):
    __tablename__ = "ingest_events"
    __table_args__ = (
        # 幂等去重（E18/D50）：同一来源的同一业务事件只接受一次
        UniqueConstraint(
            "source",
            "business_event_id",
            name="uq_ingest_events_source_business_id",
        ),
        CheckConstraint(
            "status IN ('accepted', 'rejected', 'duplicate')",
            name="ck_ingest_events_status",
        ),
        # 重放位置查询：消费重启从上次 offset 续读
        Index(
            "ix_ingest_events_topic_partition_offset",
            "topic",
            "partition",
            "offset",
        ),
        Index(
            "ix_ingest_events_source_received",
            "source",
            "received_at",
        ),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id = Column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    source = Column(String(64), nullable=False)
    topic = Column(String(128), nullable=True)
    partition = Column(Integer, nullable=True)
    offset = Column(Integer, nullable=True)
    business_event_id = Column(String(128), nullable=False)
    station = Column(String(128), nullable=True)
    occurred_at = Column(DateTime, nullable=True)
    # 契约声明的事件时间与实际接收时间之差（乱序/延迟标签，E18）
    latency_seconds = Column(Integer, nullable=True)
    payload_version = Column(String(16), nullable=False)
    payload = Column(JSON, nullable=False, default=dict)
    payload_hash = Column(String(64), nullable=False)
    status = Column(String(16), nullable=False)
    reject_reason = Column(String(256), nullable=True)
    # 消费批次（一次 poll 的一批事件共用一个批次号）
    ingest_batch_id = Column(UUID(as_uuid=True), nullable=True)
    received_at = Column(DateTime, nullable=False, server_default=func.now())
    note = Column(Text, nullable=True)
