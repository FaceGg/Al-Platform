import json
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.api import readiness as readiness_api
from app.services.readiness_service import ReadinessService


class TestReadiness(unittest.TestCase):
    def test_experiment_services_are_included_in_readiness(self):
        http_client = MagicMock()
        http_client.get.return_value.status_code = 200
        service = ReadinessService(
            engine=MagicMock(),
            settings=SimpleNamespace(
                task_backend="local",
                artifact_storage_backend="local",
                mlflow_tracking_uri="http://mlflow:5000",
                tensorboard_gateway_url="http://tensorboard-gateway:6006",
            ),
            http_client=http_client,
        )
        service._database = lambda: {"ready": True, "code": "OK"}

        result = service.check_all()

        self.assertTrue(result["mlflow"]["ready"])
        self.assertTrue(result["tensorboard"]["ready"])
        http_client.get.assert_any_call("http://mlflow:5000/health", timeout=3.0)
        http_client.get.assert_any_call(
            "http://tensorboard-gateway:6006/openapi.json",
            timeout=3.0,
        )

    def test_experiment_service_failures_use_stable_redacted_codes(self):
        http_client = MagicMock()
        http_client.get.side_effect = OSError("connection includes secret-value")
        service = ReadinessService(
            engine=MagicMock(),
            settings=SimpleNamespace(
                task_backend="local",
                artifact_storage_backend="local",
                mlflow_tracking_uri="http://user:password@mlflow:5000",
                tensorboard_gateway_url="http://tensorboard-gateway:6006",
            ),
            http_client=http_client,
        )
        service._database = lambda: {"ready": True, "code": "OK"}

        result = service.check_all()

        self.assertEqual(result["mlflow"], {"ready": False, "code": "MLFLOW_UNAVAILABLE"})
        self.assertEqual(
            result["tensorboard"],
            {"ready": False, "code": "TENSORBOARD_UNAVAILABLE"},
        )
        self.assertNotIn("password", json.dumps(result).lower())

    def test_database_readiness_requires_current_alembic_revision(self):
        connection = MagicMock()
        engine = MagicMock()
        engine.connect.return_value.__enter__.return_value = connection
        service = ReadinessService(
            engine=engine,
            settings=SimpleNamespace(
                app_mode="production",
                task_backend="local",
                artifact_storage_backend="local",
            ),
        )
        with patch(
            "app.services.readiness_service.require_current_schema",
        ) as require_current_schema:
            result = service._database()

        self.assertEqual(result, {"ready": True, "code": "OK"})
        require_current_schema.assert_called_once_with(engine)

    def test_local_readiness_is_ready_without_external_services(self):
        service = ReadinessService(
            engine=SimpleNamespace(connect=lambda: None),
            settings=SimpleNamespace(task_backend="local", artifact_storage_backend="local"),
        )
        service._database = lambda: {"ready": False, "code": "DATABASE_UNAVAILABLE"}
        result = service.check_all()
        encoded = json.dumps(result)
        self.assertFalse(result["ready"])
        self.assertEqual(result["database"]["code"], "DATABASE_UNAVAILABLE")
        self.assertNotIn("password", encoded.lower())

    def test_production_readiness_builds_real_dependency_clients(self):
        production = SimpleNamespace(
            task_backend="celery",
            artifact_storage_backend="minio",
            redis_events_url=SimpleNamespace(
                get_secret_value=lambda: "redis://events/1",
            ),
        )
        redis_client = MagicMock()
        storage = MagicMock()
        celery_app = MagicMock()
        with patch.object(
            readiness_api.Redis,
            "from_url",
            return_value=redis_client,
        ), patch.object(
            readiness_api,
            "create_artifact_storage",
            return_value=storage,
        ), patch.object(readiness_api, "celery_app", celery_app):
            service = readiness_api.build_readiness_service(production)

        self.assertIs(service.redis_client, redis_client)
        self.assertIs(service.celery_app, celery_app)
        self.assertIs(service.storage, storage)


if __name__ == "__main__": unittest.main()
