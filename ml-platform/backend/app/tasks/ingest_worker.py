"""Kafka ingest worker entrypoint (B1-07, D48/D51).

compose 的 kafka-ingest 服务（profile: kafka）的进程入口：
不是 Celery task 的消费者常驻循环——直接跑 services.ingest 的消费主循环，
独立于 worker/beat 进程（消费循环是长驻阻塞的，不占 Celery 池）。

消费逻辑与 ml_platform.kafka_ingest_loop 任务体同源（同一个 while True 循环），
此入口只是给 compose 一个可直接 `python -m` 的模块。
"""
from __future__ import annotations

import logging
import time

from app.config import settings
from app.database import SessionLocal
from app.models.project import Project
from app.services.ingest import ingest_batch, record_heartbeat

logger = logging.getLogger(__name__)


def main() -> int:
    if not settings.kafka_ingest_enabled or not settings.kafka_bootstrap_servers:
        logger.error(
            "kafka ingest worker 需要 KAFKA_INGEST_ENABLED=true 与 KAFKA_BOOTSTRAP_SERVERS"
        )
        return 2

    from kafka import KafkaConsumer

    consumer = KafkaConsumer(
        settings.kafka_ingest_topic,
        bootstrap_servers=settings.kafka_bootstrap_servers,
        group_id=settings.kafka_ingest_group_id,
        enable_auto_commit=True,
        value_deserializer=_deserialize,
    )
    logger.info(
        "kafka ingest worker started (topic=%s, group=%s)",
        settings.kafka_ingest_topic, settings.kafka_ingest_group_id,
    )
    while True:
        raw_batches = consumer.poll(
            timeout_ms=int(settings.kafka_ingest_poll_seconds * 1000),
            max_records=500,
        )
        for topic_partition, messages in (raw_batches or {}).items():
            records = [message.value for message in messages]
            offsets = [message.offset for message in messages]
            if not records:
                continue
            with SessionLocal() as db:
                project_row = db.query(Project.id).order_by(Project.id.asc()).first()
                if project_row is None:
                    logger.warning("kafka ingest skipped: no project to attribute events to")
                    time.sleep(5.0)
                    continue
                summary = ingest_batch(
                    db, project_id=project_row[0], source="kafka",
                    topic=settings.kafka_ingest_topic,
                    partition=topic_partition.partition,
                    offsets=offsets, events=records,
                )
                db.commit()
                logger.info(
                    "ingest batch: accepted=%s duplicate=%s rejected=%s",
                    summary.get("accepted"), summary.get("duplicate"), summary.get("rejected"),
                )
        # 心跳由 ingest_batch 落（每批一次）；空轮也补一次让页脚知道进程活着
        with SessionLocal() as db:
            record_heartbeat(db, state="ok")
        time.sleep(0.1)


def _deserialize(raw: bytes) -> dict:
    import json

    try:
        return json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return {"business_event_id": "", "station": "", "occurred_at": "", "raw_unparseable": True}


if __name__ == "__main__":
    raise SystemExit(main())
