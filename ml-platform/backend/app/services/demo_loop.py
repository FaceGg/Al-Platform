"""Closed-loop demo service: inference → error dataset → alert → review → retrain → swap.

Route A of the demo design: predictions run against the deployment's current
model version artifact in-process, error rows flow back into a dataset
artifact that shows up in data management, thresholds raise in-app alerts,
alerts can open a review annotation task, and accumulated data triggers an
AutoML job whose best candidate replaces the deployment model.
"""

from __future__ import annotations

import hashlib
import io
import json
import math
import tempfile
import threading
import uuid
from datetime import datetime
from functools import lru_cache
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

from app.config import settings
from app.database import SessionLocal
from app.models.artifact import Artifact
from app.models.data_version import DatasetSample, DatasetSchemaColumn
from app.models.demo_loop import DemoLoopConfig, DemoLoopEvent
from app.models.experiment import Experiment, ExperimentAutoMLBinding
from app.models.model_registry import InferenceDeployment, ModelVersion
from app.models.notifications import InAppNotification
from app.models.platform_models import GenericAnnotationTask
from app.models.project import Project
from app.models.training import TrainingJob
from app.models.user import User
from app.services.annotation_concurrency import AssignmentError, create_assignments
from app.services.annotation_scope import persist_scope_entries, scope_descriptor, scope_digest
from app.services.artifact_service import build_artifact_service
from app.services.automl_catalog import AUTOML_FAMILY_IDS, resolve_algorithm_families
from app.services.automl_execution import normalize_evaluation_config, resolve_automl_feature_columns
from app.services.automl_search import normalize_search_controls, validate_target_columns
from app.services.inference_deployment import InferenceDeploymentError, InferenceDeploymentService
from app.services.inference_rollout import WeightedTargetRouter
from app.services.inference_runtime_client import InferenceRuntimeClient
from app.services.label_schema import bind_label_schema_to_task, create_label_schema, label_schema_snapshot
from app.services.model_registry import ModelRegistryService, ModelRegistryError
from app.services.spot_weld_features import (
    REPORT_TABLE_FIELDS,
    WAVEFORM_FIELDS,
    build_feature_frame,
)


class DemoLoopError(ValueError):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


_LOCKS_GUARD = threading.Lock()
_LOCKS: dict[str, threading.Lock] = {}


def _lock_for(key: str) -> threading.Lock:
    with _LOCKS_GUARD:
        lock = _LOCKS.get(key)
        if lock is None:
            lock = threading.Lock()
            _LOCKS[key] = lock
        return lock


def _json_value(value):
    if value is None or value is pd.NaT:
        return None
    if isinstance(value, (pd.Timestamp, datetime)):
        return value.isoformat()
    if isinstance(value, np.generic):
        return _json_value(value.item())
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    return value


def _automl_dispatcher():
    if getattr(settings, "task_backend", "local") == "celery":
        # CeleryTrainingDispatcher lives in the training API module; the celery
        # task itself lives in app.tasks.training_tasks.
        from app.api.training import CeleryTrainingDispatcher
        from app.tasks.training_tasks import execute_automl_task

        return CeleryTrainingDispatcher(execute_automl_task)
    from app.tasks.training_tasks import LocalTrainingDispatcher, execute_local_automl_task

    return LocalTrainingDispatcher(execute_local_automl_task)


@lru_cache(maxsize=1)
def _deployment_service() -> InferenceDeploymentService | None:
    """Production-identical runtime client, cached per backend process."""
    secret = settings.resolved_inference_internal_secret
    if not settings.inference_runtime_url or secret is None:
        return None
    return InferenceDeploymentService(
        InferenceRuntimeClient(
            settings.inference_runtime_url,
            secret.get_secret_value(),
            load_timeout_seconds=settings.inference_load_timeout_seconds,
            predict_timeout_seconds=settings.inference_predict_timeout_seconds,
        ),
        SessionLocal,
    )


def _feature_names(version: ModelVersion) -> list[str]:
    names: list[str] = []
    for item in version.feature_schema or []:
        if isinstance(item, dict) and item.get("name") is not None:
            names.append(str(item["name"]))
        elif isinstance(item, str):
            names.append(item)
    return names


def _scalar_label(value):
    value = _json_value(value)
    if isinstance(value, list):
        value = value[0] if value else None
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return value


class DemoLoopService:
    """One service instance per request/session; concurrency handled per config."""

    def __init__(self, db):
        self.db = db

    # ------------------------------------------------------------------ helpers

    def _emit(self, config: DemoLoopConfig, event_type: str, message: str,
              *, severity: str = "info", payload: dict | None = None) -> DemoLoopEvent:
        event = DemoLoopEvent(
            config_id=config.id,
            event_type=event_type,
            severity=severity,
            message=message,
            payload=_json_value(payload or {}) or {},
        )
        self.db.add(event)
        return event

    def _artifact_service(self):
        return build_artifact_service(self.db)

    def _deployment(self, config: DemoLoopConfig) -> InferenceDeployment:
        if config.deployment_id is None:
            raise DemoLoopError("DEMO_LOOP_DEPLOYMENT_MISSING", "Loop has no deployment configured")
        deployment = self.db.query(InferenceDeployment).filter(
            InferenceDeployment.id == config.deployment_id,
        ).first()
        if deployment is None:
            raise DemoLoopError("DEMO_LOOP_DEPLOYMENT_MISSING", "Configured deployment no longer exists")
        return deployment

    def _current_model_version(self, deployment: InferenceDeployment) -> ModelVersion:
        if deployment.model_version_id is None:
            raise DemoLoopError("DEMO_LOOP_MODEL_MISSING", "Deployment has no model version")
        version = self.db.query(ModelVersion).filter(
            ModelVersion.id == deployment.model_version_id,
        ).first()
        if version is None:
            raise DemoLoopError("DEMO_LOOP_MODEL_MISSING", "Deployment model version no longer exists")
        return version

    def _load_model(self, version: ModelVersion):
        if version.source_artifact_id is None:
            raise DemoLoopError("DEMO_LOOP_MODEL_ARTIFACT_MISSING", "Model version has no artifact")
        artifact = self.db.query(Artifact).filter(Artifact.id == version.source_artifact_id).first()
        if artifact is None:
            raise DemoLoopError("DEMO_LOOP_MODEL_ARTIFACT_MISSING", "Model artifact no longer exists")
        service = self._artifact_service()
        with service.storage.open(artifact.storage_uri) as handle:
            payload = handle.read()
        loaded = joblib.load(io.BytesIO(payload))
        # Model-library/AutoML artifacts are often packaged as dicts; unwrap
        # the estimator instead of failing with AttributeError on .predict.
        if isinstance(loaded, dict):
            for key in ("model", "estimator", "clf", "pipeline", "best_model"):
                candidate = loaded.get(key)
                if candidate is not None and hasattr(candidate, "predict"):
                    return candidate
            raise DemoLoopError(
                "DEMO_LOOP_MODEL_ARTIFACT_INVALID",
                "模型制品是打包结构且不含可直接推理的估计器；请通过推理部署的运行时调用（或使用 ONNX 版本）",
            )
        return loaded

    # ------------------------------------------------------------------ config

    def get_config(self, project_id):
        return self.db.query(DemoLoopConfig).filter(
            DemoLoopConfig.project_id == project_id,
        ).order_by(DemoLoopConfig.created_at.asc()).first()

    def save_config(self, project_id, actor_id, data: dict) -> DemoLoopConfig:
        config = self.get_config(project_id)
        if config is None:
            config = DemoLoopConfig(project_id=project_id, created_by_id=actor_id)
            self.db.add(config)
        deployment_id = data.get("deployment_id")
        if deployment_id:
            try:
                deployment_uuid = uuid.UUID(str(deployment_id))
            except (TypeError, ValueError, AttributeError):
                raise DemoLoopError("DEMO_LOOP_CONFIG_INVALID", "deployment_id must be a UUID")
            deployment = self.db.query(InferenceDeployment).filter(
                InferenceDeployment.id == deployment_uuid,
                InferenceDeployment.project_id == project_id,
            ).first()
            if deployment is None:
                raise DemoLoopError("DEMO_LOOP_DEPLOYMENT_NOT_FOUND", "Deployment not found in this project")
            config.deployment_id = deployment.id
        error_classes = data.get("error_classes")
        if error_classes is not None:
            if not isinstance(error_classes, list) or not all(isinstance(item, str) for item in error_classes):
                raise DemoLoopError("DEMO_LOOP_CONFIG_INVALID", "error_classes must be a list of strings")
            if not error_classes:
                raise DemoLoopError("DEMO_LOOP_CONFIG_INVALID", "error_classes must not be empty")
            config.error_classes = error_classes
        if "name" in data and str(data.get("name") or "").strip():
            config.name = str(data["name"]).strip()[:128]
        if "preprocess_enabled" in data:
            config.preprocess_enabled = bool(data["preprocess_enabled"])
        if "alert_threshold_rows" in data:
            threshold = int(data["alert_threshold_rows"] or 1)
            if threshold < 1:
                raise DemoLoopError("DEMO_LOOP_CONFIG_INVALID", "alert_threshold_rows must be >= 1")
            config.alert_threshold_rows = threshold
        if "require_review" in data:
            config.require_review = bool(data["require_review"])
        if "review_annotator_ids" in data:
            annotators = data.get("review_annotator_ids") or []
            if not isinstance(annotators, list):
                raise DemoLoopError("DEMO_LOOP_CONFIG_INVALID", "review_annotator_ids must be a list")
            config.review_annotator_ids = [str(item) for item in annotators]
        if "retrain_enabled" in data:
            config.retrain_enabled = bool(data["retrain_enabled"])
        if "retrain_threshold_rows" in data:
            config.retrain_threshold_rows = max(0, int(data["retrain_threshold_rows"] or 0))
        if "retrain_max_trials" in data:
            config.retrain_max_trials = max(5, int(data["retrain_max_trials"] or 10))
        if "retrain_target_column" in data:
            config.retrain_target_column = str(data["retrain_target_column"] or "").strip()[:128]
        if "retrain_dataset_artifact_id" in data:
            raw = data.get("retrain_dataset_artifact_id")
            if raw:
                try:
                    artifact_uuid = uuid.UUID(str(raw))
                except (TypeError, ValueError, AttributeError):
                    raise DemoLoopError("DEMO_LOOP_CONFIG_INVALID", "retrain_dataset_artifact_id must be a UUID")
                artifact = self.db.query(Artifact).filter(
                    Artifact.id == artifact_uuid,
                    Artifact.project_id == project_id,
                    Artifact.type == "dataset",
                ).first()
                if artifact is None:
                    raise DemoLoopError("DEMO_LOOP_CONFIG_INVALID", "Retrain dataset not found in this project")
                config.retrain_dataset_artifact_id = artifact.id
            else:
                config.retrain_dataset_artifact_id = None
        self.db.commit()
        self.db.refresh(config)
        return config

    # ------------------------------------------------------------------ predict

    def predict(self, config: DemoLoopConfig, record: dict, actor_id) -> dict:
        if not isinstance(record, dict) or not record:
            raise DemoLoopError("DEMO_LOOP_RECORD_INVALID", "record must be a non-empty object")
        deployment = self._deployment(config)
        version = self._current_model_version(deployment)

        predicted, confidence = self._run_prediction(config, deployment, version, record)

        is_error = str(predicted) in (config.error_classes or [])
        self._emit(
            config,
            "error_row" if is_error else "row_predicted",
            f"预测类别 {predicted}" + ("（命中报错类别，回流数据集）" if is_error else ""),
            severity="warning" if is_error else "info",
            payload={"prediction": str(predicted), "confidence": confidence},
        )

        appended = False
        if is_error:
            self._append_error_rows(config, [dict(record, **{
                "prediction": str(predicted),
                "confidence": confidence,
            })], actor_id)
            appended = True
            self._after_error_append(config, str(predicted), actor_id)

        self.db.commit()
        return {
            "prediction": str(predicted),
            "confidence": confidence,
            "model_version_id": str(version.id),
            "error_matched": is_error,
            "appended": appended,
            "error_count": int(config.error_count),
            "alert_count": int(config.alert_count),
            "retrain_status": config.retrain_status,
        }

    def _run_prediction(self, config: DemoLoopConfig, deployment: InferenceDeployment, version: ModelVersion, record: dict):
        """Runtime first (production-identical ONNX serving), in-process fallback."""
        names = _feature_names(version)
        if names:
            missing = [name for name in names if name not in record]
            if missing:
                record = self._engineer_missing_features(config, record, missing, names)
        service = _deployment_service()
        if service is not None:
            try:
                routed = WeightedTargetRouter().select_active(deployment, uuid.uuid4().hex)
                if names:
                    numeric = {}
                    for name in names:
                        value = record[name]
                        if isinstance(value, bool) or not isinstance(value, (int, float)):
                            try:
                                value = float(value)
                            except (TypeError, ValueError) as error:
                                raise DemoLoopError(
                                    "DEMO_LOOP_RECORD_INVALID",
                                    f"特征列 {name} 的值不是数值：{value!r}",
                                ) from error
                        numeric[name] = value
                    records = [numeric]
                else:
                    records = [dict(record)]
                result = service.runtime.predict(
                    f"{routed.revision_id}:{routed.model_version_id}", records,
                )
                predictions = result.get("predictions") or []
                if not predictions:
                    raise DemoLoopError("DEMO_LOOP_PREDICT_EMPTY", "推理运行时未返回预测结果")
                predicted = _scalar_label(predictions[0])
                probabilities = result.get("probabilities") or []
                confidence = None
                if probabilities:
                    row = _json_value(probabilities[0])
                    if isinstance(row, list) and row:
                        confidence = round(float(max(row)), 4)
                return predicted, confidence
            except DemoLoopError:
                raise
            except (InferenceDeploymentError, RuntimeError) as error:
                code = getattr(error, "code", "INFERENCE_RUNTIME_UNAVAILABLE")
                if code == "INFERENCE_SCHEMA_MISMATCH":
                    raise DemoLoopError(
                        "DEMO_LOOP_RECORD_INVALID",
                        "数据与模型特征列不匹配（需要与训练特征完全一致的数值列）",
                    ) from error
        return self._predict_in_process(
            version, record, names,
            preprocess_enabled=bool(getattr(config, "preprocess_enabled", False)),
        )

    def _engineer_missing_features(
        self, config: DemoLoopConfig, record: dict, missing: list[str], names: list[str],
    ) -> dict:
        """Derive the model's engineered features from raw report data.

        Uses the platform's spot-weld feature engineering (report table fields
        + four waveform channels → fixed 73-feature schema) when the uploaded
        row carries the raw source columns.
        """
        if not config.preprocess_enabled:
            raise DemoLoopError(
                "DEMO_LOOP_RECORD_INVALID",
                f"数据缺少模型特征列：{', '.join(missing[:10])}。"
                "若上传的是原始点焊报告数据（含波形列 cvei/cvev/cver/cvep），"
                "请打开「自动特征工程」开关后重试；否则请上传已做过特征工程的完整特征数据集。",
            )
        try:
            features, _schema, _stats = build_feature_frame(pd.DataFrame([record]))
        except Exception as error:
            raise DemoLoopError(
                "DEMO_LOOP_RECORD_INVALID",
                "自动特征工程失败：请确认上传的行为原始点焊报告数据，"
                f"需包含报告字段 {', '.join(REPORT_TABLE_FIELDS)} 与波形列 {', '.join(WAVEFORM_FIELDS)}"
                f"（缺失原因：{error}）",
            ) from error
        if features.empty:
            raise DemoLoopError(
                "DEMO_LOOP_RECORD_INVALID",
                "自动特征工程未产出任何特征行，请检查上传数据格式",
            )
        engineered = {
            str(key): _json_value(value)
            for key, value in features.iloc[0].to_dict().items()
        }
        merged = {**record, **engineered}
        still_missing = [name for name in names if name not in merged]
        if still_missing:
            raise DemoLoopError(
                "DEMO_LOOP_RECORD_INVALID",
                f"自动特征工程后仍缺少模型特征列：{', '.join(still_missing[:10])}",
            )
        return merged

    def _predict_in_process(self, version: ModelVersion, record: dict, names: list[str], *, preprocess_enabled: bool):
        model = self._load_model(version)
        frame = pd.DataFrame([record])
        columns = names or self._feature_columns(model, version)
        if columns:
            frame = frame.reindex(columns=list(columns))
        if preprocess_enabled:
            frame = self._basic_preprocess(frame)
        try:
            prediction = model.predict(frame)
        except Exception as error:
            raise DemoLoopError(
                "DEMO_LOOP_PREDICT_FAILED",
                f"进程内推理失败（预处理开关：{'开' if preprocess_enabled else '关'}）：{error}",
            ) from error
        predicted = _scalar_label(prediction[0])
        confidence = None
        if hasattr(model, "predict_proba"):
            try:
                proba = model.predict_proba(frame)
                confidence = round(float(np.asarray(proba)[0].max()), 4)
            except Exception:
                confidence = None
        return predicted, confidence

    def _feature_columns(self, model, version: ModelVersion) -> list[str]:
        columns = getattr(model, "feature_names_in_", None)
        if columns is not None and len(columns):
            return [str(item) for item in columns]
        schema = version.feature_schema or []
        if isinstance(schema, list) and schema and all(isinstance(item, str) for item in schema):
            return list(schema)
        return []

    @staticmethod
    def _basic_preprocess(frame: pd.DataFrame) -> pd.DataFrame:
        frame = frame.copy()
        for column in frame.columns:
            series = frame[column]
            if pd.api.types.is_numeric_dtype(series):
                frame[column] = series.fillna(0)
            else:
                frame[column] = series.astype("object").where(series.notna(), "")
        return frame

    # ------------------------------------------------------------- error dataset

    def _error_artifact(self, config: DemoLoopConfig, columns: list[str]) -> Artifact:
        if config.error_artifact_id:
            artifact = self.db.query(Artifact).filter(
                Artifact.id == config.error_artifact_id,
                Artifact.project_id == config.project_id,
            ).first()
            if artifact is not None:
                return artifact
        name = f"{config.name}-报错数据"
        exists = self.db.query(Artifact.id).filter(
            Artifact.project_id == config.project_id,
            Artifact.name == name,
            Artifact.type == "dataset",
        ).first()
        if exists is not None:
            name = f"{name}-{uuid.uuid4().hex[:6]}"
        frame = pd.DataFrame(columns=columns or ["record"])
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "error_rows.csv"
            frame.to_csv(path, index=False)
            artifact = self._artifact_service().create_from_file(
                config.project_id, path, name, "dataset",
                metadata={
                    "source": "demo_loop",
                    "row_count": 0,
                    "column_count": len(frame.columns),
                    "schema": [
                        {"name": str(column), "dtype": "object", "null_count": 0}
                        for column in frame.columns
                    ],
                },
            )
        config.error_artifact_id = artifact.id
        self._emit(config, "error_dataset_created", f"已创建报错数据集 {artifact.name}",
                   payload={"artifact_id": str(artifact.id)})
        return artifact

    def _append_error_rows(self, config: DemoLoopConfig, rows: list[dict], actor_id) -> None:
        columns = sorted({key for row in rows for key in row})
        with _lock_for(str(config.id)):
            artifact = self._error_artifact(config, columns)
            service = self._artifact_service()
            old_uri = artifact.storage_uri
            with service.storage.materialize(artifact.storage_uri) as path:
                frame = pd.read_csv(path)
            for row in rows:
                frame.loc[len(frame)] = [
                    _json_value(row.get(column)) for column in frame.columns
                ]
            with tempfile.TemporaryDirectory() as tmp:
                out = Path(tmp) / "error_rows.csv"
                frame.to_csv(out, index=False)
                stored = service.storage.put(
                    out,
                    project_id=str(config.project_id),
                    artifact_id=str(artifact.id),
                    filename="error_rows.csv",
                )
            schema = [
                {"name": str(column), "dtype": str(frame[column].dtype),
                 "null_count": int(frame[column].isna().sum())}
                for column in frame.columns
            ]
            artifact.storage_uri = stored.uri
            artifact.file_size = stored.size
            artifact.metadata_ = {
                **(artifact.metadata_ or {}),
                "sha256": stored.sha256,
                "source": "demo_loop",
                "row_count": int(len(frame)),
                "column_count": int(len(frame.columns)),
                "schema": schema,
            }
            self.db.commit()
            if old_uri and old_uri != stored.uri:
                try:
                    service.storage.delete(old_uri)
                except Exception:
                    pass
        self._emit(config, "error_appended", f"错误数据已追加（当前 {len(frame)} 行）",
                   payload={"rows": len(rows), "total": int(len(frame))})

    # ---------------------------------------------------------------- thresholds

    def _after_error_append(self, config: DemoLoopConfig, predicted: str, actor_id) -> None:
        config.error_count = int(config.error_count or 0) + 1
        threshold = max(1, int(config.alert_threshold_rows or 1))
        if config.error_count % threshold == 0:
            config.alert_count = int(config.alert_count or 0) + 1
            self._emit(
                config, "alert_triggered",
                f"报错数据达到 {config.error_count} 行，触发第 {config.alert_count} 次管理员告警",
                severity="critical",
                payload={"error_count": config.error_count, "alert_count": config.alert_count},
            )
            self._notify_admins(config, predicted)
            if config.require_review:
                if config.review_annotator_ids:
                    try:
                        self._create_review_task(config, actor_id)
                    except (AssignmentError, DemoLoopError, ValueError) as error:
                        self._emit(config, "review_task_failed", f"创建人工审核任务失败：{error}",
                                   severity="warning")
                else:
                    self._emit(config, "review_skipped", "已开启人工审核但未配置标注员", severity="warning")
        if (
            config.retrain_enabled
            and int(config.retrain_threshold_rows or 0) > 0
            and config.error_count >= int(config.retrain_threshold_rows)
            and config.retrain_status in {"idle", "failed", ""}
            and config.retrain_job_id is None
        ):
            self._trigger_retrain(config, actor_id)

    def _notify_admins(self, config: DemoLoopConfig, predicted: str) -> None:
        recipients: set = set()
        project = self.db.query(Project).filter(Project.id == config.project_id).first()
        if project is not None and project.owner_id:
            recipients.add(uuid.UUID(str(project.owner_id)))
        for row in self.db.query(User.id).filter(User.role == "admin").all():
            recipients.add(row.id)
        for recipient in recipients:
            self.db.add(InAppNotification(
                recipient_user_id=recipient,
                project_id=config.project_id,
                event_id=uuid.uuid4(),
                event_type="demo_loop.alert",
                deduplication_key=f"dl-{config.id.hex[:12]}-{uuid.uuid4().hex[:12]}",
                severity="warning",
                title=f"【{config.name}】报错数据告警",
                body=(
                    f"推理命中的报错类别 {predicted} 已累计 {config.error_count} 行，"
                    f"达到告警阈值 {config.alert_threshold_rows} 行，请关注数据回流与模型质量。"
                ),
                payload={"config_id": str(config.id), "error_count": config.error_count},
            ))

    # ------------------------------------------------------------- review task

    def _create_review_task(self, config: DemoLoopConfig, actor_id) -> None:
        artifact = self.db.query(Artifact).filter(
            Artifact.id == config.error_artifact_id,
        ).first()
        if artifact is None:
            raise DemoLoopError("DEMO_LOOP_ERROR_DATASET_MISSING", "Error dataset artifact missing")
        service = self._artifact_service()
        version = service.create_dataset_version_from_artifact(artifact, operator_id=actor_id)
        schema = create_label_schema(
            self.db,
            project_id=config.project_id,
            name=f"{config.name}-复核标签",
            columns=[{
                "machine_key": "review_label",
                "display_name": "复核标签",
                "value_type": "enum",
                "required": True,
                "enum_values": list(config.error_classes or []),
            }],
            commit=False,
        )
        source_columns = [
            {"name": column.name, "dtype": column.dtype, "nullable": column.nullable, "position": column.position}
            for column in sorted(
                self.db.query(DatasetSchemaColumn)
                .filter(DatasetSchemaColumn.dataset_version_id == version.id).all(),
                key=lambda item: item.position,
            )
        ]
        entries = [
            (str(sample.sample_id), int(sample.row_index))
            for sample in self.db.query(DatasetSample)
            .filter(DatasetSample.dataset_version_id == version.id)
            .order_by(DatasetSample.row_index.asc(), DatasetSample.id.asc())
            .yield_per(500)
        ]
        count, scope_hash = scope_digest(entries)
        snapshot = {
            "dataset_version": {
                "id": str(version.id),
                "version": version.version,
                "content_hash": version.content_hash,
                "schema_hash": version.schema_hash,
                "columns": source_columns,
            },
            "scope": scope_descriptor(count, scope_hash),
            "visible_columns": [column["name"] for column in (source_columns or [])],
            "label_schema": label_schema_snapshot(schema),
            "instructions": "闭环演示自动创建：请复核本行数据是否确实属于报错类别。",
            "completion_criteria": "",
            "configuration": {},
            "field_descriptions": {},
        }
        canonical = json.dumps(snapshot, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
        snapshot["config_hash"] = "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        task = GenericAnnotationTask(
            project_id=config.project_id,
            dataset_version_id=version.id,
            label_schema_id=schema.id,
            owner_id=actor_id,
            name=f"{config.name}-人工审核-{config.alert_count}",
            mode="manual",
            # Assignments require an assignable state; the demo flow skips the
            # manual draft→publish step and lands directly on awaiting_annotation.
            status="awaiting_annotation",
            sample_scope={"kind": "all"},
            label_snapshot=snapshot["label_schema"],
            task_snapshot=snapshot,
            idempotency_key=f"demo-loop-review-{config.id}-{config.alert_count}",
        )
        self.db.add(task)
        self.db.flush()
        persisted = persist_scope_entries(self.db, task.id, task.task_revision, entries)
        if persisted != count:
            raise DemoLoopError("DEMO_LOOP_REVIEW_SCOPE_MISMATCH", "Review scope persistence mismatch")
        bind_label_schema_to_task(self.db, task_id=task.id, schema=schema)
        create_assignments(
            self.db,
            task_id=task.id,
            # Config JSON stores strings; create_assignments compares against
            # UUID subject sets, so coerce before handing over.
            annotator_ids=[uuid.UUID(str(item)) for item in config.review_annotator_ids or []],
            sample_scope={"kind": "all"},
            due_at=None,
            actor=actor_id,
            idempotency_key=f"demo-loop-assign-{config.id}-{config.alert_count}",
        )
        config.review_task_id = task.id
        self.db.commit()
        self._emit(config, "review_task_created",
                   f"已创建人工审核任务并分配 {len(config.review_annotator_ids)} 名标注员",
                   payload={"task_id": str(task.id), "samples": count})

    # ------------------------------------------------------------------- retrain

    def _trigger_retrain(self, config: DemoLoopConfig, actor_id) -> None:
        try:
            self._trigger_retrain_inner(config, actor_id)
        except DemoLoopError as error:
            self.db.rollback()
            self._emit(config, "retrain_failed", f"自动建模触发失败：{error}", severity="warning")
            self.db.commit()
        except Exception as error:  # noqa: BLE001 - keep the loop alive
            self.db.rollback()
            self._emit(config, "retrain_failed", f"自动建模触发失败：{error}", severity="warning")
            self.db.commit()

    def _trigger_retrain_inner(self, config: DemoLoopConfig, actor_id) -> None:
        if not config.retrain_target_column:
            raise DemoLoopError("DEMO_LOOP_RETRAIN_TARGET_MISSING", "未配置重训目标列")
        if config.retrain_dataset_artifact_id is None:
            raise DemoLoopError("DEMO_LOOP_RETRAIN_DATASET_MISSING", "未配置重训数据集")
        service = self._artifact_service()
        dataset = service.resolve(config.retrain_dataset_artifact_id, config.project_id, expected_type="dataset")
        # One AutoML job per experiment (binding PK), so each retrain cycle
        # gets its own experiment named by cycle.
        experiment = self.db.query(Experiment).filter(
            Experiment.project_id == config.project_id,
            Experiment.name == f"{config.name}-自动建模-{config.error_count}",
        ).first()
        if experiment is None:
            experiment = Experiment(
                project_id=config.project_id,
                created_by=actor_id,
                name=f"{config.name}-自动建模-{config.error_count}",
                description="闭环演示自动创建的实验",
                # Unique placeholder; the real tracking id is registered right
                # below and the column is globally unique.
                mlflow_experiment_id=f"pending-{uuid.uuid4().hex[:24]}",
            )
            self.db.add(experiment)
            self.db.flush()
        if experiment.mlflow_experiment_id.startswith("pending-"):
            # Register the experiment with the real tracking backend so the
            # AutoML worker can start a run against it.
            from mlflow.tracking import MlflowClient

            from app.services.experiment_tracking import (
                MlflowExperimentTracking,
                resolve_tracking_configuration,
            )
            tracking_uri, artifact_root = resolve_tracking_configuration(settings)
            tracking = MlflowExperimentTracking(
                client=MlflowClient(tracking_uri=tracking_uri),
                artifact_root=artifact_root,
            )
            experiment.mlflow_experiment_id = tracking.ensure_experiment(
                f"project/{experiment.project_id}/{experiment.id}",
            )
            self.db.flush()

        with service.materialize(dataset.id, config.project_id, expected_type="dataset") as path:
            frame = pd.read_csv(path)
        target = config.retrain_target_column
        if target not in frame.columns:
            raise DemoLoopError("DEMO_LOOP_RETRAIN_TARGET_MISSING", f"目标列 {target} 不在重训数据集中")
        task_type = "classification"
        validate_target_columns(frame, task_type, [target])
        feature_columns = resolve_automl_feature_columns(
            frame, target, None, target_columns=[target],
        )
        families = resolve_algorithm_families(list(AUTOML_FAMILY_IDS))
        evaluation = normalize_evaluation_config(True, 3)
        controls = normalize_search_controls(strength="light", time_budget=600, class_weight=True)
        max_trials = max(int(config.retrain_max_trials or 10), len(families))
        fingerprint = hashlib.sha256(json.dumps({
            "config_id": str(config.id), "error_count": config.error_count,
            "dataset": str(dataset.id), "target": target,
        }, sort_keys=True).encode("utf-8")).hexdigest()
        job = TrainingJob(
            id=uuid.uuid4(),
            project_id=config.project_id,
            user_id=actor_id,
            experiment_id=experiment.id,
            name=f"{config.name}-自动建模-{config.error_count}",
            operator_id="automl",
            params={
                "target_column": target,
                "target_columns": [target],
                "input_columns": list(feature_columns),
                "task": task_type,
                "search_contract": "optuna_v1",
                "algorithm_ids": [family.id for family in families],
                "search_method": "bayesian",
                "max_trials": max_trials,
                **evaluation,
                "time_budget": controls["time_budget"],
                "search_strength": controls["strength"],
                "class_weight": controls["class_weight"],
            },
            dataset_artifact_id=dataset.id,
            dataset_path=service.storage_reference(dataset),
            status="pending",
            automl_contract={
                "task_type": task_type,
                "target_columns": [target],
                "cross_validation_folds": evaluation["cross_validation_folds"],
                "cv_strategy": "stratified",
                "random_seed": 42,
                "idempotency_fingerprint": fingerprint,
            },
            automl_idempotency_key=f"demo-loop-{config.id}-{fingerprint[:24]}",
        )
        self.db.add(job)
        self.db.add(ExperimentAutoMLBinding(experiment_id=experiment.id, job_id=job.id))
        self.db.flush()
        # Local dispatcher only registers on enqueue and needs start(task_id)
        # to spawn the worker thread; Celery's delay runs it inside enqueue.
        dispatcher = _automl_dispatcher()
        task_id = dispatcher.enqueue(job.id)
        if hasattr(dispatcher, "start"):
            dispatcher.start(task_id)
        config.retrain_job_id = job.id
        config.retrain_status = "queued"
        self.db.commit()
        self._emit(config, "retrain_triggered",
                   f"报错数据已达 {config.error_count} 行，自动建模任务已触发（{max_trials} 组试验）",
                   severity="warning",
                   payload={"job_id": str(job.id), "task_id": task_id})

    def refresh_retrain_status(self, config: DemoLoopConfig, actor_id) -> None:
        if config.retrain_status not in {"queued", "running"} or config.retrain_job_id is None:
            return
        job = self.db.query(TrainingJob).filter(TrainingJob.id == config.retrain_job_id).first()
        if job is None:
            config.retrain_status = "failed"
            self._emit(config, "retrain_failed", "自动建模任务记录丢失", severity="warning")
            self.db.commit()
            return
        # Persisted jobs start as "pending"; surface that to users as queued.
        mapped_status = {"pending": "queued"}.get(job.status, job.status)
        if mapped_status != config.retrain_status:
            config.retrain_status = mapped_status
            if mapped_status == "running":
                self._emit(config, "retrain_running", "自动建模任务执行中")
            elif mapped_status == "failed":
                self._emit(config, "retrain_failed",
                           f"自动建模失败：{job.error_message or job.error_code or '未知错误'}",
                           severity="critical")
        if job.status == "completed":
            self._swap_to_best_model(config, job, actor_id)
        self.db.commit()

    def _candidate_score(self, row: dict) -> float:
        metrics = row.get("metrics") or {}
        if isinstance(metrics, dict):
            for key in ("auc", "accuracy", "f1", "precision", "recall", "r2"):
                value = metrics.get(key)
                if isinstance(value, (int, float)):
                    return float(value)
            for value in metrics.values():
                if isinstance(value, (int, float)):
                    return float(value)
        return 0.0

    def _swap_to_best_model(self, config: DemoLoopConfig, job: TrainingJob, actor_id) -> None:
        if config.swapped_model_version_id:
            return
        registry = ModelRegistryService(artifact_service=build_artifact_service(self.db))
        candidates = registry.list_registerable_candidates(self.db, job.id)
        if not candidates:
            self._emit(config, "retrain_failed", "自动建模完成但没有可注册的候选模型", severity="warning")
            return
        best = max(candidates, key=self._candidate_score)
        candidate_id = best.get("candidate_id") or best.get("id")
        try:
            version, _created = registry.register_automl_candidate(
                self.db,
                task_id=job.id,
                candidate_id=candidate_id,
                model_name=f"{config.name}-自动模型",
                actor_id=actor_id,
                idempotency_key=f"demo-loop-{config.id}-{job.id}",
            )
            registry.transition_model_version(self.db, version.id, "approve", actor_id)
        except ModelRegistryError as error:
            self._emit(config, "swap_failed", f"最优模型注册失败：{error.code}", severity="critical")
            return
        previous_id = None
        deployment = self.db.query(InferenceDeployment).filter(
            InferenceDeployment.id == config.deployment_id,
        ).first() if config.deployment_id else None
        if deployment is not None:
            previous_id = str(deployment.model_version_id) if deployment.model_version_id else None
            deployment.model_version_id = version.id
        config.swapped_model_version_id = version.id
        self._emit(
            config, "model_swapped",
            f"自动建模完成，已将部署模型替换为最优候选（{best.get('name') or best.get('algorithm_id')}）",
            severity="critical",
            payload={
                "new_model_version_id": str(version.id),
                "previous_model_version_id": previous_id,
                "candidate": _json_value(best) or {},
            },
        )

    # -------------------------------------------------------------------- reset

    def reset(self, config: DemoLoopConfig, actor_id) -> None:
        with _lock_for(str(config.id)):
            config.error_count = 0
            config.alert_count = 0
            config.retrain_status = "idle"
            config.retrain_job_id = None
            self.db.query(DemoLoopEvent).filter(DemoLoopEvent.config_id == config.id).delete()
            self._emit(config, "loop_reset", "演示闭环状态已重置（配置与数据集保留）")
            self.db.commit()

    # -------------------------------------------------------------------- status

    def build_status(self, config: DemoLoopConfig) -> dict:
        events = self.db.query(DemoLoopEvent).filter(
            DemoLoopEvent.config_id == config.id,
        ).order_by(DemoLoopEvent.created_at.desc(), DemoLoopEvent.id.desc()).limit(50).all()
        error_artifact = None
        if config.error_artifact_id:
            artifact = self.db.query(Artifact).filter(Artifact.id == config.error_artifact_id).first()
            if artifact is not None:
                error_artifact = {
                    "id": str(artifact.id),
                    "name": artifact.name,
                    "row_count": (artifact.metadata_ or {}).get("row_count", 0),
                }
        return {
            "config_id": str(config.id),
            "error_count": int(config.error_count or 0),
            "alert_count": int(config.alert_count or 0),
            "retrain_status": config.retrain_status,
            "retrain_job_id": str(config.retrain_job_id) if config.retrain_job_id else None,
            "review_task_id": str(config.review_task_id) if config.review_task_id else None,
            "swapped_model_version_id": (
                str(config.swapped_model_version_id) if config.swapped_model_version_id else None
            ),
            "error_artifact": error_artifact,
            "events": [
                {
                    "id": str(event.id),
                    "event_type": event.event_type,
                    "severity": event.severity,
                    "message": event.message,
                    "payload": event.payload or {},
                    "created_at": event.created_at.isoformat() if event.created_at else None,
                }
                for event in reversed(events)
            ],
        }


def demo_loop_service(db):
    return DemoLoopService(db)
