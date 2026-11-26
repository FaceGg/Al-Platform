"""Quality alert periodic tasks (补齐路线第一批 F2a, D16/D21).

- watch_quality_devices：设备心跳巡检（300s）——过期产生 device_anomaly
  预警（同因合并防风暴），恢复写 device_recovered 轨迹。
- watch_alert_sla：预警 SLA 巡检（600s）——临期/超时两档域事件入 outbox，
  由既有通知管线投递（订阅路由）。
"""
from __future__ import annotations

import logging

from app.database import SessionLocal
from app.tasks.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(name="ml_platform.watch_quality_devices")
def watch_quality_devices_task() -> dict:
    from app.services.quality_alerts import watch_devices

    with SessionLocal() as db:
        try:
            result = watch_devices(db)
            db.commit()
            return result
        except Exception:
            db.rollback()
            logger.exception("quality device watch failed")
            raise


@celery_app.task(name="ml_platform.watch_alert_sla")
def watch_alert_sla_task() -> dict:
    from app.services.quality_alerts import watch_sla

    with SessionLocal() as db:
        try:
            result = watch_sla(db)
            db.commit()
            return result
        except Exception:
            db.rollback()
            logger.exception("quality alert SLA watch failed")
            raise
