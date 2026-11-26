"""Approval queue sweep (补齐路线第二批 S1, B2-10/D6): 过期回收 + 过期前提醒."""

import logging

from app.tasks.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(name="ml_platform.sweep_approval_expiries")
def sweep_approval_expiries_task() -> dict:
    """审批队列巡检（600s）：提醒档（≤12h 一次）与过期档（status=expired），
    域事件入 outbox 由既有订阅路由投递（同 quality-alert-sla-watch 形制）。"""
    from app.database import SessionLocal
    from app.services.approvals import sweep_expiries

    with SessionLocal() as db:
        try:
            result = sweep_expiries(db)
            db.commit()
            return result
        except Exception:
            db.rollback()
            logger.exception("approval expiry sweep failed")
            raise
