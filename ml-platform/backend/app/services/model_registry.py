"""Model registry version creation and approval lifecycle."""

from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import tempfile
import uuid

from sqlalchemy import func
from sqlalchemy.exc import IntegrityError

from app.models.artifact import Artifact
from app.models.model_library import ModelLibrary
from app.models.model_registry import ModelVersion, RegisteredModel
from app.models.training import TrainingJob
from app.services.artifact_service import ArtifactService
from app.services.model_cards import ModelCardService
from app.services.onnx_conversion import ConversionError, convert_platform_joblib, validate_onnx


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
        self.model_cards = ModelCardService()

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

    @staticmethod
    def _automl_result(job, algorithm_id: str) -> dict:
        metrics = dict(job.metrics or {})
        results = metrics.get("algorithm_results")
        if not isinstance(results, list):
            raise ModelRegistryError("AUTOML_RESULT_NOT_FOUND")
        for item in results:
            if isinstance(item, dict) and str(item.get("algorithm_id")) == str(algorithm_id):
                if item.get("status") != "completed" or not (
                    item.get("model_library_id") or item.get("model_artifact_id")
                ):
                    raise ModelRegistryError("AUTOML_RESULT_NOT_REGISTERABLE")
                return item
        raise ModelRegistryError("AUTOML_RESULT_NOT_FOUND")

    @staticmethod
    def _write_automl_registration(job, algorithm_id: str, registered_model_id, version_id) -> None:
        metrics = dict(job.metrics or {})
        for key in ("algorithm_results", "all_results"):
            values = metrics.get(key)
            if isinstance(values, list):
                for item in values:
                    if isinstance(item, dict) and str(item.get("algorithm_id")) == str(algorithm_id):
                        item["registered_model_id"] = str(registered_model_id)
                        item["model_version_id"] = str(version_id)
        best = metrics.get("best_model")
        if isinstance(best, dict) and str(best.get("algorithm_id")) == str(algorithm_id):
            best["registered_model_id"] = str(registered_model_id)
            best["model_version_id"] = str(version_id)
        job.metrics = metrics

    @staticmethod
    def _name_with_suffix(base: str, suffix: str) -> str:
        marker = f" [{suffix}]"
        return f"{base[:128 - len(marker)]}{marker}"

    def _create_automl_registered_model(
        self,
        db,
        *,
        job,
        library,
        actor_id,
        display_name: str,
    ) -> RegisteredModel:
        base_name = f"{job.name} - {display_name}"[:128]
        candidates = (
            base_name,
            self._name_with_suffix(base_name, str(job.id)[:8]),
            self._name_with_suffix(base_name, str(library.id)),
        )
        for candidate in dict.fromkeys(candidates):
            try:
                with db.begin_nested():
                    model = self.create_registered_model(
                        db,
                        project_id=job.project_id,
                        actor_id=actor_id,
                        name=candidate,
                        description=f"AutoML 模型结果：{display_name}",
                    )
                return model
            except IntegrityError:
                continue
        raise ModelRegistryError("MODEL_NAME_CONFLICT")

    def register_automl_result(
        self,
        db,
        *,
        job,
        algorithm_id: str,
        actor_id,
        commit: bool = True,
    ) -> tuple[RegisteredModel, ModelVersion, bool]:
        if job.status != "completed":
            raise ModelRegistryError("AUTOML_JOB_NOT_COMPLETED")
        result = self._automl_result(job, algorithm_id)
        library = None
        source_library_id = result.get("model_library_id")
        if source_library_id:
            try:
                source_uuid = uuid.UUID(str(source_library_id))
            except (TypeError, ValueError, AttributeError):
                raise ModelRegistryError("MODEL_SOURCE_NOT_FOUND") from None
            library = db.query(ModelLibrary).filter(
                ModelLibrary.id == source_uuid,
                ModelLibrary.project_id == job.project_id,
                ModelLibrary.training_job_id == job.id,
                ModelLibrary.status == "completed",
                ModelLibrary.format == "joblib",
            ).with_for_update().first()
            if library is None or library.model_artifact_id is None:
                raise ModelRegistryError("MODEL_SOURCE_NOT_FOUND")
        else:
            artifact_id = result.get("model_artifact_id")
            try:
                artifact_uuid = uuid.UUID(str(artifact_id))
            except (TypeError, ValueError, AttributeError):
                raise ModelRegistryError("MODEL_SOURCE_NOT_FOUND") from None
            artifact = db.query(Artifact).filter(
                Artifact.id == artifact_uuid,
                Artifact.project_id == job.project_id,
                Artifact.type == "model",
                Artifact.format == "joblib",
            ).first()
            metadata = dict(artifact.metadata_ or {}) if artifact is not None else {}
            if artifact is None or metadata.get("source") != "automl":
                raise ModelRegistryError("MODEL_SOURCE_NOT_FOUND")
            if str(metadata.get("training_job_id")) != str(job.id):
                raise ModelRegistryError("MODEL_SOURCE_UNTRUSTED")
            metadata_candidate = metadata.get("best_candidate") or metadata.get("best_algorithm")
            if metadata_candidate not in {None, str(algorithm_id)}:
                raise ModelRegistryError("MODEL_SOURCE_UNTRUSTED")
            library = db.query(ModelLibrary).filter(
                ModelLibrary.project_id == job.project_id,
                ModelLibrary.training_job_id == job.id,
                ModelLibrary.model_artifact_id == artifact.id,
                ModelLibrary.status == "completed",
                ModelLibrary.format == "joblib",
            ).with_for_update().first()
            if library is None:
                library = ModelLibrary(
                    name=str(result.get("name") or algorithm_id),
                    project_id=job.project_id,
                    owner_id=job.user_id,
                    status="completed",
                    framework="sklearn",
                    backbone=str(algorithm_id),
                    metrics=dict(result),
                    params=dict(result.get("params") or {}),
                    training_job_id=job.id,
                    dataset_artifact_id=job.dataset_artifact_id,
                    model_artifact_id=artifact.id,
                    file_size=artifact.file_size or 0,
                    format="joblib",
                    progress=100.0,
                )
                db.add(library)
                db.flush()
        existing = db.query(ModelVersion).filter(
            ModelVersion.source_model_library_id == library.id,
        ).order_by(ModelVersion.version_number.desc()).first()
        if existing is not None:
            self._write_automl_registration(job, algorithm_id, existing.registered_model_id, existing.id)
            if commit:
                db.commit()
            return existing.registered_model, existing, False
        display_name = str(result.get("name") or algorithm_id)
        model = self._create_automl_registered_model(
            db,
            job=job,
            library=library,
            actor_id=actor_id,
            display_name=display_name,
        )
        version = self.register_platform_version(
            db,
            model_id=model.id,
            source_model_library_id=library.id,
            actor_id=actor_id,
            commit=False,
        )
        self._write_automl_registration(job, algorithm_id, model.id, version.id)
        if commit:
            db.commit()
            db.refresh(model)
            db.refresh(version)
        return model, version, True

    @staticmethod
    def _candidate(job, candidate_id):
        for item in (job.metrics or {}).get("algorithm_results", ()):
            if isinstance(item, dict) and str(item.get("candidate_id") or item.get("algorithm_id")) == str(candidate_id):
                if item.get("status") != "completed" or not item.get("model_artifact_id"):
                    raise ModelRegistryError("CANDIDATE_NOT_REGISTERABLE")
                return item
        raise ModelRegistryError("CANDIDATE_NOT_FOUND")

    @staticmethod
    def _automl_output_contract(job, candidate_metadata: dict, targets: list[str]) -> dict:
        """Persist typed target fields so annotation never has to infer them."""
        source = candidate_metadata.get("target_schema") or job.target_schema or (job.metrics or {}).get("target_schema")
        if isinstance(source, dict) and source.get("name"):
            entries = [source]
        elif isinstance(source, list):
            entries = source
        elif isinstance(source, dict) and isinstance(source.get("columns"), list):
            entries = source["columns"]
        else:
            entries = []
        by_name = {
            str(item.get("name")): item
            for item in entries
            if isinstance(item, dict) and str(item.get("name") or "").strip()
        }
        columns = []
        for target in targets:
            entry = by_name.get(str(target))
            if entry is None or not str(entry.get("dtype") or "").strip():
                raise ModelRegistryError("MODEL_CONTRACT_INVALID")
            columns.append({
                "machine_key": str(target),
                "display_name": str(entry.get("display_name") or target),
                "dtype": str(entry["dtype"]),
                "task": str(entry.get("task") or candidate_metadata.get("task_type") or ""),
                "classes": list(entry.get("classes") or []),
            })
        return {
            "task_type": candidate_metadata.get("task_type"),
            "target_columns": list(targets),
            "columns": columns,
        }

    def register_automl_candidate(self, db, *, task_id, candidate_id, model_name, actor_id, idempotency_key):
        try:
            task_uuid = uuid.UUID(str(task_id))
        except (TypeError, ValueError, AttributeError):
            raise ModelRegistryError("AUTOML_JOB_NOT_FOUND") from None
        job = db.query(TrainingJob).filter(TrainingJob.id == task_uuid).with_for_update().first()
        if job is None:
            raise ModelRegistryError("AUTOML_JOB_NOT_FOUND")
        if job.status != "completed":
            raise ModelRegistryError("CANDIDATE_NOT_REGISTERABLE")
        if not isinstance(model_name, str) or not model_name.strip() or len(model_name.strip()) > 128:
            raise ModelRegistryError("MODEL_NAME_INVALID")
        normalized_name = model_name.strip()
        key = str(idempotency_key or "").strip()
        if not key or len(key) > 128:
            raise ModelRegistryError("IDEMPOTENCY_KEY_REQUIRED")
        existing = db.query(ModelVersion).filter(
            ModelVersion.registration_task_id == job.id,
            ModelVersion.registration_idempotency_key == key,
        ).first()
        if existing is not None:
            if (
                existing.registration_candidate_id == str(candidate_id)
                and existing.registered_model.name == normalized_name
            ):
                return existing, False
            raise ModelRegistryError("MODEL_REGISTRATION_IDEMPOTENCY_CONFLICT")
        candidate = self._candidate(job, candidate_id)
        try:
            artifact_uuid = uuid.UUID(str(candidate["model_artifact_id"]))
        except (TypeError, ValueError, AttributeError):
            raise ModelRegistryError("CANDIDATE_NOT_REGISTERABLE") from None
        artifact = db.query(Artifact).filter(
            Artifact.id == artifact_uuid,
            Artifact.project_id == job.project_id,
            Artifact.type == "model",
            Artifact.format == "joblib",
        ).first()
        metadata = dict(artifact.metadata_ or {}) if artifact is not None else {}
        if artifact is None or metadata.get("source") != "automl" or str(metadata.get("training_job_id")) != str(job.id):
            raise ModelRegistryError("CANDIDATE_NOT_REGISTERABLE")
        if not isinstance(metadata.get("sha256"), str) or len(metadata["sha256"]) != 64:
            raise ModelRegistryError("MODEL_CONTRACT_INVALID")
        try:
            with self.artifact_service.materialize(artifact.id, job.project_id, expected_type="model") as source:
                digest = hashlib.sha256(source.read_bytes()).hexdigest()
        except Exception:
            raise ModelRegistryError("CANDIDATE_NOT_REGISTERABLE") from None
        if digest != metadata["sha256"]:
            raise ModelRegistryError("MODEL_CONTRACT_INVALID")
        candidate_metadata = dict((job.metrics or {}).get("input_contract") or metadata.get("input_contract") or {})
        targets = list(candidate_metadata.get("target_columns") or [])
        inputs = list(candidate_metadata.get("input_columns") or [])
        if not targets or not inputs:
            raise ModelRegistryError("MODEL_CONTRACT_INVALID")
        output_contract = self._automl_output_contract(job, candidate_metadata, targets)
        contract_hash = hashlib.sha256(json.dumps(candidate_metadata, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        library = ModelLibrary(
            name=normalized_name,
            project_id=job.project_id,
            owner_id=actor_id,
            status="completed",
            framework="sklearn",
            backbone=str(candidate.get("algorithm_id") or candidate_id),
            metrics=dict((job.metrics or {}).get("per_target") or candidate.get("per_target") or {}),
            params=dict(candidate.get("params") or {}),
            training_job_id=job.id,
            dataset_artifact_id=job.dataset_artifact_id,
            model_artifact_id=artifact.id,
            file_size=artifact.file_size or 0,
            format="joblib",
            progress=100.0,
        )
        db.add(library)
        db.flush()
        model = self.create_registered_model(db, project_id=job.project_id, actor_id=actor_id, name=normalized_name, description="")
        version = self.register_platform_version(db, model_id=model.id, source_model_library_id=library.id, actor_id=actor_id, commit=False)
        version.registration_task_id = job.id
        version.registration_candidate_id = str(candidate_id)
        version.registration_idempotency_key = key
        version.lifecycle_state = "pending_review"
        version.output_schema = output_contract
        version.conversion_metadata = {**(version.conversion_metadata or {}), "input_contract_hash": contract_hash, "input_contract": candidate_metadata, "source_artifact_sha256": metadata["sha256"], "preprocessing": (job.metrics or {}).get("preprocessing") or job.preprocessing or {}, "feature_importance": (job.metrics or {}).get("feature_importance_report") or {}}
        db.flush()
        return version, True

    def list_registerable_candidates(self, db, task_id):
        try:
            task_uuid = uuid.UUID(str(task_id))
        except (TypeError, ValueError, AttributeError):
            raise ModelRegistryError("AUTOML_JOB_NOT_FOUND") from None
        job = db.query(TrainingJob).filter(TrainingJob.id == task_uuid).first()
        if job is None:
            raise ModelRegistryError("AUTOML_JOB_NOT_FOUND")
        if job.status != "completed":
            return []
        rows = []
        for item in (job.metrics or {}).get("algorithm_results", ()):
            if not isinstance(item, dict) or item.get("status") != "completed" or not item.get("model_artifact_id"):
                continue
            rows.append({
                "candidate_id": str(item.get("candidate_id") or item.get("algorithm_id")),
                "algorithm_id": item.get("algorithm_id"),
                "name": item.get("name") or item.get("algorithm_id"),
                "metrics": dict(item.get("aggregate") or item.get("metrics") or {}),
                "model_artifact_id": str(item.get("model_artifact_id")),
            })
        return rows

    def validate_model_contract(self, db, model_version_id):
        version = self._version(db, model_version_id)
        metadata = dict(version.conversion_metadata or {})
        return {"valid": bool(metadata.get("input_contract_hash")), "input_contract_hash": metadata.get("input_contract_hash"), "target_columns": (version.output_schema or {}).get("target_columns", [])}

    def transition_model_version(self, db, model_version_id, action, actor_id, *, commit=True):
        version = self._version(db, model_version_id)
        target = {"approve": "enabled", "disable": "disabled", "revoke": "revoked", "archive": "archived"}.get(action)
        if target is None:
            raise ModelRegistryError("MODEL_VERSION_STATE_CONFLICT")
        if action == "approve" and version.lifecycle_state not in {"pending_review", "disabled"}:
            raise ModelRegistryError("MODEL_VERSION_STATE_CONFLICT")
        version.lifecycle_state = target
        if action == "approve":
            version.approval_status = "approved"
        elif action in {"disable", "revoke", "archive"}:
            version.approval_status = "archived" if action == "archive" else version.approval_status
        if commit:
            db.commit(); db.refresh(version)
        else:
            db.flush()
        return version

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
        source_model_artifact_id=None,
    ) -> ModelVersion:
        model = self._model(db, model_id)
        library = None
        if source_model_library_id is not None:
            try:
                source_uuid = uuid.UUID(str(source_model_library_id))
            except (TypeError, ValueError, AttributeError):
                raise ModelRegistryError("MODEL_SOURCE_NOT_FOUND") from None
            library = db.query(ModelLibrary).filter(
                ModelLibrary.id == source_uuid,
                ModelLibrary.project_id == model.project_id,
            ).first()
        elif source_model_artifact_id is not None:
            try:
                artifact_uuid = uuid.UUID(str(source_model_artifact_id))
            except (TypeError, ValueError, AttributeError):
                raise ModelRegistryError("MODEL_SOURCE_NOT_FOUND") from None
            artifact = db.query(Artifact).filter(
                Artifact.id == artifact_uuid,
                Artifact.project_id == model.project_id,
                Artifact.type == "model",
                Artifact.format == "joblib",
            ).first()
            if artifact is not None:
                metadata = dict(artifact.metadata_ or {})
                job_id = metadata.get("training_job_id")
                try:
                    job_uuid = uuid.UUID(str(job_id))
                except (TypeError, ValueError, AttributeError):
                    raise ModelRegistryError("MODEL_SOURCE_UNTRUSTED") from None
                job = db.query(TrainingJob).filter(
                    TrainingJob.id == job_uuid,
                    TrainingJob.project_id == model.project_id,
                    TrainingJob.status == "completed",
                ).first()
                if job is None or metadata.get("source") != "automl":
                    raise ModelRegistryError("MODEL_SOURCE_UNTRUSTED")
                library = db.query(ModelLibrary).filter(
                    ModelLibrary.project_id == model.project_id,
                    ModelLibrary.training_job_id == job.id,
                    ModelLibrary.model_artifact_id == artifact.id,
                ).first()
                if library is None:
                    library = ModelLibrary(
                        name=artifact.name,
                        project_id=model.project_id,
                        owner_id=actor_id,
                        status="completed",
                        framework="sklearn",
                        backbone=str(metadata.get("best_candidate") or "automl"),
                        metrics={},
                        params={},
                        training_job_id=job.id,
                        dataset_artifact_id=job.dataset_artifact_id,
                        model_artifact_id=artifact.id,
                        file_size=artifact.file_size or 0,
                        format="joblib",
                        progress=100.0,
                    )
                    db.add(library)
                    db.flush()
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
            TrainingJob.status == "completed",
        ).first()
        if job is None or library.status != "completed" or library.format != "joblib":
            raise ModelRegistryError("MODEL_SOURCE_UNTRUSTED")
        if metadata.get("source") == "automl":
            algorithm_id = str(
                metadata.get("best_candidate")
                or metadata.get("best_algorithm")
                or metadata.get("candidate_id")
                or ""
            )
            results = (job.metrics or {}).get("algorithm_results")
            trusted = isinstance(results, list) and any(
                isinstance(item, dict)
                and str(item.get("algorithm_id")) == algorithm_id
                and (
                    str(item.get("model_library_id")) == str(library.id)
                    or str(item.get("model_artifact_id")) == str(artifact.id)
                )
                and item.get("status") == "completed"
                for item in results
            )
        else:
            trusted = job.model_artifact_id == artifact.id and job.model_library_id == library.id
        if not trusted:
            raise ModelRegistryError("MODEL_SOURCE_UNTRUSTED")

        onnx_artifact = None
        with tempfile.TemporaryDirectory(prefix="registry-conversion-") as temporary:
            destination = Path(temporary) / f"{model.id}.onnx"
            with self.artifact_service.materialize(
                artifact.id,
                model.project_id,
                expected_type="model",
            ) as source:
                try:
                    result = self.converter(
                        source,
                        destination,
                        timeout_seconds=self.conversion_timeout_seconds,
                    )
                except ConversionError as error:
                    raise ModelRegistryError(error.code) from None
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
            db.flush()
            self.model_cards.ensure_for_version(db, version)
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
        db.flush()
        self.model_cards.ensure_for_version(db, version)
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
            # Legacy approvals predate lifecycle_state; heal rows still sitting
            # in pending_review so the enabled gate (automatic annotation,
            # deployments) recognizes them. Never touch disabled/revoked rows.
            if version.lifecycle_state in (None, "pending_review"):
                version.lifecycle_state = "enabled"
                self._finish(db, version, commit)
            return version
        if version.approval_status != "pending":
            raise ModelRegistryError("MODEL_VERSION_STATE_CONFLICT")
        version.approval_status = "approved"
        version.lifecycle_state = "enabled"
        version.approval_comment = str(comment or "").strip()
        version.approved_by_id = actor_id
        version.approved_at = utcnow()
        self.model_cards.ensure_for_version(db, version)
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
        self.model_cards.ensure_for_version(db, version)
        self._finish(db, version, commit)
        return version

    def archive(self, db, version_id, actor_id, comment="", *, commit=True):
        version = self._version(db, version_id)
        if version.approval_status == "archived":
            if version.lifecycle_state in (None, "pending_review"):
                version.lifecycle_state = "archived"
                self._finish(db, version, commit)
            return version
        version.approval_status = "archived"
        version.lifecycle_state = "archived"
        version.approval_comment = str(comment or "").strip()
        version.approved_by_id = actor_id
        version.approved_at = utcnow()
        self.model_cards.ensure_for_version(db, version)
        self._finish(db, version, commit)
        return version

    @staticmethod
    def _finish(db, version, commit):
        if commit:
            db.commit()
            db.refresh(version)
        else:
            db.flush()
