"""Model registry version creation and approval lifecycle."""

from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
import tempfile
import uuid

from sqlalchemy import func

from app.models.artifact import Artifact
from app.models.model_library import ModelLibrary
from app.models.model_registry import ModelVersion, RegisteredModel
from app.models.training import TrainingJob
from app.services.artifact_service import ArtifactService
from app.services.onnx_conversion import convert_platform_joblib, validate_onnx


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class ModelRegistryError(RuntimeError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


class ModelRegistryService:
    def __init__(
        self,
        *,
        artifact_service: ArtifactService,
        converter=convert_platform_joblib,
        validator=validate_onnx,
        conversion_timeout_seconds: int = 120,
    ):
        self.artifact_service = artifact_service
        self.converter = converter
        self.validator = validator
        self.conversion_timeout_seconds = conversion_timeout_seconds

    def compensate_version_artifact(self, storage_uri: str | None) -> None:
        if storage_uri:
            self.artifact_service.storage.delete(storage_uri)

    def create_registered_model(
        self,
        db,
        *,
        project_id,
        actor_id,
        name,
        description,
    ) -> RegisteredModel:
        normalized_name = str(name).strip()
        if not normalized_name or len(normalized_name) > 128:
            raise ModelRegistryError("MODEL_NAME_INVALID")
        model = RegisteredModel(
            project_id=project_id,
            name=normalized_name,
            description=str(description or "").strip(),
            created_by_id=actor_id,
        )
        db.add(model)
        db.flush()
        return model

    def _model(self, db, model_id) -> RegisteredModel:
        try:
            model_uuid = uuid.UUID(str(model_id))
        except (TypeError, ValueError, AttributeError):
            raise ModelRegistryError("REGISTERED_MODEL_NOT_FOUND") from None
        model = db.query(RegisteredModel).filter(
            RegisteredModel.id == model_uuid,
        ).with_for_update().first()
        if model is None:
            raise ModelRegistryError("REGISTERED_MODEL_NOT_FOUND")
        return model

    @staticmethod
    def _next_version_number(db, model_id) -> int:
        current = db.query(func.max(ModelVersion.version_number)).filter(
            ModelVersion.registered_model_id == model_id,
        ).scalar()
        return int(current or 0) + 1

    @staticmethod
    def _conversion_metadata(result) -> dict[str, object]:
        return {
            "converter": result.converter,
            "opset": result.opset,
            "input_names": list(result.input_names),
            "output_names": list(result.output_names),
            "sha256": result.sha256,
            "size": result.size,
        }

    def register_platform_version(
        self,
        db,
        *,
        model_id,
        source_model_library_id,
        actor_id,
        commit: bool = True,
    ) -> ModelVersion:
        model = self._model(db, model_id)
        try:
            source_uuid = uuid.UUID(str(source_model_library_id))
        except (TypeError, ValueError, AttributeError):
            raise ModelRegistryError("MODEL_SOURCE_NOT_FOUND") from None
        library = db.query(ModelLibrary).filter(
            ModelLibrary.id == source_uuid,
            ModelLibrary.project_id == model.project_id,
        ).first()
        if library is None or library.model_artifact_id is None:
            raise ModelRegistryError("MODEL_SOURCE_NOT_FOUND")
        artifact = db.query(Artifact).filter(
            Artifact.id == library.model_artifact_id,
            Artifact.project_id == model.project_id,
            Artifact.type == "model",
        ).first()
        if artifact is None:
            raise ModelRegistryError("MODEL_SOURCE_NOT_FOUND")
        metadata = artifact.metadata_ or {}
        if metadata.get("source") not in {"training", "automl"}:
            raise ModelRegistryError("MODEL_SOURCE_UNTRUSTED")
        job_id = metadata.get("training_job_id")
        try:
            job_uuid = uuid.UUID(str(job_id))
        except (TypeError, ValueError, AttributeError):
            raise ModelRegistryError("MODEL_SOURCE_UNTRUSTED") from None
        job = db.query(TrainingJob).filter(
            TrainingJob.id == job_uuid,
            TrainingJob.project_id == model.project_id,
            TrainingJob.model_artifact_id == artifact.id,
            TrainingJob.model_library_id == library.id,
            TrainingJob.status == "completed",
        ).first()
        if job is None or library.status != "completed" or library.format != "joblib":
            raise ModelRegistryError("MODEL_SOURCE_UNTRUSTED")

        onnx_artifact = None
        with tempfile.TemporaryDirectory(prefix="registry-conversion-") as temporary:
            destination = Path(temporary) / f"{model.id}.onnx"
            with self.artifact_service.materialize(
                artifact.id,
                model.project_id,
                expected_type="model",
            ) as source:
                result = self.converter(
                    source,
                    destination,
                    timeout_seconds=self.conversion_timeout_seconds,
                )
            onnx_artifact = self.artifact_service.create_from_file(
                model.project_id,
                destination,
                f"{model.name}-v{self._next_version_number(db, model.id)}.onnx",
                "model",
                metadata={
                    "source": "model_registry_conversion",
                    "source_artifact_id": str(artifact.id),
                    "source_model_library_id": str(library.id),
                    "sha256": result.sha256,
                },
                commit=False,
            )
            version = ModelVersion(
                registered_model_id=model.id,
                version_number=self._next_version_number(db, model.id),
                source_kind="platform_joblib",
                source_model_library_id=library.id,
                source_artifact_id=artifact.id,
                onnx_artifact_id=onnx_artifact.id,
                framework=library.framework or "",
                algorithm=library.backbone or "",
                feature_schema=deepcopy(result.feature_schema),
                output_schema=deepcopy(result.output_schema),
                metrics=deepcopy(library.metrics or {}),
                conversion_metadata=self._conversion_metadata(result),
                approval_status="pending",
                created_by_id=actor_id,
            )
            db.add(version)
            try:
                if commit:
                    db.commit()
                    db.refresh(version)
                else:
                    db.flush()
            except Exception:
                db.rollback()
                self.artifact_service.storage.delete(onnx_artifact.storage_uri)
                raise
        return version

    def register_onnx_version(
        self,
        db,
        *,
        model_id,
        source_artifact_id,
        actor_id,
        feature_schema,
        output_schema,
        commit: bool = True,
    ) -> ModelVersion:
        model = self._model(db, model_id)
        artifact = self.artifact_service.resolve(
            source_artifact_id,
            model.project_id,
            expected_type="model",
        )
        if artifact.format != "onnx":
            raise ModelRegistryError("MODEL_SOURCE_UNSUPPORTED")
        with self.artifact_service.materialize(
            artifact.id,
            model.project_id,
            expected_type="model",
        ) as source:
            result = self.validator(source, feature_schema, output_schema)
        version = ModelVersion(
            registered_model_id=model.id,
            version_number=self._next_version_number(db, model.id),
            source_kind="onnx_artifact",
            source_model_library_id=None,
            source_artifact_id=artifact.id,
            onnx_artifact_id=artifact.id,
            framework="onnx",
            algorithm="",
            feature_schema=deepcopy(result.feature_schema),
            output_schema=deepcopy(result.output_schema),
            metrics={},
            conversion_metadata=self._conversion_metadata(result),
            approval_status="pending",
            created_by_id=actor_id,
        )
        db.add(version)
        if commit:
            db.commit()
            db.refresh(version)
        else:
            db.flush()
        return version

    @staticmethod
    def _version(db, version_id) -> ModelVersion:
        try:
            version_uuid = uuid.UUID(str(version_id))
        except (TypeError, ValueError, AttributeError):
            raise ModelRegistryError("MODEL_VERSION_NOT_FOUND") from None
        version = db.query(ModelVersion).filter(
            ModelVersion.id == version_uuid,
        ).with_for_update().first()
        if version is None:
            raise ModelRegistryError("MODEL_VERSION_NOT_FOUND")
        return version

    def approve(self, db, version_id, actor_id, comment="", *, commit=True):
        version = self._version(db, version_id)
        if version.approval_status == "approved":
            return version
        if version.approval_status != "pending":
            raise ModelRegistryError("MODEL_VERSION_STATE_CONFLICT")
        version.approval_status = "approved"
        version.approval_comment = str(comment or "").strip()
        version.approved_by_id = actor_id
        version.approved_at = utcnow()
        self._finish(db, version, commit)
        return version

    def reject(self, db, version_id, actor_id, comment, *, commit=True):
        normalized = str(comment or "").strip()
        if not normalized:
            raise ModelRegistryError("MODEL_REJECTION_COMMENT_REQUIRED")
        version = self._version(db, version_id)
        if version.approval_status == "rejected":
            return version
        if version.approval_status != "pending":
            raise ModelRegistryError("MODEL_VERSION_STATE_CONFLICT")
        version.approval_status = "rejected"
        version.approval_comment = normalized
        version.approved_by_id = actor_id
        version.approved_at = utcnow()
        self._finish(db, version, commit)
        return version

    def archive(self, db, version_id, actor_id, comment="", *, commit=True):
        version = self._version(db, version_id)
        if version.approval_status == "archived":
            return version
        version.approval_status = "archived"
        version.approval_comment = str(comment or "").strip()
        version.approved_by_id = actor_id
        version.approved_at = utcnow()
        self._finish(db, version, commit)
        return version

    @staticmethod
    def _finish(db, version, commit):
        if commit:
            db.commit()
            db.refresh(version)
        else:
            db.flush()
