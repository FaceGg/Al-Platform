"""Weighted inference routing and durable rollout state transitions."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import math
from typing import Mapping
from uuid import UUID

from sqlalchemy import update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import object_session

from app.events.domain import (
    DomainEventRecorder,
    NullDomainEventRecorder,
    create_domain_event,
)
from app.models.artifact import Artifact
from app.models.model_registry import (
    DeploymentRevision,
    DeploymentRollout,
    DeploymentTarget,
    InferenceDeployment,
    ModelVersion,
)


DEFAULT_STEP_SCHEDULE = (0, 1000, 5000, 10000)
DEFAULT_THRESHOLDS = {"max_error_rate": 0.01, "max_p95_ms": 500}
ACTIVE_ROLLOUT_STATES = frozenset({"pending", "preloading", "progressing", "paused"})
TERMINAL_ROLLOUT_STATES = frozenset({"completed", "failed", "rolled_back"})


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class InferenceRolloutError(RuntimeError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class RoutedTarget:
    revision_id: UUID | str
    model_version_id: UUID | str


class WeightedTargetRouter:
    """Select a deterministic target from immutable basis-point weights."""

    @staticmethod
    def _bucket(deployment_id, routing_key) -> int:
        digest = hashlib.sha256(
            f"{deployment_id}:{routing_key}".encode("utf-8")
        ).digest()
        return int.from_bytes(digest[:8], "big") % 10000

    @staticmethod
    def _targets(revision):
        targets = list(getattr(revision, "targets", ()) or ())
        targets.sort(key=lambda item: str(item.model_version_id))
        if not targets:
            raise InferenceRolloutError("TARGET_WEIGHTS_INVALID")
        weights = [getattr(item, "weight_bps", None) for item in targets]
        if any(
            isinstance(weight, bool)
            or not isinstance(weight, int)
            or weight < 0
            or weight > 10000
            for weight in weights
        ) or sum(weights) != 10000:
            raise InferenceRolloutError("TARGET_WEIGHTS_INVALID")
        return targets

    def select(self, revision, routing_key) -> RoutedTarget:
        targets = self._targets(revision)
        bucket = self._bucket(revision.deployment_id, routing_key)
        cumulative = 0
        for target in targets:
            cumulative += int(target.weight_bps)
            if bucket < cumulative:
                return RoutedTarget(revision.id, target.model_version_id)
        raise InferenceRolloutError("TARGET_WEIGHTS_INVALID")

    def select_active(self, deployment, routing_key) -> RoutedTarget:
        db = object_session(deployment)
        if db is None:
            raise InferenceRolloutError("INFERENCE_DEPLOYMENT_NOT_ATTACHED")
        rollout = db.query(DeploymentRollout).filter(
            DeploymentRollout.deployment_id == deployment.id,
            DeploymentRollout.state.in_(tuple(ACTIVE_ROLLOUT_STATES)),
        ).order_by(DeploymentRollout.created_at.desc()).first()
        stable = db.query(DeploymentRevision).filter(
            DeploymentRevision.deployment_id == deployment.id,
            DeploymentRevision.status == "stable",
        ).order_by(DeploymentRevision.revision_number.desc()).first()
        if rollout is not None and rollout.from_revision is not None:
            stable = rollout.from_revision
        if stable is None:
            raise InferenceRolloutError("STABLE_REVISION_NOT_FOUND")
        selected = stable
        if rollout is not None and rollout.state == "progressing":
            candidate_bucket = self._bucket(deployment.id, routing_key)
            if candidate_bucket < int(rollout.current_step):
                selected = rollout.to_revision
        return self.select(selected, routing_key)


class InferenceRolloutService:
    def __init__(
        self,
        runtime,
        *,
        event_recorder: DomainEventRecorder | None = None,
        clock=utcnow,
        step_schedule=DEFAULT_STEP_SCHEDULE,
        thresholds=DEFAULT_THRESHOLDS,
    ):
        self.runtime = runtime
        self.event_recorder = event_recorder or NullDomainEventRecorder()
        self.clock = clock
        self.step_schedule = tuple(step_schedule)
        self.thresholds = dict(thresholds)

    @staticmethod
    def _uuid(value, code):
        try:
            return UUID(str(value))
        except (TypeError, ValueError, AttributeError):
            raise InferenceRolloutError(code) from None

    @staticmethod
    def _deployment(db, deployment_id, *, lock=False):
        deployment_uuid = InferenceRolloutService._uuid(
            deployment_id, "INFERENCE_DEPLOYMENT_NOT_FOUND"
        )
        query = db.query(InferenceDeployment).filter(
            InferenceDeployment.id == deployment_uuid,
        )
        if lock:
            query = query.with_for_update()
        deployment = query.first()
        if deployment is None:
            raise InferenceRolloutError("INFERENCE_DEPLOYMENT_NOT_FOUND")
        return deployment

    @staticmethod
    def _rollout(db, rollout_id, *, lock=False):
        rollout_uuid = InferenceRolloutService._uuid(
            rollout_id, "ROLLOUT_NOT_FOUND"
        )
        query = db.query(DeploymentRollout).filter(
            DeploymentRollout.id == rollout_uuid,
        )
        if lock:
            query = query.with_for_update()
        rollout = query.first()
        if rollout is None:
            raise InferenceRolloutError("ROLLOUT_NOT_FOUND")
        return rollout

    @staticmethod
    def _normalize_steps(steps):
        try:
            values = tuple(int(item) for item in steps)
        except (TypeError, ValueError):
            raise InferenceRolloutError("ROLLOUT_STEP_SCHEDULE_INVALID") from None
        if (
            not values
            or values[0] != 0
            or values[-1] != 10000
            or len(set(values)) != len(values)
            or any(item < 0 or item > 10000 for item in values)
            or tuple(sorted(values)) != values
        ):
            raise InferenceRolloutError("ROLLOUT_STEP_SCHEDULE_INVALID")
        return values

    @staticmethod
    def _normalize_thresholds(thresholds):
        values = dict(DEFAULT_THRESHOLDS)
        if thresholds is not None:
            if not isinstance(thresholds, Mapping):
                raise InferenceRolloutError("ROLLOUT_THRESHOLDS_INVALID")
            values.update(thresholds)
        error_rate = values.get("max_error_rate")
        p95 = values.get("max_p95_ms")
        if (
            isinstance(error_rate, bool)
            or not isinstance(error_rate, (int, float))
            or not math.isfinite(float(error_rate))
            or not 0 <= float(error_rate) <= 1
            or isinstance(p95, bool)
            or not isinstance(p95, (int, float))
            or not math.isfinite(float(p95))
            or float(p95) < 0
        ):
            raise InferenceRolloutError("ROLLOUT_THRESHOLDS_INVALID")
        return {"max_error_rate": float(error_rate), "max_p95_ms": float(p95)}

    @staticmethod
    def _target_values(target):
        if isinstance(target, Mapping):
            model_id = target.get("model_version_id")
            weight = target.get("weight_bps")
        elif isinstance(target, (tuple, list)) and len(target) == 2:
            model_id, weight = target
        else:
            model_id = getattr(target, "model_version_id", None)
            weight = getattr(target, "weight_bps", None)
        if isinstance(weight, bool) or not isinstance(weight, int):
            raise InferenceRolloutError("TARGET_WEIGHTS_INVALID")
        if weight < 0 or weight > 10000:
            raise InferenceRolloutError("TARGET_WEIGHTS_INVALID")
        return model_id, weight

    def validate_targets(self, db, revision_id):
        revision_uuid = self._uuid(revision_id, "REVISION_NOT_FOUND")
        targets = db.query(DeploymentTarget).filter(
            DeploymentTarget.revision_id == revision_uuid,
        ).all()
        weights = [getattr(item, "weight_bps", None) for item in targets]
        if not targets or any(
            isinstance(weight, bool)
            or not isinstance(weight, int)
            or weight < 0
            or weight > 10000
            for weight in weights
        ) or sum(weights) != 10000:
            raise InferenceRolloutError("TARGET_WEIGHTS_INVALID")
        if len({str(item.model_version_id) for item in targets}) != len(targets):
            raise InferenceRolloutError("TARGET_DUPLICATE")
        return targets

    def _stable_revision(self, db, deployment, actor_id):
        revision = db.query(DeploymentRevision).filter(
            DeploymentRevision.deployment_id == deployment.id,
            DeploymentRevision.status == "stable",
        ).order_by(DeploymentRevision.revision_number.desc()).first()
        if revision is not None:
            return revision
        revision = DeploymentRevision(
            deployment_id=deployment.id,
            revision_number=1,
            strategy="immediate",
            status="stable",
            created_by_id=actor_id,
        )
        db.add(revision)
        db.flush()
        db.add(DeploymentTarget(
            revision_id=revision.id,
            model_version_id=deployment.model_version_id,
            weight_bps=10000,
            role="stable",
        ))
        db.flush()
        return revision

    def _record(self, db, deployment, rollout, event_type, *, actor_id=None, error_code=None):
        payload = {
            "revision_id": str(rollout.to_revision_id),
            "deployment_id": str(deployment.id),
            "model_version_ids": [
                str(target.model_version_id)
                for target in (rollout.to_revision.targets or ())
            ],
        }
        if error_code:
            payload["error_code"] = error_code
        if event_type in {"rollout.started", "rollout.failed", "runtime.load_failed"}:
            payload["step"] = int(rollout.current_step)
        event = create_domain_event(
            idempotency_key=(
                f"rollout:{rollout.id}:{rollout.state}:{rollout.lock_version}"
            ),
            event_type=event_type,
            severity="error" if error_code else "info",
            occurred_at=self.clock(),
            project_id=deployment.project_id,
            actor_id=actor_id,
            resource_type="inference_deployment",
            resource_id=str(deployment.id),
            payload=payload,
        )
        self.event_recorder.record(db, event)

    def record_rollout_completed(self, db, deployment_id, revision_id, actor_id=None):
        deployment = self._deployment(db, deployment_id)
        revision = db.query(DeploymentRevision).filter(
            DeploymentRevision.id == self._uuid(revision_id, "REVISION_NOT_FOUND"),
        ).first()
        if revision is None:
            raise InferenceRolloutError("REVISION_NOT_FOUND")
        rollout = DeploymentRollout(
            id=revision.id,
            deployment_id=deployment.id,
            to_revision_id=revision.id,
            state="completed",
            current_step=10000,
            lock_version=1,
        )
        rollout.to_revision = revision
        self._record(db, deployment, rollout, "rollout.completed", actor_id=actor_id)

    def create_candidate(
        self,
        db,
        deployment_id,
        actor_id,
        targets,
        strategy="canary",
        step_schedule=None,
        thresholds=None,
    ):
        deployment = self._deployment(db, deployment_id, lock=True)
        if strategy not in {"immediate", "canary", "rolling"}:
            raise InferenceRolloutError("REVISION_STRATEGY_INVALID")
        active = db.query(DeploymentRollout).filter(
            DeploymentRollout.deployment_id == deployment.id,
            DeploymentRollout.state.in_(tuple(ACTIVE_ROLLOUT_STATES)),
        ).with_for_update().first()
        if active is not None:
            raise InferenceRolloutError("ROLLOUT_ALREADY_ACTIVE")
        normalized_targets = []
        seen = set()
        for target in targets or ():
            model_id, weight = self._target_values(target)
            model_uuid = self._uuid(model_id, "MODEL_VERSION_NOT_FOUND")
            if str(model_uuid) in seen:
                raise InferenceRolloutError("TARGET_DUPLICATE")
            seen.add(str(model_uuid))
            version = db.query(ModelVersion).filter(ModelVersion.id == model_uuid).first()
            if version is None or version.registered_model.project_id != deployment.project_id:
                raise InferenceRolloutError("MODEL_VERSION_NOT_FOUND")
            if version.approval_status != "approved":
                raise InferenceRolloutError("MODEL_VERSION_NOT_APPROVED")
            normalized_targets.append((model_uuid, weight))
        if not normalized_targets or sum(item[1] for item in normalized_targets) != 10000:
            raise InferenceRolloutError("TARGET_WEIGHTS_INVALID")
        stable = self._stable_revision(db, deployment, actor_id)
        max_number = db.query(DeploymentRevision.revision_number).filter(
            DeploymentRevision.deployment_id == deployment.id,
        ).order_by(DeploymentRevision.revision_number.desc()).first()
        revision = DeploymentRevision(
            deployment_id=deployment.id,
            revision_number=(int(max_number[0]) if max_number else 0) + 1,
            strategy=strategy,
            status="candidate",
            created_by_id=actor_id,
        )
        db.add(revision)
        db.flush()
        db.add_all([
            DeploymentTarget(
                revision_id=revision.id,
                model_version_id=model_id,
                weight_bps=weight,
                role="candidate",
            )
            for model_id, weight in normalized_targets
        ])
        rollout = DeploymentRollout(
            deployment_id=deployment.id,
            from_revision_id=stable.id,
            to_revision_id=revision.id,
            state="pending",
            current_step=0,
            lock_version=1,
            step_schedule=list(self._normalize_steps(step_schedule or self.step_schedule)),
            thresholds=self._normalize_thresholds(thresholds),
        )
        db.add(rollout)
        try:
            db.flush()
            self._record(db, deployment, rollout, "rollout.started", actor_id=actor_id)
            db.commit()
            db.refresh(rollout)
        except IntegrityError:
            db.rollback()
            raise InferenceRolloutError("ROLLOUT_ALREADY_ACTIVE") from None
        return rollout

    @staticmethod
    def _transition(db, rollout, expected_lock_version, **values):
        current = int(rollout.lock_version)
        if expected_lock_version is not None and int(expected_lock_version) != current:
            raise InferenceRolloutError("ROLLOUT_REVISION_CONFLICT")
        result = db.execute(
            update(DeploymentRollout).where(
                DeploymentRollout.id == rollout.id,
                DeploymentRollout.lock_version == current,
            ).values(
                **values,
                lock_version=current + 1,
                updated_at=utcnow(),
            )
        )
        if result.rowcount != 1:
            raise InferenceRolloutError("ROLLOUT_REVISION_CONFLICT")
        db.flush()
        db.refresh(rollout)
        return rollout

    @staticmethod
    def _check_expected(rollout, expected_lock_version):
        if expected_lock_version is not None and int(expected_lock_version) != int(rollout.lock_version):
            raise InferenceRolloutError("ROLLOUT_REVISION_CONFLICT")

    def _preload_revision(self, db, rollout, revision=None):
        revision = revision or rollout.to_revision
        preload = getattr(self.runtime, "preload", None)
        if callable(preload):
            return preload(rollout.deployment_id, revision.id)
        loader = getattr(self.runtime, "load", None)
        if not callable(loader):
            raise InferenceRolloutError("INFERENCE_RUNTIME_UNAVAILABLE")
        for target in revision.targets or ():
            version = db.query(ModelVersion).filter(ModelVersion.id == target.model_version_id).one()
            artifact = db.query(Artifact).filter(Artifact.id == version.onnx_artifact_id).one()
            metadata = version.conversion_metadata or {}
            specification = {
                "runtime_key": f"{revision.id}:{target.model_version_id}",
                "deployment_id": str(rollout.deployment_id),
                "revision_id": str(revision.id),
                "model_version_id": str(version.id),
                "version_number": int(version.version_number),
                "storage_uri": artifact.storage_uri,
                "sha256": metadata.get("sha256") or (artifact.metadata_ or {}).get("sha256"),
                "size": int(metadata.get("size") or artifact.file_size or 0),
                "feature_schema": version.feature_schema,
                "output_schema": version.output_schema,
                "input_names": metadata.get("input_names", []),
                "output_names": metadata.get("output_names", []),
            }
            loader(specification["runtime_key"], specification)

    def preload(self, db, rollout_id, expected_lock_version=None):
        rollout = self._rollout(db, rollout_id, lock=True)
        if rollout.state == "progressing":
            return rollout
        if rollout.state in TERMINAL_ROLLOUT_STATES:
            return rollout
        if rollout.state != "pending":
            raise InferenceRolloutError("ROLLOUT_INVALID_STATE")
        self._transition(
            db,
            rollout,
            expected_lock_version,
            state="preloading",
            started_at=self.clock(),
            last_error_code=None,
        )
        db.commit()
        try:
            self._preload_revision(db, rollout)
        except Exception as error:
            code = getattr(error, "code", "INFERENCE_RUNTIME_UNAVAILABLE")
            rollout = self._rollout(db, rollout.id, lock=True)
            self._transition(
                db,
                rollout,
                rollout.lock_version,
                state="failed",
                current_step=0,
                last_error_code="ROLLOUT_PRELOAD_FAILED",
                completed_at=self.clock(),
            )
            deployment = self._deployment(db, rollout.deployment_id)
            self._record(
                db, deployment, rollout, "runtime.load_failed", error_code=code,
            )
            self._record(
                db, deployment, rollout, "rollout.failed",
                error_code="ROLLOUT_PRELOAD_FAILED",
            )
            db.commit()
            raise InferenceRolloutError("ROLLOUT_PRELOAD_FAILED") from None
        rollout = self._rollout(db, rollout.id, lock=True)
        self._transition(db, rollout, rollout.lock_version, state="progressing")
        db.commit()
        return rollout

    @staticmethod
    def _observation(runtime, rollout):
        for name in ("observe", "health", "metrics"):
            method = getattr(runtime, name, None)
            if callable(method):
                try:
                    value = method(rollout)
                except TypeError:
                    value = method()
                if isinstance(value, Mapping):
                    return value
        return {"error_rate": 0.0, "p95_ms": 0.0}

    def _health_failed(self, rollout, observation):
        observation = observation or {}
        error_rate = observation.get("error_rate", observation.get("max_error_rate", 0.0))
        p95 = observation.get("p95_ms", observation.get("p95_latency_ms", 0.0))
        try:
            return (
                float(error_rate) > float((rollout.thresholds or {}).get("max_error_rate", 0.01))
                or float(p95) > float((rollout.thresholds or {}).get("max_p95_ms", 500))
            )
        except (TypeError, ValueError):
            return True

    def advance(self, db, rollout_id, expected_lock_version=None, observation=None):
        rollout = self._rollout(db, rollout_id, lock=True)
        if rollout.state == "completed":
            return rollout
        if rollout.state in {"failed", "rolled_back"}:
            return rollout
        if rollout.state != "progressing":
            raise InferenceRolloutError("ROLLOUT_INVALID_STATE")
        if self._health_failed(rollout, observation or self._observation(self.runtime, rollout)):
            self._transition(
                db,
                rollout,
                expected_lock_version,
                state="paused",
                current_step=0,
                last_error_code="ROLLOUT_HEALTH_THRESHOLD_EXCEEDED",
            )
            deployment = self._deployment(db, rollout.deployment_id)
            self._record(
                db, deployment, rollout, "rollout.failed",
                error_code="ROLLOUT_HEALTH_THRESHOLD_EXCEEDED",
            )
            db.commit()
            raise InferenceRolloutError("ROLLOUT_HEALTH_THRESHOLD_EXCEEDED")
        steps = list(rollout.step_schedule or DEFAULT_STEP_SCHEDULE)
        current = int(rollout.current_step)
        next_steps = [step for step in steps if int(step) > current]
        if not next_steps:
            return rollout
        next_step = int(next_steps[0])
        if next_step >= 10000:
            self._check_expected(rollout, expected_lock_version)
            deployment = self._deployment(db, rollout.deployment_id)
            try:
                self._replace_legacy_runtime(
                    db,
                    deployment,
                    from_revision=rollout.from_revision,
                    to_revision=rollout.to_revision,
                )
            except InferenceRolloutError:
                self._transition(
                    db,
                    rollout,
                    rollout.lock_version,
                    state="paused",
                    current_step=0,
                    last_error_code="ROLLOUT_LEGACY_REFRESH_FAILED",
                )
                self._record(
                    db,
                    deployment,
                    rollout,
                    "rollout.failed",
                    error_code="ROLLOUT_LEGACY_REFRESH_FAILED",
                )
                db.commit()
                raise
            self._transition(
                db,
                rollout,
                expected_lock_version,
                state="completed",
                current_step=10000,
                last_error_code=None,
                completed_at=self.clock(),
            )
            rollout.to_revision.status = "stable"
            rollout.to_revision.activated_at = self.clock()
            rollout.from_revision.status = "superseded"
            self._record(db, deployment, rollout, "rollout.completed")
        else:
            self._transition(
                db,
                rollout,
                expected_lock_version,
                state="progressing",
                current_step=next_step,
                last_error_code=None,
            )
        db.commit()
        return rollout

    def _replace_legacy_runtime(
        self,
        db,
        deployment,
        *,
        from_revision,
        to_revision,
    ):
        """Replace legacy key while retaining a stable fallback on load failure."""
        loader = getattr(self.runtime, "load", None)
        if not callable(loader):
            return
        unloader = getattr(self.runtime, "unload", None)
        if not callable(unloader):
            raise InferenceRolloutError("INFERENCE_RUNTIME_UNAVAILABLE")
        if from_revision is None or to_revision is None:
            raise InferenceRolloutError("STABLE_REVISION_NOT_FOUND")
        from app.services.inference_deployment import InferenceDeploymentService

        previous_specification = InferenceDeploymentService._specification(
            db,
            deployment,
            revision=from_revision,
        )
        replacement_specification = InferenceDeploymentService._specification(
            db,
            deployment,
            revision=to_revision,
        )
        try:
            unloader(deployment.id)
            loader(deployment.id, replacement_specification)
        except Exception:
            try:
                unloader(deployment.id)
                loader(deployment.id, previous_specification)
            except Exception:
                pass
            raise InferenceRolloutError("ROLLOUT_LEGACY_REFRESH_FAILED") from None

    def pause(self, db, rollout_id, expected_lock_version=None):
        rollout = self._rollout(db, rollout_id, lock=True)
        if rollout.state in {"paused", "failed", "rolled_back", "completed"}:
            return rollout
        if rollout.state not in {"pending", "preloading", "progressing"}:
            raise InferenceRolloutError("ROLLOUT_INVALID_STATE")
        self._transition(
            db,
            rollout,
            expected_lock_version,
            state="paused",
            current_step=0,
            last_error_code=None,
        )
        db.commit()
        return rollout

    def resume(self, db, rollout_id, expected_lock_version=None):
        rollout = self._rollout(db, rollout_id, lock=True)
        if rollout.state == "progressing":
            return rollout
        if rollout.state != "paused":
            raise InferenceRolloutError("ROLLOUT_INVALID_STATE")
        self._transition(
            db,
            rollout,
            expected_lock_version,
            state="progressing",
            current_step=0,
            last_error_code=None,
        )
        db.commit()
        return rollout

    def rollback(self, db, rollout_id, expected_lock_version=None):
        rollout = self._rollout(db, rollout_id, lock=True)
        if rollout.state == "rolled_back":
            return rollout
        if rollout.state not in {
            "pending", "preloading", "progressing", "paused", "completed", "failed",
        }:
            raise InferenceRolloutError("ROLLOUT_INVALID_STATE")
        self._check_expected(rollout, expected_lock_version)
        try:
            self._preload_revision(db, rollout, revision=rollout.from_revision)
            unload = getattr(self.runtime, "unload", None)
            if callable(unload):
                for target in rollout.to_revision.targets or ():
                    unload(f"{rollout.to_revision.id}:{target.model_version_id}")
            self._transition(
                db,
                rollout,
                expected_lock_version,
                state="rolled_back",
                current_step=0,
                last_error_code=None,
                completed_at=self.clock(),
            )
            rollout.to_revision.status = "failed"
            rollout.from_revision.status = "stable"
            deployment = self._deployment(db, rollout.deployment_id)
            self._record(db, deployment, rollout, "rollback.completed")
            db.commit()
        except InferenceRolloutError as error:
            db.rollback()
            if error.code == "ROLLOUT_REVISION_CONFLICT":
                raise
            rollout = self._rollout(db, rollout_id, lock=True)
            self._transition(
                db,
                rollout,
                rollout.lock_version,
                state="failed",
                current_step=0,
                last_error_code="ROLLOUT_ROLLBACK_FAILED",
            )
            db.commit()
            raise InferenceRolloutError("ROLLOUT_ROLLBACK_FAILED") from None
        except Exception:
            db.rollback()
            rollout = self._rollout(db, rollout_id, lock=True)
            self._transition(
                db,
                rollout,
                rollout.lock_version,
                state="failed",
                current_step=0,
                last_error_code="ROLLOUT_ROLLBACK_FAILED",
            )
            db.commit()
            raise InferenceRolloutError("ROLLOUT_ROLLBACK_FAILED") from None
        return rollout

    def reconcile(self, db):
        loaded = 0
        failed = 0
        active = db.query(DeploymentRollout).filter(
            DeploymentRollout.state.in_(tuple(ACTIVE_ROLLOUT_STATES)),
        ).all()
        for rollout in active:
            try:
                self._preload_revision(db, rollout)
                if rollout.state in {"pending", "preloading"}:
                    locked = self._rollout(db, rollout.id, lock=True)
                    self._transition(
                        db,
                        locked,
                        locked.lock_version,
                        state="progressing",
                        started_at=locked.started_at or self.clock(),
                        last_error_code=None,
                    )
                loaded += 1
            except Exception:
                rollout = self._rollout(db, rollout.id, lock=True)
                self._transition(
                    db,
                    rollout,
                    rollout.lock_version,
                    state="failed",
                    current_step=0,
                    last_error_code="ROLLOUT_PRELOAD_FAILED",
                )
                failed += 1
        db.commit()
        return {"loaded": loaded, "failed": failed}
