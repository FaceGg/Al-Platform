"""Celery application configuration."""

GENERICIZATION_BRIDGE_ONLY = True

from celery import Celery
from celery.schedules import crontab

from app.config import settings


celery_app = Celery(
    "ml_platform",
    include=[
        "app.tasks.workflow_tasks",
        "app.tasks.training_tasks",
        "app.tasks.annotation_preview_tasks",
        "app.tasks.annotation_execution_tasks",
        "app.tasks.inference_tasks",
        "app.tasks.notification_tasks",
        "app.tasks.spot_weld_quality_tasks",
        "app.tasks.model_export_tasks",
        "app.tasks.dataset_import_tasks",
        "app.tasks.annotation_return_tasks",
        "app.tasks.kubernetes_tasks",
        "app.tasks.kg_tasks",
        "app.tasks.quality_tasks",
        "app.tasks.qms_tasks",
        "app.tasks.ingest_tasks",
        "app.tasks.approval_tasks",
        "app.tasks.recovery",
    ],
    broker=(settings.celery_broker_url.get_secret_value() if settings.celery_broker_url else None),
    backend=(settings.celery_result_backend.get_secret_value() if settings.celery_result_backend else None),
)
celery_app.conf.update(
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    enable_utc=True,
    broker_connection_retry_on_startup=True,
    worker_prefetch_multiplier=1,
    task_soft_time_limit=settings.task_soft_timeout_seconds,
    task_time_limit=settings.task_hard_timeout_seconds,
    beat_schedule={
        "pipeline-scheduler-tick": {
            "task": "ml_platform.scheduler_tick",
            "schedule": 60.0,
        },
        "pipeline-scheduler-recovery": {
            "task": "ml_platform.recover_pipeline_schedules",
            "schedule": 60.0,
        },
        # A-10：僵尸 running run 对账（历史上 reconcile_stale_runs 无调用者）
        "workflow-run-recovery": {
            "task": "ml_platform.recover_stale_workflow_runs",
            "schedule": 60.0,
        },
        # 升级批次：AgentRun 陈旧清扫周期化（此前仅启动期执行一次）
        "agent-run-recovery": {
            "task": "ml_platform.recover_stale_agent_runs",
            "schedule": 60.0,
        },
        "training-job-recovery": {
            "task": "ml_platform.recover_training_jobs",
            "schedule": 60.0,
        },
        "durable-operation-recovery": {
            "task": "ml_platform.recover_operations",
            "schedule": 60.0,
        },
        "inference-deployment-reconciliation": {
            "task": "ml_platform.reconcile_inference_deployments",
            "schedule": 60.0,
        },
        "inference-rollout-reconciliation": {
            "task": "ml_platform.reconcile_inference_rollouts",
            "schedule": 60.0,
        },
        "inference-telemetry-retention": {
            "task": "ml_platform.prune_inference_telemetry",
            "schedule": crontab(hour=0, minute=0),
        },
        "inference-result-retention": {
            # 推理结果明细保留期清理（B1-16）：每日清理，聚合桶永久保留
            "task": "ml_platform.prune_inference_results",
            "schedule": crontab(hour=0, minute=5),
        },
        "kubernetes-job-reconcile": {
            "task": "ml_platform.kubernetes_jobs_reconcile",
            "schedule": 60.0,
        },
        "kubernetes-job-gc": {
            "task": "ml_platform.kubernetes_jobs_gc",
            "schedule": 300.0,
        },
        "notebook-idle-sweep": {
            "task": "ml_platform.notebook_idle_sweep",
            "schedule": 300.0,
        },
        "governance-usage-collect": {
            "task": "ml_platform.governance_usage_collect",
            "schedule": 60.0,
        },
        "governance-reservation-sweep": {
            "task": "ml_platform.governance_reservation_sweep",
            "schedule": 300.0,
        },
        "notification-outbox-dispatch": {
            "task": "ml_platform.enqueue_due_notifications",
            "schedule": 30.0,
        },
        # F2a 预警处置主干（D16/D21）：设备心跳巡检与 SLA 两档通知
        "quality-device-watch": {
            "task": "ml_platform.watch_quality_devices",
            "schedule": 300.0,
        },
        "quality-alert-sla-watch": {
            "task": "ml_platform.watch_alert_sla",
            "schedule": 600.0,
        },
        # 第三批 B3-08（D7）：质量报告定时生成（600s 巡检上一已完结周期，唯一键幂等）
        "qms-report-scheduler": {
            "task": "ml_platform.qms_report_scheduled",
            "schedule": 600.0,
        },
        # F4 漂移定时批检（D40）：周期可配，默认 300 秒
        "drift-scan": {
            "task": "ml_platform.scan_model_drift",
            "schedule": float(settings.drift_scan_interval_seconds),
        },
        # S1 审批队列巡检（B2-10/D6）：过期回收 + 过期前 12h 提醒（600s）
        "approval-expiry-sweep": {
            "task": "ml_platform.sweep_approval_expiries",
            "schedule": 600.0,
        },
    },
)

# Register tasks for CLI/import smoke checks as well as worker include discovery.
from app.tasks import training_tasks  # noqa: E402,F401
from app.tasks import annotation_preview_tasks  # noqa: E402,F401
from app.tasks import annotation_execution_tasks  # noqa: E402,F401
from app.tasks import scheduler_tasks  # noqa: E402,F401
from app.tasks import inference_tasks  # noqa: E402,F401
from app.tasks import notification_tasks  # noqa: E402,F401
from app.tasks import spot_weld_quality_tasks  # noqa: E402,F401
from app.tasks import model_export_tasks  # noqa: E402,F401
from app.tasks import dataset_import_tasks  # noqa: E402,F401
from app.tasks import annotation_return_tasks  # noqa: E402,F401
from app.tasks import kubernetes_tasks  # noqa: E402,F401
from app.tasks import quality_tasks  # noqa: E402,F401
from app.tasks import qms_tasks  # noqa: E402,F401
from app.tasks import ingest_tasks  # noqa: E402,F401
from app.tasks import approval_tasks  # noqa: E402,F401
from app.tasks import recovery  # noqa: E402,F401

# prefork 子进程初始化时重建网关出网 client：httpx.Client 不是 fork 安全的，
# MainProcess 建立的连接池被 worker 子进程继承后父子共用底层 socket，请求会
# 静默返回空响应（2026-11-23 KG 深度抽取全量 empty_completion 实证）
from celery.signals import worker_process_init  # noqa: E402


@worker_process_init.connect
def _reset_llm_http_client(**kwargs):
    try:
        from app.services.llm_gateway import reset_http_client

        reset_http_client()
    except Exception:  # noqa: BLE001
        pass
