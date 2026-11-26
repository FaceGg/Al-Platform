"""Kafka ingest task (补齐路线第一批 F5b, B1-07, D51).

`ml_platform.kafka_ingest_loop`：长驻消费循环（Celery task）——从配置的 topic 拉取
批次，走 services/ingest.ingest_batch 的契约校验与幂等落库；每轮写心跳。

默认完全不启动：`KAFKA_INGEST_ENABLED=false`（诚实设计⑤——无真实流量不宣称
实时链路生效，页脚如实显示「未启用」）。compose 的 kafka / kafka-ingest 服务
（profile: kafka）开启该开关，默认 16 服务栈不变。

消费器用 kafka-python-ng（纯 Python，D49）。
"""
from __future__ import annotations

import json
import logging
import time

from app.tasks.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(name="ml_platform.kafka_ingest_loop")
def kafka_ingest_loop_task() -> dict:
    from app.config import settings as app_settings

    if not app_settings.kafka_ingest_enabled or not app_settings.kafka_bootstrap_servers:
        # 未配置即不启动：页脚如实显示「未启用」（诚实设计⑤）
        return {"started": False, "reason": "KAFKA_INGEST_ENABLED 未开启或未配置 broker"}

    from kafka import KafkaConsumer

    from app.database import SessionLocal
    from app.models.project import Project
    from app.services.ingest import ingest_batch

    consumer = KafkaConsumer(
        app_settings.kafka_ingest_topic,
        bootstrap_servers=app_settings.kafka_bootstrap_servers,
        group_id=app_settings.kafka_ingest_group_id,
        enable_auto_commit=True,
        value_deserializer=_deserialize,
    )
    logger.info(
        "kafka ingest loop started (topic=%s, group=%s)",
        app_settings.kafka_ingest_topic, app_settings.kafka_ingest_group_id,
    )
    totals = {"accepted": 0, "duplicate": 0, "rejected": 0, "batches": 0, "started": True}
    while True:
        raw_batches = consumer.poll(
            timeout_ms=int(app_settings.kafka_ingest_poll_seconds * 1000),
            max_records=500,
        )
        for _topic_partition, messages in (raw_batches or {}).items():
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
                    db, project_id=project_row[0],
                    source="kafka",
                    topic=app_settings.kafka_ingest_topic,
                    partition=_topic_partition.partition,
                    offsets=offsets,
                    events=records,
                )
                db.commit()
                totals["batches"] += 1
                for key in ("accepted", "duplicate", "rejected"):
                    totals[key] += summary.get(key, 0)
        time.sleep(0.1)


def _deserialize(raw: bytes) -> dict:
    """无法解析的载荷交给契约校验落 rejected（不静默丢弃）。"""
    try:
        return json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return {"business_event_id": "", "station": "", "occurred_at": "", "raw_unparseable": True}
