"""Inference deployment desired/observed state orchestration."""

from datetime import datetime, timezone
import uuid

from app.models.artifact import Artifact
from app.models.model_registry import InferenceDeployment, ModelVersion
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
        if commit:
            db.commit()
            db.refresh(deployment)
        else:
            db.flush()
        return deployment

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
        version = db.query(ModelVersion).filter(
            ModelVersion.id == deployment.model_version_id,
        ).one()
        artifact = db.query(Artifact).filter(
            Artifact.id == version.onnx_artifact_id,
        ).one()
        metadata = version.conversion_metadata or {}
        return {
            "deployment_id": str(deployment.id),
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
            self.runtime.unload(deployment.id)
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

    def predict(self, db, deployment_id, records):
        deployment = self._deployment(db, deployment_id)
        if deployment.desired_state != "running" or deployment.observed_state != "running":
            raise InferenceDeploymentError("DEPLOYMENT_NOT_READY")
        try:
            return self.runtime.predict(deployment.id, records)
        except (InferenceRuntimeClientError, InferenceDeploymentError) as error:
            raise InferenceDeploymentError(self._runtime_code(error)) from None

    def reconcile(self, db):
        runtime_ids = {
            str(item["deployment_id"])
            for item in self.runtime.list().get("items", [])
        }
        desired = db.query(InferenceDeployment).all()
        loaded = unloaded = failed = 0
        desired_ids = {str(item.id) for item in desired if item.desired_state == "running"}
        for deployment in desired:
            try:
                if deployment.desired_state == "running" and str(deployment.id) not in runtime_ids:
                    self.runtime.load(deployment.id, self._specification(db, deployment))
                    deployment.observed_state = "running"
                    deployment.last_error_code = None
                    loaded += 1
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
        for orphan_id in runtime_ids - desired_ids:
            if not any(str(item.id) == orphan_id for item in desired):
                try:
                    self.runtime.unload(orphan_id)
                    unloaded += 1
                except Exception:
                    failed += 1
        db.commit()
        return {"loaded": loaded, "unloaded": unloaded, "failed": failed}
