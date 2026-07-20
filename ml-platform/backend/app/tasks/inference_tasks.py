"""Celery reconciliation task for inference deployments."""

from app.config import settings
from app.database import SessionLocal
from app.services.inference_deployment import InferenceDeploymentService
from app.services.inference_runtime_client import InferenceRuntimeClient
from app.tasks.celery_app import celery_app


def build_inference_deployment_service():
    secret = settings.resolved_inference_internal_secret
    if not settings.inference_runtime_url or secret is None:
        raise RuntimeError("Inference runtime is not configured")
    client = InferenceRuntimeClient(
        settings.inference_runtime_url,
        secret.get_secret_value(),
        load_timeout_seconds=settings.inference_load_timeout_seconds,
        predict_timeout_seconds=settings.inference_predict_timeout_seconds,
    )
    return InferenceDeploymentService(client, SessionLocal)


@celery_app.task(name="ml_platform.reconcile_inference_deployments")
def reconcile_inference_deployments():
    with SessionLocal() as db:
        return build_inference_deployment_service().reconcile(db)
