# -*- coding: utf-8 -*-
"""Knowledge-graph LLM extraction task dispatching.

Celery 任务为主通道；broker 不可用时降级为进程内线程（本地栈/单机部署也能
跑深度抽取）。任务本体在 services 层（knowledge_graph_llm_extraction.
run_kg_extraction_job），这里是分发与恢复外壳。
"""
import threading

from app.tasks.celery_app import celery_app

_KG_TASK_NAME = "ml_platform.execute_kg_extract"


@celery_app.task(name=_KG_TASK_NAME, ignore_result=True)
def execute_kg_extract(job_id: str) -> None:
    from app.services.knowledge_graph_llm_extraction import run_kg_extraction_job

    run_kg_extraction_job(str(job_id))


def dispatch_kg_extraction(job_id: str) -> str:
    """投递任务；broker 不可用时进程内线程兜底（返回实际通道名）。"""
    try:
        execute_kg_extract.delay(str(job_id))
        return "celery"
    except Exception:  # noqa: BLE001 - broker 掉线/未起 worker 时本地兜底
        thread = threading.Thread(
            target=_run_local,
            args=(str(job_id),),
            daemon=True,
            name=f"kg-extract-{job_id}",
        )
        thread.start()
        return "local-thread"


def _run_local(job_id: str) -> None:
    from app.services.knowledge_graph_llm_extraction import run_kg_extraction_job

    try:
        run_kg_extraction_job(str(job_id))
    except Exception:  # noqa: BLE001 - 错误已在 job 行留档
        pass
