"""Celery tasks for persisted inference deployments and rollouts."""

import uuid

from app.config import settings
from app.database import SessionLocal
from app.models.model_registry import DeploymentRollout
from app.services.inference_deployment import InferenceDeploymentService
from app.services.inference_observability import InferenceObservability
from app.services.inference_rollout import InferenceRolloutError, InferenceRolloutService
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


def build_inference_rollout_service():
    return InferenceRolloutService(build_inference_deployment_service().runtime)


def _rollout_result(rollout):
    return {
        "id": str(rollout.id),
        "state": rollout.state,
        "lock_version": int(rollout.lock_version),
    }


def _persisted_rollout(db, rollout_id):
    try:
        rollout_uuid = uuid.UUID(str(rollout_id))
    except (TypeError, ValueError, AttributeError):
        return None
    return db.query(DeploymentRollout).filter(
        DeploymentRollout.id == rollout_uuid,
    ).first()


def _known_rollout_error_result(db, rollout_id, error):
    if error.code == "ROLLOUT_REVISION_CONFLICT":
        persisted = _persisted_rollout(db, rollout_id)
        if persisted is not None:
            return _rollout_result(persisted)
    return {"id": str(rollout_id), "error_code": error.code}


@celery_app.task(name="ml_platform.reconcile_inference_deployments")
def reconcile_inference_deployments():
    with SessionLocal() as db:
        deployment_service = build_inference_deployment_service()
        return deployment_service.reconcile(db)


@celery_app.task(name="ml_platform.advance_inference_rollout")
def advance_inference_rollout(rollout_id, expected_lock_version):
    with SessionLocal() as db:
        try:
            rollout = build_inference_rollout_service().advance(
                db,
                rollout_id,
                expected_lock_version=expected_lock_version,
            )
        except InferenceRolloutError as error:
            return _known_rollout_error_result(db, rollout_id, error)
        return _rollout_result(rollout)


@celery_app.task(name="ml_platform.rollback_inference_rollout")
def rollback_inference_rollout(rollout_id, expected_lock_version):
    with SessionLocal() as db:
        try:
            rollout = build_inference_rollout_service().rollback(
                db,
                rollout_id,
                expected_lock_version=expected_lock_version,
            )
        except InferenceRolloutError as error:
            return _known_rollout_error_result(db, rollout_id, error)
        return _rollout_result(rollout)


@celery_app.task(name="ml_platform.reconcile_inference_rollouts")
def reconcile_inference_rollouts():
    with SessionLocal() as db:
        rollout_service = build_inference_rollout_service()
        recovering = db.query(DeploymentRollout).filter(
            DeploymentRollout.state.in_(("pending", "preloading")),
        ).all()
        result = (
            rollout_service.reconcile(db)
            if recovering
            else {"loaded": 0, "failed": 0}
        )
        advanced = 0
        advance_failed = 0
        progressing = db.query(DeploymentRollout).filter(
            DeploymentRollout.state == "progressing",
        ).all()
        for rollout in progressing:
            try:
                rollout_service.advance(
                    db,
                    rollout.id,
                    expected_lock_version=rollout.lock_version,
                )
                advanced += 1
            except InferenceRolloutError as error:
                if error.code != "ROLLOUT_REVISION_CONFLICT":
                    advance_failed += 1
        return {
            **result,
            "advanced": advanced,
            "advance_failed": advance_failed,
        }


@celery_app.task(name="ml_platform.prune_inference_telemetry")
def prune_inference_telemetry():
    with SessionLocal() as db:
        pruned = InferenceObservability(
            log_retention_days=settings.inference_log_retention_days,
        ).prune(db)
        db.commit()
        return {"pruned": pruned}
