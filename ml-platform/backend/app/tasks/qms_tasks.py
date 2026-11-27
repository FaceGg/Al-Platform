"""QMS 周期任务（补齐路线第三批 B3-08，技术方案 D7）。

- qms_report_scheduled：质量报告定时生成（beat `qms-report-scheduler`，600s 巡检
  due）——对上一已完结周期补齐日报/周报/月报（generated_by=scheduler），唯一键
  幂等，只为有质量活动的项目生成。
"""
from __future__ import annotations

import logging

from app.database import SessionLocal
from app.tasks.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(name="ml_platform.qms_report_scheduled")
def qms_report_scheduled_task() -> dict:
    from app.services.qms_tools import scheduled_due_reports

    with SessionLocal() as db:
        try:
            result = scheduled_due_reports(db)
            db.commit()
            return result
        except Exception:
            db.rollback()
            logger.exception("qms report scheduling failed")
            raise
