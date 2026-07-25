"""Inference deployment desired/observed state orchestration."""

from datetime import datetime, timezone
import uuid

from app.models.artifact import Artifact
from app.models.model_registry import (
    DeploymentRevision,
    DeploymentRollout,
    DeploymentTarget,
    InferenceDeployment,
    ModelVersion,
)
from app.services.inference_runtime_client import InferenceRuntimeClientError


def utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


class InferenceDeploymentError(RuntimeError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


class InferenceDeploymentService:
    def __init__(self, runtime_client, session_factory):
        self.runtime = runtime_client
        self.session_factory = session_factory

    @staticmethod
    def _uuid(value, code):
        try:
            return uuid.UUID(str(value))
        except (TypeError, ValueError, AttributeError):
            raise InferenceDeploymentError(code) from None

    def create(self, db, *, project_id, version_id, actor_id, name, commit=True):
        project_uuid = self._uuid(project_id, "PROJECT_NOT_FOUND")
        version_uuid = self._uuid(version_id, "MODEL_VERSION_NOT_FOUND")
        version = db.query(ModelVersion).filter(
            ModelVersion.id == version_uuid,
        ).first()
        if version is None or version.registered_model.project_id != project_uuid:
            raise InferenceDeploymentError("MODEL_VERSION_NOT_FOUND")
        if version.approval_status != "approved":
            raise InferenceDeploymentError("MODEL_NOT_APPROVED")
        normalized_name = str(name).strip()
        if not normalized_name or len(normalized_name) > 128:
            raise InferenceDeploymentError("DEPLOYMENT_NAME_INVALID")
        deployment = InferenceDeployment(
            project_id=project_uuid,
            name=normalized_name,
            model_version_id=version.id,
            desired_state="stopped",
            observed_state="stopped",
            created_by_id=actor_id,
        )
        db.add(deployment)
        db.flush()
        self._ensure_stable_revision(db, deployment, actor_id)
        if commit:
            db.commit()
            db.refresh(deployment)
        else:
            db.flush()
        return deployment

    @staticmethod
    def _ensure_stable_revision(db, deployment, actor_id=None):
        revision = db.query(DeploymentRevision).filter(
            DeploymentRevision.deployment_id == deployment.id,
            DeploymentRevision.status == "stable",
        ).order_by(DeploymentRevision.revision_number.desc()).first()
        if revision is not None:
            return revision
        latest = db.query(DeploymentRevision.revision_number).filter(
            DeploymentRevision.deployment_id == deployment.id,
        ).order_by(DeploymentRevision.revision_number.desc()).first()
        revision = DeploymentRevision(
            deployment_id=deployment.id,
            revision_number=(int(latest[0]) if latest else 0) + 1,
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

    def _deployment(self, db, deployment_id, lock=False):
        deployment_uuid = self._uuid(
            deployment_id, "INFERENCE_DEPLOYMENT_NOT_FOUND"
        )
        query = db.query(InferenceDeployment).filter(
            InferenceDeployment.id == deployment_uuid,
        )
        if lock:
            query = query.with_for_update()
        deployment = query.first()
        if deployment is None:
            raise InferenceDeploymentError("INFERENCE_DEPLOYMENT_NOT_FOUND")
        return deployment

    @staticmethod
    def _specification(db, deployment):
        revision = db.query(DeploymentRevision).filter(
            DeploymentRevision.deployment_id == deployment.id,
            DeploymentRevision.status == "stable",
        ).order_by(DeploymentRevision.revision_number.desc()).first()
        model_version_id = deployment.model_version_id
        if revision is not None and revision.targets:
            model_version_id = sorted(
                revision.targets,
                key=lambda target: (-int(target.weight_bps), str(target.model_version_id)),
            )[0].model_version_id
        version = db.query(ModelVersion).filter(
            ModelVersion.id == model_version_id,
        ).one()
        artifact = db.query(Artifact).filter(
            Artifact.id == version.onnx_artifact_id,
        ).one()
        metadata = version.conversion_metadata or {}
        return {
            "runtime_key": str(deployment.id),
            "deployment_id": str(deployment.id),
            "revision_id": str(revision.id) if revision is not None else None,
            "model_version_id": str(version.id),
            "version_number": version.version_number,
            "storage_uri": artifact.storage_uri,
            "sha256": metadata.get("sha256") or (artifact.metadata_ or {}).get("sha256"),
            "size": int(metadata.get("size") or artifact.file_size or 0),
            "feature_schema": version.feature_schema,
            "output_schema": version.output_schema,
            "input_names": metadata.get("input_names", []),
            "output_names": metadata.get("output_names", []),
        }

    @staticmethod
    def _target_specification(db, deployment, revision, target):
        version = db.query(ModelVersion).filter(
            ModelVersion.id == target.model_version_id,
        ).one()
        artifact = db.query(Artifact).filter(
            Artifact.id == version.onnx_artifact_id,
        ).one()
        metadata = version.conversion_metadata or {}
        return {
            "runtime_key": f"{revision.id}:{target.model_version_id}",
            "deployment_id": str(deployment.id),
            "revision_id": str(revision.id),
            "model_version_id": str(version.id),
            "version_number": version.version_number,
            "storage_uri": artifact.storage_uri,
            "sha256": metadata.get("sha256") or (artifact.metadata_ or {}).get("sha256"),
            "size": int(metadata.get("size") or artifact.file_size or 0),
            "feature_schema": version.feature_schema,
            "output_schema": version.output_schema,
            "input_names": metadata.get("input_names", []),
            "output_names": metadata.get("output_names", []),
        }

    def _load_stable_aliases(self, db, deployment, loaded_keys=None):
        revision = db.query(DeploymentRevision).filter(
            DeploymentRevision.deployment_id == deployment.id,
            DeploymentRevision.status == "stable",
        ).order_by(DeploymentRevision.revision_number.desc()).first()
        if revision is None:
            return
        loaded_keys = loaded_keys if loaded_keys is not None else set()
        for target in revision.targets or ():
            runtime_key = f"{revision.id}:{target.model_version_id}"
            if runtime_key in loaded_keys:
                continue
            self.runtime.load(
                runtime_key,
                self._target_specification(db, deployment, revision, target),
            )
            loaded_keys.add(runtime_key)

    def _runtime_keys_for_stop(self, db, deployment):
        """Find legacy and revision runtime keys belonging to deployment."""
        deployment_id = str(deployment.id)
        runtime_keys = {deployment_id}
        stable = db.query(DeploymentRevision).filter(
            DeploymentRevision.deployment_id == deployment.id,
            DeploymentRevision.status == "stable",
        ).order_by(DeploymentRevision.revision_number.desc()).first()
        revisions = [stable] if stable is not None else []
        active_rollouts = db.query(DeploymentRollout).filter(
            DeploymentRollout.deployment_id == deployment.id,
            DeploymentRollout.state.in_(("pending", "preloading", "progressing", "paused")),
        ).all()
        revisions.extend(rollout.to_revision for rollout in active_rollouts)
        for revision in revisions:
            runtime_keys.update(
                f"{revision.id}:{target.model_version_id}"
                for target in revision.targets or ()
            )

        lister = getattr(self.runtime, "list", None)
        if callable(lister):
            for item in (lister().get("items", []) or ()):
                if str(item.get("deployment_id")) != deployment_id:
                    continue
                runtime_key = item.get("runtime_key") or item.get("deployment_id")
                if runtime_key:
                    runtime_keys.add(str(runtime_key))
        return runtime_keys

    @staticmethod
    def _runtime_code(error):
        return getattr(error, "code", "INFERENCE_RUNTIME_UNAVAILABLE")

    def start(self, db, deployment_id):
        deployment = self._deployment(db, deployment_id, lock=True)
        if deployment.desired_state == "running" and deployment.observed_state == "running":
            return deployment
        deployment.desired_state = "running"
        deployment.observed_state = "starting"
        deployment.last_error_code = None
        db.commit()
        specification = self._specification(db, deployment)
        try:
            self.runtime.load(deployment.id, specification)
            self._load_stable_aliases(db, deployment, {str(deployment.id)})
        except Exception as error:
            deployment = self._deployment(db, deployment.id, lock=True)
            deployment.observed_state = "failed"
            deployment.last_error_code = self._runtime_code(error)
            deployment.last_checked_at = utcnow()
            db.commit()
            raise InferenceDeploymentError(deployment.last_error_code) from None
        deployment = self._deployment(db, deployment.id, lock=True)
        deployment.observed_state = "running"
        deployment.last_error_code = None
        deployment.started_at = utcnow()
        deployment.last_checked_at = utcnow()
        db.commit()
        db.refresh(deployment)
        return deployment

    def stop(self, db, deployment_id):
        deployment = self._deployment(db, deployment_id, lock=True)
        if deployment.desired_state == "stopped" and deployment.observed_state == "stopped":
            return deployment
        deployment.desired_state = "stopped"
        deployment.observed_state = "stopping"
        deployment.last_error_code = None
        db.commit()
        try:
            runtime_keys = self._runtime_keys_for_stop(db, deployment)
            first_error = None
            for runtime_key in sorted(runtime_keys):
                try:
                    self.runtime.unload(runtime_key)
                except Exception as error:
                    first_error = first_error or error
            if first_error is not None:
                raise first_error
        except Exception as error:
            deployment = self._deployment(db, deployment.id, lock=True)
            deployment.observed_state = "failed"
            deployment.last_error_code = self._runtime_code(error)
            deployment.last_checked_at = utcnow()
            db.commit()
            raise InferenceDeploymentError(deployment.last_error_code) from None
        deployment = self._deployment(db, deployment.id, lock=True)
        deployment.observed_state = "stopped"
        deployment.stopped_at = utcnow()
        deployment.last_checked_at = utcnow()
        db.commit()
        db.refresh(deployment)
        return deployment

    def predict(self, db, deployment_id, records, routing_key=None):
        deployment = self._deployment(db, deployment_id)
        if deployment.desired_state != "running" or deployment.observed_state != "running":
            raise InferenceDeploymentError("DEPLOYMENT_NOT_READY")
        try:
            runtime_key = deployment.id
            if routing_key is not None:
                from app.services.inference_rollout import WeightedTargetRouter

                routed = WeightedTargetRouter().select_active(deployment, routing_key)
                stable = db.query(DeploymentRevision).filter(
                    DeploymentRevision.deployment_id == deployment.id,
                    DeploymentRevision.status == "stable",
                ).order_by(DeploymentRevision.revision_number.desc()).first()
                if (
                    stable is None
                    or str(routed.revision_id) != str(stable.id)
                    or str(routed.model_version_id) != str(deployment.model_version_id)
                ):
                    runtime_key = f"{routed.revision_id}:{routed.model_version_id}"
            return self.runtime.predict(runtime_key, records)
        except (InferenceRuntimeClientError, InferenceDeploymentError) as error:
            raise InferenceDeploymentError(self._runtime_code(error)) from None

    def reconcile(self, db):
        runtime_items = self.runtime.list().get("items", [])
        runtime_ids = {
            str(item.get("runtime_key") or item["deployment_id"])
            for item in runtime_items
        }
        desired = db.query(InferenceDeployment).all()
        loaded = unloaded = failed = 0
        desired_ids = {str(item.id) for item in desired if item.desired_state == "running"}
        expected_runtime_ids = set(desired_ids)
        for deployment in desired:
            if deployment.desired_state != "running":
                continue
            stable_revision = db.query(DeploymentRevision).filter(
                DeploymentRevision.deployment_id == deployment.id,
                DeploymentRevision.status == "stable",
            ).order_by(DeploymentRevision.revision_number.desc()).first()
            if stable_revision is not None:
                expected_runtime_ids.update(
                    f"{stable_revision.id}:{target.model_version_id}"
                    for target in stable_revision.targets or ()
                )
        active_rollouts = db.query(DeploymentRollout).filter(
            DeploymentRollout.state.in_(("pending", "preloading", "progressing", "paused")),
        ).all()
        for rollout in active_rollouts:
            if str(rollout.deployment_id) not in desired_ids:
                continue
            revision = rollout.to_revision
            expected_runtime_ids.update(
                f"{revision.id}:{target.model_version_id}"
                for target in revision.targets or ()
            )
            for target in revision.targets or ():
                runtime_key = f"{revision.id}:{target.model_version_id}"
                if runtime_key in runtime_ids:
                    continue
                try:
                    self.runtime.load(
                        runtime_key,
                        self._target_specification(db, rollout.deployment, revision, target),
                    )
                    runtime_ids.add(runtime_key)
                    loaded += 1
                except Exception as error:
                    failed += 1
        for deployment in desired:
            try:
                expected_runtime_key = str(deployment.id)
                if deployment.desired_state == "running" and expected_runtime_key not in runtime_ids:
                    self.runtime.load(deployment.id, self._specification(db, deployment))
                    runtime_ids.add(expected_runtime_key)
                    deployment.observed_state = "running"
                    deployment.last_error_code = None
                    loaded += 1
                if deployment.desired_state == "running":
                    self._load_stable_aliases(db, deployment, runtime_ids)
                elif deployment.desired_state == "stopped" and str(deployment.id) in runtime_ids:
                    self.runtime.unload(deployment.id)
                    deployment.observed_state = "stopped"
                    deployment.last_error_code = None
                    unloaded += 1
                deployment.last_checked_at = utcnow()
            except Exception as error:
                deployment.observed_state = "failed"
                deployment.last_error_code = self._runtime_code(error)
                deployment.last_checked_at = utcnow()
                failed += 1
        for orphan_id in runtime_ids - expected_runtime_ids:
            if not any(str(item.id) == orphan_id for item in desired):
                try:
                    self.runtime.unload(orphan_id)
                    unloaded += 1
                except Exception:
                    failed += 1
        db.commit()
        return {"loaded": loaded, "unloaded": unloaded, "failed": failed}
