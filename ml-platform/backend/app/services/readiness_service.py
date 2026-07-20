"""Infrastructure readiness checks with stable, redacted status codes."""

import httpx
from sqlalchemy import text

from app.database_schema import require_current_schema


class ReadinessService:
    def __init__(
        self,
        engine,
        settings,
        redis_client=None,
        celery_app=None,
        storage=None,
        http_client=None,
    ):
        self.engine = engine
        self.settings = settings
        self.redis_client = redis_client
        self.celery_app = celery_app
        self.storage = storage
        self.http_client = http_client or httpx

    def check_all(self) -> dict:
        checks = {
            "database": self._database(),
            "redis": self._redis(),
            "celery": self._celery(),
            "storage": self._storage(),
            "mlflow": self._mlflow(),
            "tensorboard": self._tensorboard(),
            "inference_runtime": self._inference_runtime(),
        }
        return {"ready": all(item["ready"] for item in checks.values()), **checks}

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
