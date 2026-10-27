"""Infrastructure readiness checks with stable, redacted status codes."""

import time
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeoutError

import httpx
from sqlalchemy import text

from app.database_schema import require_current_schema

_DEFAULT_PROBE_TIMEOUT_SECONDS = 10.0

# 探测超时的回退值：状态类探针沿用既有稳定 code，布尔/可选值探针回到失败位。
_PROBE_TIMEOUT_FALLBACKS = {
    "database": {"ready": False, "code": "DATABASE_UNAVAILABLE"},
    "redis": {"ready": False, "code": "REDIS_UNAVAILABLE"},
    "celery": {"ready": False, "code": "CELERY_UNAVAILABLE"},
    "storage": {"ready": False, "code": "MINIO_UNAVAILABLE"},
    "mlflow": {"ready": False, "code": "MLFLOW_UNAVAILABLE"},
    "tensorboard": {"ready": False, "code": "TENSORBOARD_UNAVAILABLE"},
    "inference_runtime": {"ready": False, "code": "INFERENCE_RUNTIME_UNAVAILABLE"},
    "notification_worker_registered": False,
    "migration_head": None,
}


class ReadinessService:
    def __init__(
        self,
        engine,
        settings,
        redis_client=None,
        celery_app=None,
        storage=None,
        http_client=None,
        probe_timeout_seconds=None,
    ):
        self.engine = engine
        self.settings = settings
        self.redis_client = redis_client
        self.celery_app = celery_app
        self.storage = storage
        self.http_client = http_client or httpx
        self.probe_timeout_seconds = probe_timeout_seconds

    def check_all(self) -> dict:
        probes = {
            "database": self._database,
            "redis": self._redis,
            "celery": self._celery,
            "storage": self._storage,
            "mlflow": self._mlflow,
            "tensorboard": self._tensorboard,
            "inference_runtime": self._inference_runtime,
            "notification_worker_registered": self._notification_worker_registered,
            "migration_head": self._migration_head,
        }
        results = self._run_probes_concurrently(probes)
        checks = {
            name: results[name]
            for name in (
                "database",
                "redis",
                "celery",
                "storage",
                "mlflow",
                "tensorboard",
                "inference_runtime",
            )
        }
        notification_crypto_configured = self._notification_crypto_configured()
        notification_worker_registered = results["notification_worker_registered"]
        notification_ready = (
            getattr(self.settings, "app_mode", "local") != "production"
            or (notification_crypto_configured and notification_worker_registered)
        )
        return {
            "ready": all(item["ready"] for item in checks.values())
            and notification_ready,
            **checks,
            "notification_crypto_configured": notification_crypto_configured,
            "notification_worker_registered": notification_worker_registered,
            "migration_head": results["migration_head"],
        }

    def _run_probes_concurrently(self, probes: dict) -> dict:
        """Run independent probes in parallel under one shared deadline.

        Serial probing stacks each probe's timeout (Redis/Celery 广播 +
        3 个 HTTP 探测曾合计约 3s)；并行后总时延 ≈ 最慢单项。超时的
        探针按 _PROBE_TIMEOUT_FALLBACKS 回退，线程留给其自身 I/O 超时
        收尾，不阻塞响应。
        """
        if self.probe_timeout_seconds is not None:
            timeout = self.probe_timeout_seconds
        else:
            timeout = float(
                getattr(
                    self.settings,
                    "readiness_probe_timeout_seconds",
                    _DEFAULT_PROBE_TIMEOUT_SECONDS,
                )
            )
        deadline = time.monotonic() + timeout
        pool = ThreadPoolExecutor(
            max_workers=min(len(probes), 8),
            thread_name_prefix="readiness-probe",
        )
        try:
            futures = {name: pool.submit(fn) for name, fn in probes.items()}
            results = {}
            for name, future in futures.items():
                remaining = max(0.0, deadline - time.monotonic())
                try:
                    results[name] = future.result(timeout=remaining)
                except FutureTimeoutError:
                    fallback = _PROBE_TIMEOUT_FALLBACKS.get(
                        name, {"ready": False, "code": "PROBE_TIMEOUT"}
                    )
                    results[name] = dict(fallback) if isinstance(fallback, dict) else fallback
            return results
        finally:
            pool.shutdown(wait=False)

    def _migration_head(self) -> str | None:
        try:
            with self.engine.connect() as connection:
                row = connection.execute(
                    text("SELECT version_num FROM alembic_version")
                ).scalar()
            return str(row) if row else None
        except Exception:
            return None

    def _notification_crypto_configured(self) -> bool:
        master_key = getattr(self.settings, "resolved_notification_master_key", None)
        if master_key is None:
            return False
        try:
            return bool(master_key.get_secret_value().strip())
        except AttributeError:
            return False

    def _notification_worker_registered(self) -> bool:
        required_tasks = {
            "ml_platform.deliver_notifications",
            "ml_platform.enqueue_due_notifications",
        }
        tasks = getattr(self.celery_app, "tasks", {}) if self.celery_app else {}
        if not required_tasks.issubset(tasks):
            return False
        if getattr(self.settings, "task_backend", "local") != "celery":
            return True
        try:
            inspector = self.celery_app.control.inspect()
            active_workers = inspector.ping()
            registered = inspector.registered()
        except Exception:
            return False
        if not isinstance(active_workers, dict) or not active_workers:
            return False
        if not isinstance(registered, dict):
            return False
        for worker_name in active_workers:
            worker_tasks = registered.get(worker_name)
            if not isinstance(worker_tasks, (list, tuple, set)):
                return False
            if not required_tasks.issubset(worker_tasks):
                return False
        return True

    def _database(self):
        try:
            with self.engine.connect() as connection:
                connection.execute(text("SELECT 1"))
            if getattr(self.settings, "app_mode", "local") == "production":
                require_current_schema(self.engine)
            return {"ready": True, "code": "OK"}
        except Exception:
            return {"ready": False, "code": "DATABASE_UNAVAILABLE"}

    def _redis(self):
        if self.settings.task_backend != "celery" and self.redis_client is None:
            return {"ready": True, "code": "LOCAL_MODE"}
        try:
            if self.redis_client is None or not self.redis_client.ping():
                raise RuntimeError
            return {"ready": True, "code": "OK"}
        except Exception:
            return {"ready": False, "code": "REDIS_UNAVAILABLE"}

    def _celery(self):
        if self.settings.task_backend != "celery":
            return {"ready": True, "code": "LOCAL_MODE"}
        try:
            if (
                self.celery_app is None
                or "ml_platform.execute_training" not in self.celery_app.tasks
            ):
                raise RuntimeError
            workers = self.celery_app.control.inspect().ping() if self.celery_app else None
            if not workers:
                raise RuntimeError
            return {"ready": True, "code": "OK"}
        except Exception:
            return {"ready": False, "code": "CELERY_UNAVAILABLE"}

    def _storage(self):
        if self.settings.artifact_storage_backend == "local":
            return {"ready": True, "code": "LOCAL_MODE"}
        try:
            if self.storage is None or not self.storage.client.bucket_exists(self.storage.bucket):
                raise RuntimeError
            return {"ready": True, "code": "OK"}
        except Exception:
            return {"ready": False, "code": "MINIO_UNAVAILABLE"}

    def _mlflow(self):
        return self._http_service(
            getattr(self.settings, "mlflow_tracking_uri", None),
            "/health",
            "MLFLOW_UNAVAILABLE",
        )

    def _tensorboard(self):
        return self._http_service(
            getattr(self.settings, "tensorboard_gateway_url", None),
            "/openapi.json",
            "TENSORBOARD_UNAVAILABLE",
        )

    def _inference_runtime(self):
        return self._http_service(
            getattr(self.settings, "inference_runtime_url", None),
            "/health",
            "INFERENCE_RUNTIME_UNAVAILABLE",
        )

    def _http_service(self, base_url, path, unavailable_code):
        if not base_url:
            return {"ready": True, "code": "LOCAL_MODE"}
        try:
            response = self.http_client.get(
                f"{str(base_url).rstrip('/')}{path}",
                timeout=3.0,
            )
            if not 200 <= int(response.status_code) < 400:
                raise RuntimeError
            return {"ready": True, "code": "OK"}
        except Exception:
            return {"ready": False, "code": unavailable_code}
