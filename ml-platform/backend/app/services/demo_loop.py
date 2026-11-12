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
import tempfile
import uuid

from sqlalchemy.exc import IntegrityError
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

from app.config import settings
from app.database import SessionLocal
from app.engine.operator_contract import OperatorContext
from app.engine.registry import OperatorRegistry
from app.models.agent_run import AgentRun
from app.models.artifact import Artifact
from app.models.data_version import DatasetSample, DatasetSchemaColumn
from app.models.demo_loop import DemoLoopConfig, DemoLoopEvent
from app.models.model_registry import DeploymentRevision, InferenceDeployment, ModelVersion
from app.models.platform_models import GenericAnnotationTask
from app.models.recipe import PipelineRecipe
from app.models.training import TrainingJob
from app.services.annotation_concurrency import AssignmentError, create_assignments
from app.services.annotation_scope import persist_scope_entries, scope_descriptor, scope_digest
from app.services.artifact_service import build_artifact_service
from app.services.closed_loop_actions import (
    ClosedLoopError,
    _automl_dispatcher,
    _json_value,
    append_rows_to_dataset_artifact,
    complete_retrain_swap,
    candidate_score,
    lock_for as _lock_for,
    notify_project_admins,
    trigger_retrain_job,
)
from app.services.inference_deployment import InferenceDeploymentError, InferenceDeploymentService
from app.services.inference_rollout import ConditionValueRouter, WeightedTargetRouter
from app.services.inference_runtime_client import InferenceRuntimeClient
from app.services.label_schema import bind_label_schema_to_task, create_label_schema, label_schema_snapshot
from app.services.model_registry import ModelRegistryError  # noqa: F401 (re-exported for callers)
# Fixed report-feature decoding goes through the bridge file's generic entry
# (production sources must not reference the legacy industry module directly).
from app.operators.processing import (
    REPORT_TABLE_FIELDS,
    WAVEFORM_FIELDS,
    build_fixed_feature_frame,
)
from app.operators.utility_operators import _validate_script_interface

FEATURE_ENGINEERING_MODES = ("legacy", "operator", "script")


class _NullExecLogger:
    """Minimal OperatorContext.logger stand-in for feature-engineering runs."""

    def info(self, message, **details):
        pass

    def warning(self, message, **details):
        pass

    def error(self, message, **details):
        pass


class DemoLoopError(ValueError):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


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


_ANOMALY_PREDICTION_THRESHOLD_CACHE: dict[str, float] = {}


def _anomaly_prediction_threshold(db, version) -> float | None:
    """部署版本的标定阈值（score_stats.threshold_score，§6.6A 判定统一）。

    与 API enrich 同链同口径——直接委托 anomaly_threshold_for_version（含
    工况分片版本的独立阈值解析：conversion_metadata.anomaly_score_stats_
    artifact_id 优先，M7）；进程级缓存（version 不可变）。
    """
    key = str(version.id)
    if key in _ANOMALY_PREDICTION_THRESHOLD_CACHE:
        return _ANOMALY_PREDICTION_THRESHOLD_CACHE[key]
    from app.services.inference_deployment import anomaly_threshold_for_version

    result = anomaly_threshold_for_version(db, version)
    if result is not None:
        _ANOMALY_PREDICTION_THRESHOLD_CACHE[key] = result
    return result


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
        try:
            with service.storage.open(artifact.storage_uri) as handle:
                payload = handle.read()
        except Exception as error:
            raise DemoLoopError(
                "DEMO_LOOP_MODEL_ARTIFACT_MISSING",
                "模型制品文件缺失（可能因存储重建丢失）。请重新训练模型并部署，或将部署指回文件完好的模型版本。",
            ) from error
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

    def list_configs(self, project_id):
        return self.db.query(DemoLoopConfig).filter(
            DemoLoopConfig.project_id == project_id,
        ).order_by(DemoLoopConfig.created_at.asc()).all()

    def get_config_by_id(self, project_id, config_id):
        try:
            config_uuid = uuid.UUID(str(config_id))
        except (TypeError, ValueError, AttributeError):
            return None
        return self.db.query(DemoLoopConfig).filter(
            DemoLoopConfig.project_id == project_id,
            DemoLoopConfig.id == config_uuid,
        ).first()

    def save_config(self, project_id, actor_id, data: dict) -> DemoLoopConfig:
        config = self.get_config(project_id)
        if config is None:
            config = DemoLoopConfig(project_id=project_id, created_by_id=actor_id)
            self.db.add(config)
        self._apply_config_fields(config, project_id, data)
        self.db.commit()
        self.db.refresh(config)
        return config

    def create_config(self, project_id, actor_id, data: dict) -> DemoLoopConfig:
        config = DemoLoopConfig(project_id=project_id, created_by_id=actor_id)
        self.db.add(config)
        self._apply_config_fields(config, project_id, data)
        if not str(config.name or "").strip():
            config.name = self._unique_name(project_id, "自动化闭环", exclude_id=config.id)
        self.db.commit()
        self.db.refresh(config)
        return config

    def update_config(self, config: DemoLoopConfig, project_id, data: dict) -> DemoLoopConfig:
        self._apply_config_fields(config, project_id, data)
        self.db.commit()
        self.db.refresh(config)
        return config

    def delete_config(self, config: DemoLoopConfig) -> None:
        # 事件行显式清除：不依赖 SQLite/Postgres 的 FK 级联差异。
        self.db.query(DemoLoopEvent).filter(DemoLoopEvent.config_id == config.id).delete()
        self.db.delete(config)
        self.db.commit()

    def _unique_name(self, project_id, desired: str, exclude_id=None) -> str:
        """同项目任务名唯一：重名自动追加 -2/-3…（用户不指定则后端命名不报错）。"""
        taken = {
            row[0] for row in self.db.query(DemoLoopConfig.name).filter(
                DemoLoopConfig.project_id == project_id,
                DemoLoopConfig.id != exclude_id,
            ).all()
        }
        if desired not in taken:
            return desired
        counter = 2
        while f"{desired}-{counter}" in taken:
            counter += 1
        return f"{desired}-{counter}"[:128]

    def _apply_config_fields(self, config: DemoLoopConfig, project_id, data: dict) -> None:
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
            config.name = self._unique_name(
                project_id, str(data["name"]).strip()[:128], exclude_id=config.id)
        if "preprocess_enabled" in data:
            config.preprocess_enabled = bool(data["preprocess_enabled"])
        mode = data.get("feature_engineering_mode")
        if mode is not None:
            mode = str(mode).strip() or "legacy"
            if mode not in FEATURE_ENGINEERING_MODES:
                raise DemoLoopError(
                    "DEMO_LOOP_CONFIG_INVALID",
                    "feature_engineering_mode must be one of legacy/operator/script")
            config.feature_engineering_mode = mode
        if "feature_operator_id" in data:
            operator_id = str(data.get("feature_operator_id") or "").strip()
            if not operator_id:
                config.feature_operator_id = None
            else:
                operator = OperatorRegistry.get(operator_id)
                if operator is None or getattr(operator, "category", "") != "feature_engineering":
                    raise DemoLoopError(
                        "DEMO_LOOP_CONFIG_INVALID",
                        "所选算子必须是「特征工程」类别下的算子")
                config.feature_operator_id = operator_id
        if "feature_script" in data:
            script = str(data.get("feature_script") or "").strip()
            if not script:
                config.feature_script = None
            else:
                try:
                    _validate_script_interface(script)
                except (RuntimeError, ValueError) as error:
                    raise DemoLoopError(
                        "DEMO_LOOP_CONFIG_INVALID", f"特征工程脚本接口校验失败：{error}")
                config.feature_script = script
        resolved_mode = (getattr(config, "feature_engineering_mode", None) or "legacy")
        if resolved_mode == "operator" and not config.feature_operator_id:
            raise DemoLoopError(
                "DEMO_LOOP_CONFIG_INVALID", "operator 模式必须选择「特征工程」类别下的算子")
        if resolved_mode == "script" and not (config.feature_script or "").strip():
            raise DemoLoopError("DEMO_LOOP_CONFIG_INVALID", "script 模式必须填写特征工程 Python 脚本")
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
        if "retrain_ensemble_enabled" in data:
            config.retrain_ensemble_enabled = bool(data["retrain_ensemble_enabled"])
        if "retrain_ensemble_top_k" in data:
            # 与引擎/训练 API 同一范围（2-5），越界钳制而非报错
            config.retrain_ensemble_top_k = max(2, min(5, int(data["retrain_ensemble_top_k"] or 3)))
        if "retrain_algorithm_ids" in data:
            ids = data.get("retrain_algorithm_ids")
            if ids is not None and not isinstance(ids, list):
                raise DemoLoopError("DEMO_LOOP_CONFIG_INVALID", "retrain_algorithm_ids 必须是字符串列表")
            config.retrain_algorithm_ids = [
                str(item).strip()[:64] for item in (ids or []) if str(item).strip()
            ][:64]
        if "retrain_input_columns" in data:
            columns = data.get("retrain_input_columns")
            if columns is not None and not isinstance(columns, list):
                raise DemoLoopError("DEMO_LOOP_CONFIG_INVALID", "retrain_input_columns 必须是字符串列表")
            config.retrain_input_columns = [
                str(item).strip()[:128] for item in (columns or []) if str(item).strip()
            ][:512]
        if "retrain_mode" in data:
            mode = str(data.get("retrain_mode") or "engine").strip() or "engine"
            if mode not in {"engine", "agent"}:
                raise DemoLoopError(
                    "DEMO_LOOP_CONFIG_INVALID", "retrain_mode 必须是 engine 或 agent")
            # 新建行的 retrain_status 尚为 None（列默认值 INSERT 时才落，会话
            # autoflush=False）——None 视同 idle，否则新建 agent 模式闭环恒被
            # 误判「重训进行中」拒绝。
            if (
                mode != (config.retrain_mode or "engine")
                and (config.retrain_status or "idle") not in {"idle", "failed", ""}
            ):
                raise DemoLoopError(
                    "DEMO_LOOP_CONFIG_INVALID", "重训进行中不允许切换模式")
            config.retrain_mode = mode
        if "retrain_agent_recipe_id" in data:
            raw = data.get("retrain_agent_recipe_id")
            if raw:
                try:
                    recipe = self.db.query(PipelineRecipe).filter(
                        PipelineRecipe.id == uuid.UUID(str(raw)),
                    ).first()
                except (TypeError, ValueError) as error:
                    raise DemoLoopError(
                        "DEMO_LOOP_CONFIG_INVALID", "retrain_agent_recipe_id 不是合法 UUID")
                if recipe is None:
                    raise DemoLoopError(
                        "DEMO_LOOP_CONFIG_INVALID", "绑定的固化配方不存在")
                if recipe.project_id != config.project_id:
                    raise DemoLoopError(
                        "DEMO_LOOP_CONFIG_INVALID", "固化配方不属于本项目")
                config.retrain_agent_recipe_id = recipe.id
            else:
                config.retrain_agent_recipe_id = None
        if "retrain_target_column" in data:
            config.retrain_target_column = str(data["retrain_target_column"] or "").strip()[:128]
        if "collect_correct_enabled" in data:
            config.collect_correct_enabled = bool(data["collect_correct_enabled"])
        # 无监督漂移治理（技术方案 §3.6）：PSI 触发配置
        if "psi_enabled" in data:
            config.psi_enabled = bool(data["psi_enabled"])
        if "psi_threshold" in data:
            threshold = data.get("psi_threshold")
            if threshold is not None:
                threshold = float(threshold)
                if not 0.0 < threshold <= 1.0:
                    raise DemoLoopError("DEMO_LOOP_CONFIG_INVALID", "psi_threshold 必须在 (0, 1] 区间")
                config.psi_threshold = threshold
        if "correct_sample_ratio" in data:
            ratio = str(data.get("correct_sample_ratio") or "").strip()
            if not ratio:
                config.correct_sample_ratio = "1:1"
            else:
                parts = ratio.split(":", 1)
                if (
                    len(parts) != 2
                    or not all(part.strip().isdigit() and 1 <= int(part.strip()) <= 10 for part in parts)
                ):
                    raise DemoLoopError(
                        "DEMO_LOOP_CONFIG_INVALID",
                        "correct_sample_ratio must be like '1:3' (每报错 1 条收 3 条正常) or '3:1'")
                config.correct_sample_ratio = f"{int(parts[0].strip())}:{int(parts[1].strip())}"
        if "field_descriptions" in data:
            descriptions = data.get("field_descriptions") or {}
            if not isinstance(descriptions, dict):
                raise DemoLoopError("DEMO_LOOP_CONFIG_INVALID", "field_descriptions must be an object")
            config.field_descriptions = {
                str(key).strip(): str(value) for key, value in descriptions.items()
                if str(key).strip()
            }
        if "retrain_dataset_artifact_ids" in data:
            raw_list = data.get("retrain_dataset_artifact_ids") or []
            if raw_list:
                if not isinstance(raw_list, list):
                    raise DemoLoopError(
                        "DEMO_LOOP_CONFIG_INVALID", "retrain_dataset_artifact_ids must be a list")
                resolved = []
                for raw_id in raw_list:
                    try:
                        artifact_uuid = uuid.UUID(str(raw_id))
                    except (TypeError, ValueError, AttributeError):
                        raise DemoLoopError(
                            "DEMO_LOOP_CONFIG_INVALID",
                            "retrain_dataset_artifact_ids entries must be UUIDs") from None
                    artifact = self.db.query(Artifact).filter(
                        Artifact.id == artifact_uuid,
                        Artifact.project_id == project_id,
                        Artifact.type == "dataset",
                    ).first()
                    if artifact is None:
                        raise DemoLoopError(
                            "DEMO_LOOP_CONFIG_INVALID",
                            "Retrain dataset not found in this project")
                    resolved.append(artifact.id)
                # 去重但保持选择顺序，前端展示与合并顺序稳定。
                seen = set()
                unique = [aid for aid in resolved if not (aid in seen or seen.add(aid))]
                config.retrain_dataset_artifact_ids = [str(aid) for aid in unique]
                config.retrain_dataset_artifact_id = unique[0]
            else:
                config.retrain_dataset_artifact_ids = []
                config.retrain_dataset_artifact_id = None
        if "retrain_dataset_artifact_id" in data and "retrain_dataset_artifact_ids" not in data:
            raw = data.get("retrain_dataset_artifact_id")
            if raw:
                try:
                    artifact_uuid = uuid.UUID(str(raw))
                except (TypeError, ValueError, AttributeError):
                    raise DemoLoopError(
                        "DEMO_LOOP_CONFIG_INVALID", "retrain_dataset_artifact_id must be a UUID") from None
                artifact = self.db.query(Artifact).filter(
                    Artifact.id == artifact_uuid,
                    Artifact.project_id == project_id,
                    Artifact.type == "dataset",
                ).first()
                if artifact is None:
                    raise DemoLoopError(
                        "DEMO_LOOP_CONFIG_INVALID", "Retrain dataset not found in this project")
                config.retrain_dataset_artifact_id = artifact.id
                config.retrain_dataset_artifact_ids = [str(artifact.id)]
            else:
                config.retrain_dataset_artifact_id = None
                config.retrain_dataset_artifact_ids = []

    # ------------------------------------------------------------------ predict

    def predict(self, config: DemoLoopConfig, record: dict, actor_id, dry_run: bool = False) -> dict:
        """One loop inference. ``dry_run=True``（S5 服务化冒烟，spec v0.9 §12.1）
        只做预测：不计数、不写回流数据集、不提交任何状态变更。"""
        if not isinstance(record, dict) or not record:
            raise DemoLoopError("DEMO_LOOP_RECORD_INVALID", "record must be a non-empty object")
        deployment = self._deployment(config)
        version = self._current_model_version(deployment)

        predicted, confidence, anomaly_score, served_version = self._run_prediction(
            config, deployment, version, record,
        )

        # 无监督报警判定（技术方案 §6.6A 判定统一）：anomaly 部署按标定阈值
        # （score_stats.threshold_score）判 anomaly_score，与 API enrich 同口径；
        # 工况分片部署按实际路由到的分片版本判定（每分片阈值独立，§6.3）。
        # 阈值不可得时回退 label 端口。有监督保持类别匹配。
        output_schema = served_version.output_schema if isinstance(served_version.output_schema, dict) else {}
        if output_schema.get("task") == "anomaly":
            threshold = _anomaly_prediction_threshold(self.db, served_version)
            if threshold is not None and anomaly_score is not None:
                is_error = anomaly_score >= threshold
            else:
                is_error = str(predicted) == "-1"
        else:
            is_error = str(predicted) in (config.error_classes or [])
        if dry_run:
            return {
                "prediction": str(predicted),
                "confidence": confidence,
                "anomaly_score": anomaly_score,
                "model_version_id": str(served_version.id),
                "error_matched": is_error,
                "appended": False,
                "dry_run": True,
                "total_count": int(getattr(config, "total_count", 0) or 0),
                "error_count": int(getattr(config, "error_count", 0) or 0),
                "alert_count": int(getattr(config, "alert_count", 0) or 0),
                "retrain_status": config.retrain_status,
            }
        # 并发计数用 SQL 原子自增：读-改-写在 uvicorn 双进程 + 线程池下丢
        # 更新（4 并发批量实测 total_count 严重少计）。响应值随后重读。
        from sqlalchemy import update as sa_update

        self.db.execute(
            sa_update(DemoLoopConfig)
            .where(DemoLoopConfig.id == config.id)
            .values(total_count=DemoLoopConfig.total_count + 1)
        )
        self.db.expire(config, ["total_count", "error_count", "alert_count"])
        self._emit(
            config,
            "error_row" if is_error else "row_predicted",
            f"预测类别 {predicted}" + ("（命中报错类别，回流数据集）" if is_error else ""),
            severity="warning" if is_error else "info",
            payload={"prediction": str(predicted), "confidence": confidence},
        )

        appended = False
        if is_error:
            labeled = dict(record, **{
                "prediction": str(predicted),
                "confidence": confidence,
            })
            # 无监督分数回流（技术方案 §3.6）：回流行=特征+分数+判定（无标签
            # 要求）；anomaly_score 列随行写入，schema evolution 加列即生效。
            # 无监督任务无 retrain_target_column（镜像互斥），该段自然跳过。
            if anomaly_score is not None:
                labeled["anomaly_score"] = anomaly_score
            # 回流行自带推理结果作为标签列：与重训目标列同名，合并重训时
            # 无需人工标注（报错数据自动携带 fault=<预测类别>）。
            if config.retrain_target_column:
                labeled[config.retrain_target_column] = str(predicted)
            self._append_error_rows(config, [labeled], actor_id)
            appended = True
            self._collect_correct_rows(config, actor_id)
            self._after_error_append(config, str(predicted), actor_id)
        elif config.collect_correct_enabled:
            # 正确数据收集：缓存正常预测行，回流时按比例随报错行并入
            self._buffer_correct_row(config, record, str(predicted), confidence, anomaly_score)

        self.db.commit()
        return {
            "prediction": str(predicted),
            "confidence": confidence,
            "anomaly_score": anomaly_score,
            "model_version_id": str(served_version.id),
            "error_matched": is_error,
            "appended": appended,
            "total_count": int(config.total_count),
            "error_count": int(config.error_count),
            "alert_count": int(config.alert_count),
            "retrain_status": config.retrain_status,
        }

    def _run_prediction(self, config: DemoLoopConfig, deployment: InferenceDeployment, version: ModelVersion, record: dict):
        """Runtime first (production-identical ONNX serving), in-process fallback.

        返回 ``(predicted, confidence, anomaly_score, served_version)``——
        工况分片部署（§6.3）按记录工况路由到分片版本，served_version 是
        实际服务的版本（阈值/输出合同判定必须跟随它，而非部署主版本）。
        """
        names = _feature_names(version)
        if names:
            missing = [name for name in names if name not in record]
            if missing:
                record = self._engineer_missing_features(config, record, missing, names)
        service = _deployment_service()
        if service is not None:
            try:
                condition_column = str(getattr(deployment, "condition_column", None) or "").strip()
                if condition_column:
                    # 工况分片路由（§6.3，二期 M7）：分片部署与灰度互斥，回流
                    # 记录按其工况值精确路由到对应分片 runtime（未命中回退默认
                    # 分片），保证回流行分数与线上同口径。
                    stable = self.db.query(DeploymentRevision).filter(
                        DeploymentRevision.deployment_id == deployment.id,
                        DeploymentRevision.status == "stable",
                    ).order_by(DeploymentRevision.revision_number.desc()).first()
                    targets = list(stable.targets or ()) if stable is not None else []
                    if not targets:
                        raise DemoLoopError(
                            "DEMO_LOOP_PREDICT_EMPTY",
                            "部署缺少稳定 revision 的分片 targets，无法路由",
                        )
                    routed = ConditionValueRouter(condition_column).select_for_record(
                        deployment, record, targets=targets,
                    )
                else:
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
                anomaly_score = None
                # 工况分片：实际服务的版本可能与部署主版本不同（按记录工况
                # 路由），输出合同与阈值判定都跟随 served_version。
                served_version = version
                if str(routed.model_version_id) != str(version.id):
                    try:
                        candidate = self.db.query(ModelVersion).filter(
                            # 路由产物可能是 str（JSON/fake target）也可能是
                            # UUID 对象：绑定 UUID 列必须统一转 uuid 对象（坑）
                            ModelVersion.id == uuid.UUID(str(routed.model_version_id)),
                        ).first()
                    except (TypeError, ValueError):
                        # 非 UUID 形态的路由键（测试 stub/外部实现）按主版本判定
                        candidate = None
                    served_version = candidate or version
                # 无监督分数回流（技术方案 §3.6）：ONNX scores=decision_function
                # （正=正常），anomaly_score 取负统一「越高越异常」。scores 端口
                # 输出形状 [N] 张量 → _json_value 得 list，取首元素。
                output_schema = served_version.output_schema if isinstance(served_version.output_schema, dict) else {}
                if output_schema.get("task") == "anomaly" and probabilities:
                    row_value = _json_value(probabilities[0])
                    if isinstance(row_value, list) and row_value:
                        row_value = row_value[0]
                    if isinstance(row_value, (int, float)) and not isinstance(row_value, bool):
                        anomaly_score = round(-float(row_value), 6)
                if probabilities:
                    row = _json_value(probabilities[0])
                    if isinstance(row, list) and row:
                        confidence = round(float(max(row)), 4)
                return predicted, confidence, anomaly_score, served_version
            except DemoLoopError:
                raise
            except (InferenceDeploymentError, RuntimeError) as error:
                code = getattr(error, "code", "INFERENCE_RUNTIME_UNAVAILABLE")
                if code == "INFERENCE_SCHEMA_MISMATCH":
                    raise DemoLoopError(
                        "DEMO_LOOP_RECORD_INVALID",
                        "数据与模型特征列不匹配（需要与训练特征完全一致的数值列）",
                    ) from error
        return (
            *self._predict_in_process(
                version, record, names,
                preprocess_enabled=bool(getattr(config, "preprocess_enabled", False)),
            ),
            version,
        )

    def _engineer_missing_features(
        self, config: DemoLoopConfig, record: dict, missing: list[str], names: list[str],
    ) -> dict:
        """Derive the model's engineered features from raw report data.

        Dispatches by ``feature_engineering_mode``:
        - ``operator``: run the selected workflow feature-engineering node
          (operator + saved params) on the single-row frame.
        - ``script``: run the user's Python script via the python_script
          operator runtime (fixed interface, auto dependency install).
        - ``legacy``: the platform's builtin report feature bridge
          (点焊报告字段 + 四路波形通道 → 73 特征 schema).
        """
        mode = (getattr(config, "feature_engineering_mode", None) or "legacy").strip()
        if mode == "operator":
            merged = self._engineer_via_operator(config, record)
        elif mode == "script":
            merged = self._engineer_via_script(config, record)
        else:
            # Explicit "legacy" mode means the user asked for the builtin
            # 点焊特征桥; no extra opt-in switch required.
            try:
                features, _schema, _stats = build_fixed_feature_frame(pd.DataFrame([record]))
            except Exception as error:
                raise DemoLoopError(
                    "DEMO_LOOP_RECORD_INVALID",
                    "自动特征工程失败：请确认上传的行为原始点焊报告数据，"
                    f"需包含报告字段 {', '.join(REPORT_TABLE_FIELDS)} 与波形列 {', '.join(WAVEFORM_FIELDS)}"
                    f"（缺失原因：{error}）；也可以在闭环配置中切换为"
                    "「工作流特征工程算子」/「Python 脚本」方式。",
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

    def _feature_engineering_context(self, config: DemoLoopConfig, node_id: str) -> OperatorContext:
        return OperatorContext(
            run_id="demo-loop",
            node_id=node_id,
            project_id=str(config.project_id),
            artifact_service=self._artifact_service(),
            cancel_requested=lambda: False,
            logger=_NullExecLogger(),
        )

    @staticmethod
    def _merge_first_row(record: dict, value) -> dict:
        """Merge the first row of a DataFrame/records output into the record."""
        if isinstance(value, pd.DataFrame):
            if value.empty:
                raise DemoLoopError(
                    "DEMO_LOOP_RECORD_INVALID", "特征工程输出为空，无法补齐模型特征列")
            row = value.iloc[0].to_dict()
        elif isinstance(value, list) and value and isinstance(value[0], dict):
            row = value[0]
        else:
            return record
        engineered = {str(key): _json_value(item) for key, item in row.items()}
        return {**record, **engineered}

    def _engineer_via_operator(self, config: DemoLoopConfig, record: dict) -> dict:
        if not config.feature_operator_id:
            raise DemoLoopError(
                "DEMO_LOOP_CONFIG_INVALID", "请先选择「特征工程」类别下的算子")
        operator = OperatorRegistry.get(config.feature_operator_id)
        if operator is None or getattr(operator, "category", "") != "feature_engineering":
            raise DemoLoopError(
                "DEMO_LOOP_CONFIG_INVALID", "所选算子不可用（须为「特征工程」类别）")
        frame = pd.DataFrame([record])
        context = self._feature_engineering_context(
            config, f"demo-loop-feature-{config.feature_operator_id}")
        try:
            # 直接选算子：使用算子默认参数（需要自定义逻辑请用 script 模式）。
            result = operator.execute(context, {"data": frame}, {})
            merged = record
            removed_columns: list[str] = []
            for name, value in (result.outputs or {}).items():
                if name == "statistics" and isinstance(value, dict):
                    # 算子显式剔除的列（如拧紧特征工程的 DECIDE_ONE/DECIDE_TWO 泄漏列）
                    # 必须同步从合并记录移除——合并以原始行为底，否则剔除被原样带回。
                    removed = value.get("removed_columns")
                    if isinstance(removed, list):
                        removed_columns = [str(item) for item in removed]
                merged = self._merge_first_row(merged, value)
            for key in removed_columns:
                merged.pop(key, None)
            return merged
        except DemoLoopError:
            raise
        except Exception as error:
            raise DemoLoopError(
                "DEMO_LOOP_RECORD_INVALID",
                f"特征工程算子执行失败：{error}",
            ) from error

    def _engineer_via_script(self, config: DemoLoopConfig, record: dict) -> dict:
        if not (config.feature_script or "").strip():
            raise DemoLoopError("DEMO_LOOP_CONFIG_INVALID", "请先填写特征工程 Python 脚本")
        operator = OperatorRegistry.get("python_script")
        if operator is None:
            raise DemoLoopError("DEMO_LOOP_CONFIG_INVALID", "python_script 算子未注册")
        frame = pd.DataFrame([record])
        context = self._feature_engineering_context(config, "demo-loop-feature-script")
        try:
            result = operator.execute(
                context,
                {"data": frame},
                {"script": config.feature_script, "auto_install": True},
            )
            rows = (result.outputs or {}).get("data")
            merged = self._merge_first_row(record, rows)
            return merged
        except DemoLoopError:
            raise
        except Exception as error:
            raise DemoLoopError(
                "DEMO_LOOP_RECORD_INVALID",
                f"特征工程脚本执行失败：{error}",
            ) from error

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
        anomaly_score = None
        if hasattr(model, "predict_proba"):
            try:
                proba = model.predict_proba(frame)
                confidence = round(float(np.asarray(proba)[0].max()), 4)
            except Exception:
                confidence = None
        # 无监督进程内兜底：分数从 joblib 管线直接取（统一「越高越异常」口径）。
        output_schema = version.output_schema if isinstance(version.output_schema, dict) else {}
        if output_schema.get("task") == "anomaly":
            try:
                detector = model[-1] if hasattr(model, "steps") else model
                if hasattr(detector, "decision_function"):
                    anomaly_score = round(float(-detector.decision_function(frame)[0]), 6)
            except Exception:
                anomaly_score = None
        return predicted, confidence, anomaly_score

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
                # Self-heal: if the stored file was lost (e.g. storage volume
                # rebuilt), start a fresh dataset instead of failing the loop.
                try:
                    with self._artifact_service().storage.materialize(artifact.storage_uri) as path:
                        pd.read_csv(path, nrows=1)
                    return artifact
                except Exception:
                    config.error_artifact_id = None
                    self.db.commit()
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

    def ensure_error_dataset(self, config: DemoLoopConfig, columns: list[str]) -> Artifact:
        """预建闭环报错数据集（列与回流行同构）。编排发布要在首次回流前拿到
        报错集 id（append_error_dataset 节点参数）；已存在则原样返回。"""
        with _lock_for(str(config.id)):
            artifact = self._error_artifact(config, columns)
        self.db.commit()
        return artifact

    def _append_error_rows(self, config: DemoLoopConfig, rows: list[dict], actor_id) -> None:
        columns = sorted({key for row in rows for key in row})
        with _lock_for(str(config.id)):
            artifact = self._error_artifact(config, columns)
            total = append_rows_to_dataset_artifact(
                self.db, self._artifact_service(), artifact, rows,
            )
        self._emit(config, "error_appended", f"错误数据已追加（当前 {total} 行）",
                   payload={"rows": len(rows), "total": total})

    # ------------------------------------------------------- correct sampling

    def _correct_buffer(self, config: DemoLoopConfig) -> dict:
        """深拷贝读取缓冲状态。

        SQLAlchemy 的 JSON 列不做原地变更检测：浅拷贝 dict 与已加载值共享
        rows 列表，append 后新旧值按值相等 → UPDATE 被静默跳过（缓冲累计
        丢失、比例收集不足的根因）。这里每次返回全新结构，赋值必然产生
        可检测的值差异。
        """
        loaded = config.correct_buffer or {}
        rows = loaded.get("rows")
        return {
            "rows": [dict(row) for row in rows] if isinstance(rows, list) else [],
            "since_correct": int(loaded.get("since_correct") or 0),
        }

    def _correct_artifact(self, config: DemoLoopConfig, columns: list[str]) -> Artifact:
        """正确数据集（独立于报错数据集，避免计数口径混淆）。"""
        if config.correct_artifact_id:
            artifact = self.db.query(Artifact).filter(
                Artifact.id == config.correct_artifact_id,
                Artifact.project_id == config.project_id,
            ).first()
            if artifact is not None:
                return artifact
        name = f"{config.name}-正确数据"
        exists = self.db.query(Artifact.id).filter(
            Artifact.project_id == config.project_id,
            Artifact.name == name,
            Artifact.type == "dataset",
        ).first()
        if exists is not None:
            name = f"{name}-{uuid.uuid4().hex[:6]}"
        frame = pd.DataFrame(columns=columns or ["record"])
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "correct_rows.csv"
            frame.to_csv(path, index=False)
            artifact = self._artifact_service().create_from_file(
                config.project_id, path, name, "dataset",
                metadata={
                    "source": "demo_loop",
                    "kind": "correct",
                    "row_count": 0,
                    "column_count": len(frame.columns),
                },
            )
        config.correct_artifact_id = artifact.id
        self._emit(config, "correct_dataset_created", f"已创建正确数据集 {artifact.name}",
                   payload={"artifact_id": str(artifact.id)})
        return artifact

    def _buffer_correct_row(self, config: DemoLoopConfig, record: dict, predicted: str, confidence, anomaly_score=None) -> None:
        """缓存正常预测行，供回流时按比例收集进正确数据集。"""
        state = self._correct_buffer(config)
        labeled = dict(record, **{
            "prediction": predicted,
            "confidence": confidence,
        })
        # 无监督分数回流（§3.6）：正常行同样携带分数——PSI 基线需要全部
        # 推理行的分数分布，只看报错行会把「异常偏置」误读成「漂移」。
        if anomaly_score is not None:
            labeled["anomaly_score"] = anomaly_score
        state["rows"].append(labeled)
        # 上限防止长跑任务无限增长（比例单周期最多 10 倍，200 条足够）
        state["rows"] = state["rows"][-200:]
        config.correct_buffer = state
        self.db.commit()

    def _collect_correct_rows(self, config: DemoLoopConfig, actor_id) -> None:
        """按「错误:正确」比例把缓冲中的正常行收集进正确数据集。

        比例 "e:c"：每累计 e 条报错，收集 c 条缓冲中的正常行；
        cycle 计数存于 correct_buffer.since_correct。正确行自带
        prediction 与目标列标签，供重训合并直接使用。
        """
        ratio = str(config.correct_sample_ratio or "1:1")
        try:
            error_part, correct_part = (int(part) for part in ratio.split(":", 1))
            error_part, correct_part = max(1, error_part), max(0, correct_part)
        except ValueError:
            error_part, correct_part = 1, 1
        if not config.collect_correct_enabled or correct_part <= 0:
            return
        state = self._correct_buffer(config)
        since = int(state.get("since_correct") or 0) + 1
        if since % error_part != 0:
            state["since_correct"] = since
            config.correct_buffer = state
            return
        state["since_correct"] = 0
        rows = state["rows"]
        take = min(correct_part, len(rows))
        if take <= 0:
            state["rows"] = []
            config.correct_buffer = state
            return
        collected, rows = rows[:take], rows[take:]
        state["rows"] = rows
        for row in collected:
            if config.retrain_target_column:
                row[config.retrain_target_column] = row.get("prediction", "")
        columns = list(collected[0].keys())
        artifact = self._correct_artifact(config, columns)
        total = append_rows_to_dataset_artifact(
            self.db, self._artifact_service(), artifact, collected,
        )
        config.correct_buffer = state
        self._emit(
            config, "correct_collected",
            f"已按 {ratio} 比例收集 {take} 条正常数据（正确数据集当前 {total} 行，缓冲剩余 {len(rows)} 条）",
            payload={"collected": take, "total": total},
        )

    # ---------------------------------------------------------------- thresholds

    def _after_error_append(self, config: DemoLoopConfig, predicted: str, actor_id) -> None:
        # error_count 同样原子自增（与 total_count 同一竞态面）；随后重读供
        # 告警取模与重训阈值评估使用。
        from sqlalchemy import update as sa_update

        self.db.execute(
            sa_update(DemoLoopConfig)
            .where(DemoLoopConfig.id == config.id)
            .values(error_count=DemoLoopConfig.error_count + 1)
        )
        self.db.expire(config, ["error_count", "alert_count"])
        threshold = max(1, int(config.alert_threshold_rows or 1))
        if int(config.error_count or 0) % threshold == 0:
            self.db.execute(
                sa_update(DemoLoopConfig)
                .where(DemoLoopConfig.id == config.id)
                .values(alert_count=DemoLoopConfig.alert_count + 1)
            )
            self.db.expire(config, ["alert_count"])
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
                    except (AssignmentError, DemoLoopError, ValueError, IntegrityError) as error:
                        # 审核任务失败只降级为事件：重训触发不能被审核链路阻断
                        # （PG 事务可能已中止，先回滚再记事件）。
                        self.db.rollback()
                        self._emit(config, "review_task_failed", f"创建人工审核任务失败：{error}",
                                   severity="warning")
                else:
                    self._emit(config, "review_skipped", "已开启人工审核但未配置标注员", severity="warning")
        if (
            config.retrain_enabled
            and (
                int(config.retrain_threshold_rows or 0) > 0
                or getattr(config, "psi_enabled", False)
            )
        ):
            self._maybe_trigger_retrain(config, actor_id)

    # ---------------------------------------------------------------- retrain mode

    def _anomaly_retrain_params(self, config: DemoLoopConfig) -> dict | None:
        """无监督重拟合参数（技术方案 §3.6）：部署模型是 anomaly 检测器时返回
        ``{"threshold_score", "contamination"}``（score_stats.json 训练基线），
        否则 None（有监督闭环合同不变）。"""
        try:
            deployment = self._deployment(config)
            version = self._current_model_version(deployment)
            output_schema = version.output_schema if isinstance(version.output_schema, dict) else {}
            if output_schema.get("task") != "anomaly":
                return None
            payload = self._score_stats_payload_for_version(version)
            if payload is None:
                return None
            threshold = payload.get("threshold_score")
            contamination = payload.get("contamination")
            return {
                "threshold_score": float(threshold) if threshold is not None else None,
                "contamination": float(contamination) if contamination is not None else None,
            }
        except Exception:
            return None

    def _score_stats_payload_for_version(self, version: ModelVersion) -> dict | None:
        """部署版本的 score_stats.json 载荷（PSI 基线/重拟合参数共用）。

        工况分片版本（§6.3，二期 M7）优先走 conversion_metadata 里注册时写入
        的 anomaly_score_stats_artifact_id（每分片独立标定）；普通版本走旧链
        （模型库 → training_job → job.metrics.score_artifact_id，即最差段/单
        模型口径）。任一环节缺失返回 None（无证据不触发）。
        """
        metadata = version.conversion_metadata if isinstance(version.conversion_metadata, dict) else {}
        shard_stats_id = str(metadata.get("anomaly_score_stats_artifact_id") or "").strip()
        artifact = None
        if shard_stats_id:
            # JSON 列取出的 id 恒为 str：UUID 列绑定必须转 uuid 对象（坑）
            artifact = self.db.query(Artifact).filter(
                Artifact.id == uuid.UUID(shard_stats_id),
            ).first()
        if artifact is None:
            from app.models.model_library import ModelLibrary

            library = self.db.query(ModelLibrary).filter(
                ModelLibrary.id == version.source_model_library_id,
            ).first()
            if library is None or not library.training_job_id:
                return None
            job = self.db.query(TrainingJob).filter(
                TrainingJob.id == library.training_job_id,
            ).first()
            score_artifact_id = (job.metrics or {}).get("score_artifact_id") if job else None
            if not score_artifact_id:
                return None
            artifact = self.db.query(Artifact).filter(
                Artifact.id == uuid.UUID(str(score_artifact_id)),
            ).first()
            if artifact is None:
                return None
        with self._artifact_service().materialize(
            artifact.id, artifact.project_id, expected_type="report",
        ) as path:
            return json.loads(Path(path).read_text(encoding="utf-8"))

    def _psi_baseline_points(self, config: DemoLoopConfig) -> list[float] | dict | None:
        """训练期分数分位表（score_stats.json，M1 产物）。

        普通部署返回 ``list[float]``（单基线，与一期一致）；工况分片部署
        （§6.3，二期 M7）返回 ``dict[condition_value → points]``——每分片
        版本各自的 score_stats 基线（PSI per-shard 的数据基础），condition_
        value=None 的通配分片（默认段）键为 None。任一环节缺失返回 None
        （无证据不触发）。
        """
        try:
            deployment = self._deployment(config)
            version = self._current_model_version(deployment)
            output_schema = version.output_schema if isinstance(version.output_schema, dict) else {}
            if output_schema.get("task") != "anomaly":
                return None
            condition_column = str(getattr(deployment, "condition_column", None) or "").strip()
            if condition_column:
                return self._psi_baseline_points_sharded(deployment, condition_column)
            payload = self._score_stats_payload_for_version(version)
            if payload is None:
                return None
            points = ((payload.get("calibration") or {}).get("quantile_points")) or []
            return [float(value) for value in points] if len(points) >= 2 else None
        except Exception:
            # 基线缺失/文件丢失：无证据不触发，静默降级（与回流数据集自愈同语义）
            return None

    def _psi_baseline_points_sharded(self, deployment, condition_column: str) -> dict | None:
        """分片基线：stable revision 每个 target 版本各自的分位表。

        ``dict[condition_value → points]``；全部解析失败返回 None（回退无
        证据不触发）。单分片也走 dict（评估端按分片语义统一处理）。
        """
        from app.models.model_registry import DeploymentRevision

        stable = self.db.query(DeploymentRevision).filter(
            DeploymentRevision.deployment_id == deployment.id,
            DeploymentRevision.status == "stable",
        ).order_by(DeploymentRevision.revision_number.desc()).first()
        if stable is None or not (stable.targets or ()):
            return None
        baselines: dict[str | None, list[float]] = {}
        for target in stable.targets or ():
            version = self.db.query(ModelVersion).filter(
                ModelVersion.id == target.model_version_id,
            ).first()
            if version is None:
                continue
            payload = self._score_stats_payload_for_version(version)
            if payload is None:
                continue
            points = ((payload.get("calibration") or {}).get("quantile_points")) or []
            if len(points) < 2:
                continue
            raw_value = getattr(target, "condition_value", None)
            baselines[str(raw_value).strip() if raw_value is not None else None] = [
                float(value) for value in points
            ]
        return baselines or None

    def _reflow_scores(self, config: DemoLoopConfig) -> list[float]:
        """回流分数样本：报错 + 正确数据集的 anomaly_score 列（§3.6 全部推理行）。

        只看报错行会把「异常偏置」误读成「漂移」——基线需要全部推理行的
        分数分布。数据集缺失/无分数列返回空表。只读已有工件（不走
        获取或创建 helper——PSI 评估不该建数据集）。
        """
        scores: list[float] = []
        artifact_ids = [config.error_artifact_id, getattr(config, "correct_artifact_id", None)]
        service = None
        for artifact_id in artifact_ids:
            if not artifact_id:
                continue
            try:
                artifact = self.db.query(Artifact).filter(
                    Artifact.id == artifact_id,
                    Artifact.project_id == config.project_id,
                ).first()
                if artifact is None:
                    continue
                service = service or self._artifact_service()
                with service.materialize(
                    artifact.id, config.project_id, expected_type="dataset",
                ) as path:
                    frame = pd.read_csv(Path(path))
            except Exception:
                continue
            if "anomaly_score" in frame.columns:
                column = pd.to_numeric(frame["anomaly_score"], errors="coerce").dropna()
                scores.extend(float(value) for value in column.tolist())
        return scores

    def _reflow_frames(self, config: DemoLoopConfig) -> list[pd.DataFrame]:
        """回流帧（PSI per-shard 用）：报错 + 正确数据集的原始行——保留工况
        列，分片评估按工况列分组。缺失数据集跳过（只读已有工件）。"""
        frames: list[pd.DataFrame] = []
        artifact_ids = [config.error_artifact_id, getattr(config, "correct_artifact_id", None)]
        service = None
        for artifact_id in artifact_ids:
            if not artifact_id:
                continue
            try:
                artifact = self.db.query(Artifact).filter(
                    Artifact.id == artifact_id,
                    Artifact.project_id == config.project_id,
                ).first()
                if artifact is None:
                    continue
                service = service or self._artifact_service()
                with service.materialize(
                    artifact.id, config.project_id, expected_type="dataset",
                ) as path:
                    frame = pd.read_csv(Path(path))
            except Exception:
                continue
            if "anomaly_score" in frame.columns:
                frames.append(frame)
        return frames

    def _reflow_scores_by_condition(
        self, config: DemoLoopConfig, condition_column: str,
    ) -> dict[str | None, list[float]]:
        """回流分数按工况值分列（§6.3 per-shard PSI 的流内侧）。

        返回 ``dict[condition_value → scores]``；工况列缺失/值缺失/未匹配
        任何已知分片的行归入 None 键（通配默认分片口径）。全部无分数返回
        空表（无证据不触发）。
        """
        grouped: dict[str | None, list[float]] = {}
        for frame in self._reflow_frames(config):
            condition_series = (
                frame[condition_column].astype(str).str.strip()
                if condition_column in frame.columns else None
            )
            scores = pd.to_numeric(frame["anomaly_score"], errors="coerce")
            for index, value in scores.items():
                if pd.isna(value):
                    continue
                if condition_series is not None and index in condition_series.index:
                    raw_value = condition_series.loc[index]
                    key: str | None = str(raw_value) if raw_value not in (None, "", "nan") else None
                else:
                    key = None
                grouped.setdefault(key, []).append(float(value))
        return grouped

    def _evaluate_psi_drift(self, config: DemoLoopConfig) -> dict | None:
        """回流分数 PSI 对训练基线（§3.6）：total_count 未变时跳过重算（节流）。

        工况分片部署（§6.3，二期 M7）：基线为 dict 时按分片评估——每分片
        用各自 score_stats 基线对该分片流内分数算 PSI（未匹配工况值的记录
        归通配分片），汇总取**最差分片**（max PSI，与 retention/冠军同口径）；
        per_shard 明细进 psi_state 供排障。普通部署单基线行为不变。
        """
        state = dict(config.psi_state or {})
        total = int(getattr(config, "total_count", 0) or 0)
        if state.get("last_total") == total and "psi" in state:
            return {
                "psi": float(state.get("psi") or 0.0),
                "level": str(state.get("level") or "stable"),
                "alert_threshold": float(config.psi_threshold or 0.25),
                "watch_threshold": 0.10,
                "sample_count": int(state.get("sample_count") or 0),
            }
        baseline_points = self._psi_baseline_points(config)
        from app.services.anomaly_drift import evaluate_score_drift

        if isinstance(baseline_points, dict):
            # 分片评估（per-shard）：deployment.condition_column 非空才可能
            # 拿到 dict 基线；取不到部署列时全部归通配键。
            deployment = self._deployment(config)
            condition_column = str(getattr(deployment, "condition_column", None) or "").strip()
            grouped = (
                self._reflow_scores_by_condition(config, condition_column)
                if condition_column else {}
            )
            if not grouped:
                drift = {"psi": None, "level": "no_data", "sample_count": 0}
            else:
                shard_reports: list[dict] = []
                for condition_value, points in baseline_points.items():
                    shard_scores = grouped.get(condition_value) or []
                    if not shard_scores:
                        continue
                    shard_drift = evaluate_score_drift(points, shard_scores)
                    shard_reports.append({
                        "condition_value": condition_value,
                        **shard_drift,
                    })
                if not shard_reports:
                    drift = {"psi": None, "level": "no_data", "sample_count": 0}
                else:
                    worst = max(shard_reports, key=lambda item: float(item.get("psi") or 0.0))
                    drift = {
                        "psi": worst.get("psi"),
                        "level": worst.get("level"),
                        "alert_threshold": float(config.psi_threshold or 0.25),
                        "watch_threshold": 0.10,
                        "sample_count": sum(
                            int(item.get("sample_count") or 0) for item in shard_reports
                        ),
                        "per_shard": shard_reports,
                    }
        else:
            scores = self._reflow_scores(config) if baseline_points else []
            if not baseline_points or not scores:
                drift = {"psi": None, "level": "no_data", "sample_count": len(scores)}
            else:
                drift = evaluate_score_drift(baseline_points, scores)
        state.update({
            "last_total": total,
            "psi": drift.get("psi"),
            "level": drift.get("level"),
            "sample_count": drift.get("sample_count") or 0,
            **({"per_shard": drift.get("per_shard")} if drift.get("per_shard") else {}),
        })
        config.psi_state = state
        return drift

    def _maybe_trigger_retrain(self, config: DemoLoopConfig, actor_id) -> None:
        """统一触发评估（报错回流 + 轮次终态追赶共用，幂等）。

        增量边沿触发：error_count - trained_baseline >= threshold。基线仅在
        换模成功时推进（_swap_to_best_model），失败/取消不推进——旧模型仍在
        服务，回流信号不作废。部署级单飞沿用 retrain_status/retrain_job_id/
        retrain_agent_run_id 三重守卫；agent 模式再过冷却/熔断/项目并发闸门
        （loop_retrain.trigger_agent_retrain），引擎模式行为与历史一致。

        PSI 触发（§3.6）：psi_enabled 时回流分数分布对训练基线的 PSI ≥ 阈值
        即触发——与行数增量是「或」关系（分数漂移先于误报显性化，正常行
        漂移也能预警）。PSI 节流：total_count 未变跳过重算。
        """
        # 启用+阈值守卫必须在统一入口：状态轮询的追赶评估曾绕过它，阈值 0
        # （界面语义=关闭）时 0-0<0 不成立 → 大屏每次轮询都对报错集触发重训，
        # 换模推进基线后再次满足，连环空转。
        if not config.retrain_enabled:
            return
        if (
            int(config.retrain_threshold_rows or 0) <= 0
            and not getattr(config, "psi_enabled", False)
        ):
            return
        if config.retrain_status not in {"idle", "failed", ""}:
            return
        if config.retrain_job_id is not None:
            return
        if getattr(config, "retrain_agent_run_id", None) is not None:
            return
        threshold_rows = int(config.retrain_threshold_rows or 0)
        baseline = int(getattr(config, "retrain_trained_baseline_count", 0) or 0)
        rows_reached = (
            threshold_rows > 0
            and int(config.error_count or 0) - baseline >= threshold_rows
        )
        psi_reached = False
        if getattr(config, "psi_enabled", False):
            drift = self._evaluate_psi_drift(config)
            if drift and drift.get("level") == "alert" and float(drift.get("psi") or 0.0) >= float(config.psi_threshold or 0.25):
                psi_reached = True
                self._emit(
                    config, "psi_alert",
                    f"分数漂移 PSI={drift.get('psi')} ≥ {drift.get('alert_threshold')}，触发重拟合预警",
                    severity="warning",
                    payload=drift,
                )
        if not rows_reached and not psi_reached:
            return
        mode = (getattr(config, "retrain_mode", None) or "engine").strip() or "engine"
        if mode == "agent":
            from app.services.agent.loop_retrain import (
                AgentRetrainError,
                trigger_agent_retrain,
            )

            try:
                trigger_agent_retrain(self.db, config, actor_id)
                return
            except AgentRetrainError as error:
                self.db.rollback()
                self._emit_retrain_failure_once(config, f"智能体重训触发失败：{error}")
                self.db.commit()
            except Exception as error:  # noqa: BLE001 - keep the loop alive
                self.db.rollback()
                self._emit_retrain_failure_once(config, f"智能体重训触发失败：{error}")
                self.db.commit()
            return
        self._trigger_retrain(config, actor_id)

    def _emit_retrain_failure_once(self, config: DemoLoopConfig, message: str,
                                   window_minutes: int = 10) -> None:
        """触发失败事件去重：状态轮询/逐行回流都会走到触发评估，同一故障
        （如配方未绑定快照）在窗口内只发一条，避免事件刷屏。"""
        from datetime import datetime, timedelta, timezone

        now = datetime.now(timezone.utc).replace(tzinfo=None)
        recent = (
            self.db.query(DemoLoopEvent)
            .filter(
                DemoLoopEvent.config_id == config.id,
                DemoLoopEvent.event_type == "retrain_failed",
                DemoLoopEvent.created_at >= now - timedelta(minutes=window_minutes),
            )
            .first()
        )
        if recent is not None:
            return
        self._emit(config, "retrain_failed", message, severity="warning")

    def _notify_admins(self, config: DemoLoopConfig, predicted: str) -> None:
        notify_project_admins(
            self.db,
            config.project_id,
            title=f"【{config.name}】报错数据告警",
            body=(
                f"推理命中的报错类别 {predicted} 已累计 {config.error_count} 行，"
                f"达到告警阈值 {config.alert_threshold_rows} 行，请关注数据回流与模型质量。"
            ),
            event_type="demo_loop.alert",
            payload={"config_id": str(config.id), "error_count": config.error_count},
        )

    # ------------------------------------------------------------- review task

    def _model_output_classes(self, config: DemoLoopConfig) -> list[str]:
        """模型全部输出类别（复核可选值）：历史预测观察值 ∪ 报错类别。"""
        classes: set[str] = set(config.error_classes or [])
        events = self.db.query(DemoLoopEvent).filter(
            DemoLoopEvent.config_id == config.id,
            DemoLoopEvent.event_type.in_(["row_predicted", "error_row"]),
        ).order_by(DemoLoopEvent.created_at.desc()).limit(500).all()
        for event in events:
            predicted = (event.payload or {}).get("prediction")
            if predicted is not None:
                classes.add(str(predicted))
        if not classes:
            classes = {"0", "1"}
        # 报错类别排在最后（复核语义：确认报错 / 改判正常）
        ordered = sorted(c for c in classes if c not in set(config.error_classes or []))
        ordered += [c for c in sorted(classes) if c in set(config.error_classes or [])]
        return ordered

    def _create_review_task(self, config: DemoLoopConfig, actor_id) -> None:
        # 每个闭环任务同一时间只保留一个人工审核任务：进行中的任务不重复
        # 新建，新报错数据继续追加到同一报错数据集，审核完成后下一轮告警再建。
        if config.review_task_id:
            existing = self.db.query(GenericAnnotationTask).filter(
                GenericAnnotationTask.id == config.review_task_id,
            ).first()
            if existing is not None and existing.status not in {
                "completed", "accepted", "cancelled", "archived",
            }:
                # 任务创建后又收集了新数据（报错/正确）→ 取消旧任务并重建，
                # 让审核样本覆盖全部已收集数据；无新增则维持原任务。
                artifact = self.db.query(Artifact).filter(
                    Artifact.id == config.error_artifact_id,
                ).first()
                created_rows = int(
                    ((existing.task_snapshot or {}).get("dataset_version") or {}).get("row_count") or 0
                )
                current_rows = int((artifact.metadata_ or {}).get("row_count") or 0) if artifact else 0
                if artifact is not None and current_rows > created_rows:
                    existing.status = "cancelled"
                    config.review_task_id = None
                    self.db.commit()
                    self._emit(
                        config, "review_task_superseded",
                        f"检测到新增收集数据（{created_rows} → {current_rows} 行），已重建审核任务以纳入全部样本",
                        severity="info",
                    )
                else:
                    self._emit(
                        config, "review_task_exists",
                        f"人工审核任务仍在进行中（{existing.name}），新报错数据继续追加到同一报错数据集",
                        severity="info",
                    )
                    return
        artifact = self.db.query(Artifact).filter(
            Artifact.id == config.error_artifact_id,
        ).first()
        if artifact is None:
            raise DemoLoopError("DEMO_LOOP_ERROR_DATASET_MISSING", "Error dataset artifact missing")
        service = self._artifact_service()
        version = service.create_dataset_version_from_artifact(artifact, operator_id=actor_id)
        # 复核可选值 = 模型全部输出类别（不止报错类别）：审核员可纠正为正常类
        classes = self._model_output_classes(config)
        schema = create_label_schema(
            self.db,
            project_id=config.project_id,
            name=f"{config.name}-复核标签",
            columns=[{
                "machine_key": "review_label",
                "display_name": "复核标签",
                # 校验器仅支持 int/float/string（"enum" 非法）；枚举约束由
                # enum_values 在类型校验后单独执行。
                "value_type": "string",
                "required": True,
                "enum_values": classes,
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
            "instructions": "自动化闭环自动创建：请复核本行数据是否确实属于报错类别。",
            "completion_criteria": "",
            "configuration": {},
            "field_descriptions": dict(config.field_descriptions or {}),
        }
        canonical = json.dumps(snapshot, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
        snapshot["config_hash"] = "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        # 幂等键带周期短码：reset 清零计数后再次告警不得撞历史任务
        # （alert_count/error_count 归零重放会与旧任务唯一键冲突）。
        review_cycle = uuid.uuid4().hex[:6]
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
            idempotency_key=f"demo-loop-review-{config.id}-{config.alert_count}-{review_cycle}",
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
            idempotency_key=f"demo-loop-assign-{config.id}-{config.alert_count}-{review_cycle}",
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
        from app.services.closed_loop_actions import resolve_retrain_dataset_ids

        dataset_ids = resolve_retrain_dataset_ids(config)
        if not dataset_ids:
            raise DemoLoopError("DEMO_LOOP_RETRAIN_DATASET_MISSING", "未配置重训数据集")
        # 无监督重拟合（技术方案 §3.6）：部署模型是 anomaly 检测器时走无监督
        # 合同——目标列必须为空（镜像互斥），阈值/污染率从训练基线 score_stats 读。
        anomaly_params = self._anomaly_retrain_params(config)
        is_anomaly = anomaly_params is not None
        target_column = (config.retrain_target_column or "").strip()
        if not is_anomaly:
            if not target_column:
                # 默认取部署模型版本的 label 列（AutoML 注册时写入 output_schema.target_columns）。
                target_column = self._deployment_default_target(config)
            if not target_column:
                raise DemoLoopError("DEMO_LOOP_RETRAIN_TARGET_MISSING", "未配置重训目标列")
        # 绑定表以 experiment_id 为主键（实验↔AutoML 任务 1:1），且重训幂等
        # 指纹含实验名；实验名必须按周期唯一，否则同轮次触发绑定冲突或重放旧任务。
        cycle = uuid.uuid4().hex[:8]
        # 工况分片重拟合（§6.3，二期 M7）：分片部署的重训必须带工况列——
        # 引擎按它重新分片训练（N bundle），否则退化单段全量、分片 targets 断。
        # config 无 deployment（测试桩/配置缺失）时安全降级为 None。
        try:
            deployment_for_shard = self._deployment(config)
        except Exception:  # noqa: BLE001 - 无部署不阻断重训参数组装
            deployment_for_shard = None
        shard_condition_column = str(
            getattr(deployment_for_shard, "condition_column", None) or ""
        ).strip() or None
        job = trigger_retrain_job(
            self.db,
            project_id=config.project_id,
            actor_id=actor_id,
            experiment_name=f"{config.name}-自动建模-{config.error_count}-{cycle}",
            job_name=f"{config.name}-自动建模-{config.error_count}-{cycle}",
            dataset_artifact_ids=dataset_ids,
            target_column=target_column,
            max_trials=config.retrain_max_trials,
            # 终选层集成随重训下发：采纳后成为任务冠军，换模即部署集成体
            ensemble=(
                {"enabled": True, "top_k": int(config.retrain_ensemble_top_k or 3)}
                if getattr(config, "retrain_ensemble_enabled", False)
                else None
            ),
            # 向导算法白名单（空 = 全族）
            algorithm_ids=list(getattr(config, "retrain_algorithm_ids", None) or []) or None,
            # 重训特征列白名单（稀疏宽表必配，空 = 全 numeric）
            input_columns=list(getattr(config, "retrain_input_columns", None) or []) or None,
            task_type="anomaly_detection" if is_anomaly else "classification",
            **(
                {
                    "anomaly_threshold_score": anomaly_params.get("threshold_score"),
                    "anomaly_contamination": anomaly_params.get("contamination"),
                    "feedback_marks": config.feedback_marks,
                    "condition_column": shard_condition_column,
                }
                if is_anomaly
                else {}
            ),
        )
        config.retrain_job_id = job.id
        config.retrain_status = "queued"
        if not is_anomaly and not config.retrain_target_column:
            # 未显式配置时回填模型 label 列，便于前端展示与后续轮次一致。
            config.retrain_target_column = target_column
        self.db.commit()
        self._emit(config, "retrain_triggered",
                   f"报错数据已达 {config.error_count} 行，自动建模任务已触发（{job.params['max_trials']} 组试验）",
                   severity="warning",
                   payload={"job_id": str(job.id)})

    def _deployment_default_target(self, config: DemoLoopConfig) -> str:
        """部署模型版本的 label 列（output_schema.target_columns 首个）。"""
        if not config.deployment_id:
            return ""
        deployment = self.db.query(InferenceDeployment).filter(
            InferenceDeployment.id == config.deployment_id,
        ).first()
        if deployment is None or not deployment.model_version_id:
            return ""
        version = self.db.query(ModelVersion).filter(
            ModelVersion.id == deployment.model_version_id,
        ).first()
        if version is None:
            return ""
        targets = (version.output_schema or {}).get("target_columns") or []
        for target in targets:
            text = str(target).strip()
            if text:
                return text
        return ""

    def refresh_retrain_status(self, config: DemoLoopConfig, actor_id) -> None:
        # agent 重放轮在途（铸造未派发）：走 agent 分支（终态→固化配方+派
        # 铸造/失败/超时）。铸造已派发后 retrain_job_id 非空，交还引擎分支。
        if (
            getattr(config, "retrain_agent_run_id", None) is not None
            and config.retrain_job_id is None
        ):
            from app.services.agent.loop_retrain import poll_agent_retrain

            if poll_agent_retrain(self.db, config, actor_id):
                return
        # 空闲/失败追赶评估：轮次终态（换模成功/失败）或冷却到期后，下一次
        # 状态轮询/回流都会按增量判据再评估——覆盖「报错停了也要追平一轮」
        # 场景（部署完成后用全量积累补一轮，而非等下一个阈值额度）。failed
        # 也参与：失败轮曾有冷却兜底，若无新报错流入，failed 态永远不会被
        # 轮询唤醒（实测冷却到期后卡死不重试）。
        if config.retrain_status in {"idle", "", "failed"} and config.retrain_job_id is None:
            self._maybe_trigger_retrain(config, actor_id)
        # 收敛入口：job 挂着就必须检查（cancel_requested/终态卡住也在此自愈），
        # 否则取消/失败/完成后 retrain_job_id 残留会永久挡住下一轮触发。
        if config.retrain_job_id is None:
            return
        job = self.db.query(TrainingJob).filter(TrainingJob.id == config.retrain_job_id).first()
        if job is None:
            config.retrain_status = "failed"
            config.retrain_job_id = None
            self._emit(config, "retrain_failed", "自动建模任务记录丢失", severity="warning")
            self.db.commit()
            return
        if job.status == "pending" and job.task_id is None:
            # 自愈：任务派发竞态（worker 领取时行尚未提交 → skipped）或
            # broker 丢消息会让 job 永久滞留 pending。超过 2 分钟视为
            # 未投递，重新派发（claim 幂等，重复投递会被安全跳过）。
            created = job.created_at
            if created is not None:
                from datetime import datetime, timezone

                age = (datetime.now(timezone.utc).replace(tzinfo=None) - created).total_seconds()
                if age > 120:
                    from app.tasks.celery_app import celery_app

                    task_id = celery_app.send_task(
                        "ml_platform.execute_automl", args=[str(job.id)],
                    ).id
                    job.task_id = task_id
                    self._emit(config, "retrain_redispatched",
                               f"检测到自动建模任务未投递（滞留 {int(age // 60)} 分钟），已重新派发",
                               severity="warning")
                    self.db.commit()
                    return
        if job.status == "cancelled":
            # 用户取消：回到可触发状态，下一轮积累重新出发。
            config.retrain_status = "idle"
            config.retrain_job_id = None
            from app.services.agent.loop_retrain import finish_agent_cycle

            finish_agent_cycle(config)
            self._emit(config, "retrain_cancelled", "自动建模任务已取消，报错继续积累后将再次触发", severity="info")
            self.db.commit()
            return
        # Persisted jobs start as "pending"; surface that to users as queued.
        mapped_status = {"pending": "queued", "cancel_requested": "running"}.get(job.status, job.status)
        if mapped_status != config.retrain_status and mapped_status in {"queued", "running"}:
            config.retrain_status = mapped_status
            if mapped_status == "running":
                self._emit(config, "retrain_running", "自动建模任务执行中")
        if job.status == "completed":
            self._swap_to_best_model(config, job, actor_id)
            # 本轮闭环结束：清 job 引用回 idle，允许下一轮积累再触发。
            config.retrain_status = "idle"
            config.retrain_job_id = None
        elif job.status == "failed":
            config.retrain_status = "failed"
            config.retrain_job_id = None
            from app.services.agent.loop_retrain import finish_agent_cycle

            finish_agent_cycle(config)
            self._emit(config, "retrain_failed",
                       f"自动建模失败：{job.error_message or job.error_code or '未知错误'}",
                       severity="critical")
        self.db.commit()

    def _candidate_score(self, row: dict) -> float:
        return candidate_score(row)

    def _swap_to_best_model(self, config: DemoLoopConfig, job: TrainingJob, actor_id) -> None:
        # 每个完成的任务只换一次模：上游 refresh_retrain_status 依据
        # retrain_status 迁移保证调用次数；swapped_model_version_id 仅作
        # 前端换模水印，每轮覆盖为新版本，不能当 once-ever 守卫。
        # agent 重放轮恢复配方门禁兜底：classification_metrics 已补二分类
        # recall_minority 输出（与智能体 S3 验收训练器 lightweight_trainer/
        # 配方门禁 PRIMARY_METRIC 同口径），
        # 引擎候选不再 missing-veto（此前 8 个 f1 0.98+ 候选全被拦的死锁已修）。
        recipe_id = None
        if getattr(config, "retrain_agent_run_id", None) is not None:
            agent_run = self.db.get(AgentRun, config.retrain_agent_run_id)
            if agent_run is not None:
                recipe_id = (agent_run.result_json or {}).get("fixated_recipe_id")
        version = complete_retrain_swap(
            self.db,
            deployment_id=config.deployment_id,
            job=job,
            actor_id=actor_id,
            model_name=f"{config.name}-自动模型",
            recipe_id=recipe_id,
        )
        from app.services.agent.loop_retrain import finish_agent_cycle

        if version is None:
            self._emit(config, "retrain_failed", "自动建模完成但没有可注册的候选模型", severity="warning")
            # 门禁否决/无候选同样是轮次终态：清重放引用 + 冷却（基线不推进，
            # 旧模型继续服务；下一次触发将带全量积累重试，熔断兜底）。
            finish_agent_cycle(config)
            return
        deployment = self.db.query(InferenceDeployment).filter(
            InferenceDeployment.id == config.deployment_id,
        ).first() if config.deployment_id else None
        previous_id = str(deployment.model_version_id) if deployment is not None and deployment.model_version_id else None
        config.swapped_model_version_id = version.id
        # 换模成功：推进已消费报错基线（增量触发的唯一推进点），agent 重放
        # 轮收尾并进入冷却期。失败/门禁否决不推进——旧模型继续服务，回流
        # 信号不作废；追赶评估由下一次 refresh/回流按增量判据再触发。
        config.retrain_trained_baseline_count = int(config.error_count or 0)
        finish_agent_cycle(config)
        # agent 轮特征脚本可能已随重放演化：提醒在档案页重新服务化（已发布
        # 条目走新配方版本；serving 图按部署引用绑定，预测自动跟随换模）。
        if recipe_id:
            from app.models.recipe import PipelineRecipeVersion

            try:
                recipe_uuid = uuid.UUID(str(recipe_id))
            except (TypeError, ValueError):
                recipe_uuid = None
            recipe_version = (
                self.db.query(PipelineRecipeVersion)
                .filter(
                    PipelineRecipeVersion.recipe_id == recipe_uuid,
                    PipelineRecipeVersion.status == "current",
                )
                .first()
            )
            new_script = (recipe_version.content_json or {}).get("feature_script") or "" if recipe_version else ""
            if new_script and new_script != (config.feature_script or ""):
                self._emit(
                    config, "retrain_reservitize_manual",
                    "本轮重放的特征脚本与闭环配置不一致，如需对外 API 同步新脚本，"
                    "请在智能体任务档案页对该轮配方重新服务化",
                    severity="info",
                    payload={"recipe_id": str(recipe_id)},
                )
        self._emit(
            config, "model_swapped",
            f"自动建模完成，已将部署模型替换为最优候选（v{version.version_number}）",
            severity="critical",
            payload={
                "new_model_version_id": str(version.id),
                "previous_model_version_id": previous_id,
            },
        )

    # -------------------------------------------------------------------- reset

    def reset(self, config: DemoLoopConfig, actor_id) -> None:
        with _lock_for(str(config.id)):
            config.error_count = 0
            config.alert_count = 0
            config.total_count = 0
            config.retrain_status = "idle"
            config.retrain_job_id = None
            # 增量触发基线与 agent 重放引用一并清零（reset=全部重来，否则
            # 历史换模推进的基线会让 reset 后的积累永远够不到阈值）。
            config.retrain_trained_baseline_count = 0
            config.retrain_agent_run_id = None
            config.retrain_agent_started_at = None
            config.retrain_cool_until = None
            # PSI 状态一并清零：reset 后回流分数样本从零积累，旧 PSI 结论失效
            config.psi_state = None
            self.db.query(DemoLoopEvent).filter(DemoLoopEvent.config_id == config.id).delete()
            self._emit(config, "loop_reset", "闭环状态已重置（配置与数据集保留）")
            self.db.commit()

    # -------------------------------------------------------------------- status

    def _current_model_score(self, config: DemoLoopConfig) -> float | None:
        """当前部署模型的验证评分（0-1）。
        取模型版本注册来源任务的最佳得分；历史模型无评分时返回 None。"""
        try:
            deployment = self._deployment(config)
            version = self._current_model_version(deployment)
            if version.registration_task_id is None:
                return None
            job = self.db.query(TrainingJob).filter(
                TrainingJob.id == version.registration_task_id,
            ).first()
            score = ((job.metrics or {}).get("best_score") if job else None)
            if isinstance(score, (int, float)) and 0 < score <= 1:
                return round(float(score), 4)
        except Exception:  # noqa: BLE001 - 评分仅用于大屏展示，失败不影响状态
            pass
        return None

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
        model_score = self._current_model_score(config)
        return {
            "config_id": str(config.id),
            "error_count": int(config.error_count or 0),
            "alert_count": int(config.alert_count or 0),
            "total_count": int(getattr(config, "total_count", 0) or 0),
            "model_score": model_score,
            "retrain_status": config.retrain_status,
            "retrain_job_id": str(config.retrain_job_id) if config.retrain_job_id else None,
            "retrain_mode": (getattr(config, "retrain_mode", None) or "engine"),
            "retrain_input_columns": [str(item) for item in (getattr(config, "retrain_input_columns", None) or [])],
            "retrain_trained_baseline_count": int(
                getattr(config, "retrain_trained_baseline_count", 0) or 0
            ),
            "retrain_agent_run_id": (
                str(config.retrain_agent_run_id) if getattr(config, "retrain_agent_run_id", None) else None
            ),
            "retrain_cool_until": (
                config.retrain_cool_until.isoformat() if getattr(config, "retrain_cool_until", None) else None
            ),
            # 无监督漂移治理（§3.6）：最近一次 PSI 评估结果随状态下发（大屏展示）
            "psi_state": config.psi_state if isinstance(config.psi_state, dict) else None,
            "psi_enabled": bool(getattr(config, "psi_enabled", False)),
            "psi_threshold": float(getattr(config, "psi_threshold", 0.25) or 0.25),
            # 部署 id（§7 三-3，三期 M10）：机群分片概览面板拉取 fleet-overview
            "deployment_id": str(config.deployment_id) if config.deployment_id else None,
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
