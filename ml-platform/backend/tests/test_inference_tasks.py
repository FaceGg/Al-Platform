"""Tests for app.tasks.inference_tasks.

The reconciliation task and service builder had no dedicated tests.
We exercise the configuration-guarding logic and the reconcile path
with mocked runtime client and session.
"""
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

sys.path.insert(0, ".")

from app.tasks import inference_tasks


class TestBuildInferenceDeploymentService(unittest.TestCase):
    def test_raises_when_runtime_url_missing(self):
        settings = SimpleNamespace(
            inference_runtime_url=None,
            resolved_inference_internal_secret=None,
            inference_load_timeout_seconds=60,
            inference_predict_timeout_seconds=30,
        )
        with patch.object(inference_tasks, "settings", settings):
            with self.assertRaises(RuntimeError) as ctx:
                inference_tasks.build_inference_deployment_service()
            self.assertIn("not configured", str(ctx.exception))

    def test_raises_when_secret_missing(self):
        settings = SimpleNamespace(
            inference_runtime_url="http://runtime:8000",
            resolved_inference_internal_secret=None,
            inference_load_timeout_seconds=60,
            inference_predict_timeout_seconds=30,
        )
        with patch.object(inference_tasks, "settings", settings):
            with self.assertRaises(RuntimeError):
                inference_tasks.build_inference_deployment_service()

    def test_returns_service_when_configured(self):
        from pydantic import SecretStr

        fake_client = MagicMock()
        fake_service = MagicMock()
        settings = SimpleNamespace(
            inference_runtime_url="http://runtime:8000",
            resolved_inference_internal_secret=SecretStr("x" * 32),
            inference_load_timeout_seconds=60,
            inference_predict_timeout_seconds=30,
        )
        with patch.object(inference_tasks, "settings", settings), \
             patch.object(inference_tasks, "InferenceRuntimeClient", return_value=fake_client) as client_cls, \
             patch.object(inference_tasks, "InferenceDeploymentService", return_value=fake_service) as svc_cls, \
             patch.object(inference_tasks, "SessionLocal") as session_local:
            result = inference_tasks.build_inference_deployment_service()
            self.assertIs(result, fake_service)
            client_cls.assert_called_once_with(
                "http://runtime:8000",
                "x" * 32,
                load_timeout_seconds=60,
                predict_timeout_seconds=30,
            )
            svc_cls.assert_called_once_with(fake_client, session_local)


class TestReconcileInferenceDeploymentsTask(unittest.TestCase):
    def test_task_invokes_reconcile_with_session(self):
        fake_service = MagicMock()
        fake_service.reconcile.return_value = {"loaded": 1, "unloaded": 0, "failed": 0}
        fake_session = MagicMock()
        fake_session.__enter__ = MagicMock(return_value=fake_session)
        fake_session.__exit__ = MagicMock(return_value=False)

        with patch.object(inference_tasks, "SessionLocal") as session_local, \
             patch.object(inference_tasks, "build_inference_deployment_service", return_value=fake_service) as builder:
            session_local.return_value = fake_session
            result = inference_tasks.reconcile_inference_deployments()

            builder.assert_called_once()
            fake_service.reconcile.assert_called_once_with(
                fake_session,
                include_rollout_aliases=False,
            )
            self.assertEqual(result, {"loaded": 1, "unloaded": 0, "failed": 0})

    def test_task_name_is_namespaced(self):
        self.assertEqual(
            inference_tasks.reconcile_inference_deployments.name,
            "ml_platform.reconcile_inference_deployments",
        )


if __name__ == "__main__":
    unittest.main()
