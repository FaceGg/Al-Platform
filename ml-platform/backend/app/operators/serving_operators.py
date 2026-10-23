# -*- coding: utf-8 -*-
"""Serving-path operators for orchestration APIs published from workflows.

`api_input` receives the single record injected by the invoke endpoint;
`load_model_artifact` binds a frozen trained-model artifact so the serving
graph never retrains per row (training stays in the training workflow).
"""
import io
import uuid

import joblib
import numpy as np

from app.engine.operator_contract import OperatorContext, OperatorResult
from app.engine.base_operator import BaseOperator, PortSpec, ParamSpec
from app.engine.registry import register_operator


def _inject_feature_names(model, names: list[str]) -> str | None:
    """把训练特征列名挂到模型上，返回注入方式（None 表示该库不支持）。

    sklearn 原生模型的 ``feature_names_in_`` 可写；xgboost 的同名属性是只读
    property（实际存储在 booster.feature_names，predict 按列名校验）；lightgbm
    等库无公开写入口——注入失败返回 None，调用方降级告警而不是让加载节点崩溃。
    """
    values = np.array(names, dtype=object)
    try:
        model.feature_names_in_ = values
        return "sklearn"
    except AttributeError:
        pass
    try:
        model.get_booster().feature_names = list(names)
        return "xgboost_booster"
    except Exception:
        pass
    return None


@register_operator
class ApiInputOperator(BaseOperator):
    id = "api_input"
    name = "API Input"
    category = "closed_loop"
    description = "Record injected by the orchestration API invoke call"
    inputs = []
    outputs = [PortSpec("data", "DataTable", "Invoked Record")]
    parameters = []

    def validate(self, inputs):
        return True

    def execute(self, context: OperatorContext, inputs, params) -> OperatorResult:
        record = getattr(context, "payload", None)
        if record is None:
            raise RuntimeError(
                "API input payload is missing; this operator only runs inside "
                "an orchestration API invoke call"
            )
        rows = record if isinstance(record, list) else [record]
        if not rows:
            raise RuntimeError("API input payload is empty")
        return OperatorResult(outputs={"data": rows})


@register_operator
class LoadModelArtifactOperator(BaseOperator):
    id = "load_model_artifact"
    name = "Load Model Artifact"
    category = "closed_loop"
    description = "Load a frozen trained-model artifact for serving"
    inputs = []
    outputs = [PortSpec("model", "Model", "Loaded Model")]
    parameters = [
        ParamSpec("model_artifact_id", "str", "", "Model Artifact ID", required=True),
    ]

    def validate(self, inputs):
        return True

    @staticmethod
    def _package_feature_names(package: dict) -> list[str]:
        """从打包工件元数据提取训练特征列名（feature_schema 优先，input_contract 兜底）。"""
        schema = package.get("feature_schema")
        if (
            isinstance(schema, list) and schema
            and all(isinstance(item, dict) and item.get("name") for item in schema)
        ):
            return [str(item["name"]) for item in schema]
        contract = package.get("input_contract")
        if isinstance(contract, dict):
            columns = contract.get("input_columns") or contract.get("required_columns")
            if isinstance(columns, list) and columns:
                return [str(column) for column in columns]
        return []

    def execute(self, context: OperatorContext, inputs, params) -> OperatorResult:
        artifact_id = str(params.get("model_artifact_id") or "").strip()
        if not artifact_id:
            raise RuntimeError("model_artifact_id is required")
        if context.artifact_service is None or not context.project_id:
            raise RuntimeError("Artifact service and project context are required")
        try:
            artifact = context.artifact_service.resolve(
                artifact_id, context.project_id, expected_type="model",
            )
            with context.artifact_service.storage.open(artifact.storage_uri) as handle:
                payload = handle.read()
        except Exception as e:
            raise RuntimeError(f"Failed to load model artifact: {e}") from e
        # 非 joblib 工件（如模型注册表导出的 ONNX）拿去 joblib.load 只会抛出
        # 裸 "KeyError: 8" 之类反序列化噪声——按工件声明的格式前置拦截。
        artifact_format = str(getattr(artifact, "format", "") or "").strip().lower()
        if artifact_format and artifact_format not in ("joblib", "pkl", "pickle"):
            raise RuntimeError(
                f"模型工件是 {artifact_format.upper()} 格式，本算子仅支持 joblib 格式的模型工件"
                "（如 AutoML 任务注册的 .joblib 产物）；ONNX 模型请通过推理部署或模型 API 调用"
            )
        try:
            loaded = joblib.load(io.BytesIO(payload))
        except Exception as e:
            raise RuntimeError(
                f"模型工件无法按 joblib 反序列化（格式声明: {artifact_format or '未知'}）: {e}; "
                "请确认选择的是 joblib 格式模型工件"
            ) from e
        if isinstance(loaded, dict):
            # Model-library/AutoML artifacts package the estimator inside a
            # metadata dict; unwrap it for apply_model.
            package = loaded
            for key in ("model", "estimator", "clf", "pipeline", "best_model"):
                candidate = loaded.get(key)
                if candidate is not None and hasattr(candidate, "predict"):
                    loaded = candidate
                    break
            else:
                raise RuntimeError(
                    "Model artifact is a package without a predictable estimator; "
                    "publish the deployment inference API instead"
                )
            # numpy 拟合的 estimator 没有 feature_names_in_，训练特征列名只在
            # 工件的 feature_schema/input_contract 里——按库能力注入（sklearn
            # 直写 / xgboost booster），下游评估与 apply_model
            # （predict_with_hint）才能按列名对齐，而不是把测试数据的全部列
            # 按位置喂入导致 "X has N features, expecting M"。
            if not hasattr(loaded, "feature_names_in_"):
                names = self._package_feature_names(package)
                n_features = getattr(loaded, "n_features_in_", None)
                if names and isinstance(n_features, int) and n_features == len(names):
                    injected = _inject_feature_names(loaded, names)
                    if injected is None:
                        context.logger.warning(
                            f"模型工件包含特征列名（{len(names)} 列），但 {type(loaded).__name__}"
                            " 不支持附加特征名——评估/推理将无法按列名自动对齐特征",
                        )
        if not hasattr(loaded, "predict"):
            raise RuntimeError("Model artifact does not expose a predict method")
        # Re-serialize the bare estimator so the model port carries something
        # downstream apply_model can consume directly.
        buffer = io.BytesIO()
        joblib.dump(loaded, buffer)
        return OperatorResult(outputs={"model": buffer.getvalue()})


@register_operator
class AppendErrorDatasetOperator(BaseOperator):
    id = "append_error_dataset"
    name = "Append Error Dataset"
    category = "closed_loop"
    description = "Append the branch rows to an error dataset artifact (closed loop)"
    inputs = [PortSpec("data", "DataTable", "Error Rows")]
    outputs = [PortSpec("data", "DataTable", "Appended Rows")]
    parameters = [
        ParamSpec("dataset_artifact_id", "str", "", "Error Dataset Artifact ID", required=True),
    ]

    def validate(self, inputs):
        return True

    def execute(self, context: OperatorContext, inputs, params) -> OperatorResult:
        import pandas as pd

        from app.services.closed_loop_actions import (
            append_rows_to_dataset_artifact,
            json_value,
        )
        artifact_id = str(params.get("dataset_artifact_id") or "").strip()
        if not artifact_id:
            raise RuntimeError("dataset_artifact_id is required")
        if context.artifact_service is None or not context.project_id:
            raise RuntimeError("Artifact service and project context are required")
        rows = inputs.get("data")
        if rows is None:
            rows = []
        if isinstance(rows, dict):
            rows = [rows]
        frame = rows if isinstance(rows, pd.DataFrame) else pd.DataFrame(rows)
        records = json_value(frame.to_dict(orient="records"))
        artifact = context.artifact_service.resolve(
            artifact_id, context.project_id, expected_type="dataset",
        )
        total = append_rows_to_dataset_artifact(
            context.artifact_service.db, context.artifact_service, artifact, records,
        )
        return OperatorResult(
            outputs={"data": records},
            metrics={"total_rows": float(total)},
        )


@register_operator
class NotifyAdminsOperator(BaseOperator):
    id = "notify_admins"
    name = "Notify Admins"
    category = "closed_loop"
    description = ("Send an in-app notification to the project owner and platform "
                   "admins; optional row threshold notifies once per N accumulated "
                   "error rows instead of on every reflow")
    inputs = [PortSpec("data", "DataTable", "Trigger Rows")]
    outputs = [PortSpec("data", "DataTable", "Trigger Rows")]
    parameters = [
        ParamSpec("title", "str", "", "Notification Title", required=True),
        ParamSpec("message", "str", "", "Notification Body", required=True),
        ParamSpec("severity", "select", "warning", "Severity",
                  options=["info", "warning", "critical"]),
        ParamSpec("threshold_rows", "int", 1, "Notify Every N Error Rows (1 = always)", range_min=1),
        ParamSpec("error_dataset_artifact_id", "str", "",
                  "Error Dataset Artifact ID (accumulation counter; empty = always notify)"),
    ]

    def validate(self, inputs):
        return True

    def execute(self, context: OperatorContext, inputs, params) -> OperatorResult:
        from app.services.closed_loop_actions import notify_project_admins
        rows = inputs.get("data")
        if rows is None:
            rows = []
        if isinstance(rows, dict):
            rows = [rows]
        count = len(rows)
        title = str(params.get("title") or "").strip() or "闭环流程通知"
        body = str(params.get("message") or "").strip() or f"闭环流程触发（{count} 行）"
        if context.artifact_service is None or not context.project_id:
            raise RuntimeError("Artifact service and project context are required")
        # 阈值节流：按报错数据集累计行数（上游回流已落库，row_count 含本次），
        # 每满 N 行通知一次；未配置数据集或 N=1 时保持每行通知的旧行为。
        threshold = max(1, int(params.get("threshold_rows") or 1))
        dataset_id = str(params.get("error_dataset_artifact_id") or "").strip()
        total = None
        if threshold > 1 and dataset_id:
            artifact = context.artifact_service.resolve(
                dataset_id, context.project_id, expected_type="dataset",
            )
            total = int((artifact.metadata_ or {}).get("row_count", 0))
            if total % threshold != 0:
                return OperatorResult(
                    outputs={"data": rows if isinstance(rows, list) else [rows]},
                    metrics={"notified": 0.0, "total_rows": float(total),
                             "threshold_rows": float(threshold)},
                )
            body = f"{body}（累计 {total} 行报错）"
        sent = notify_project_admins(
            context.artifact_service.db,
            context.project_id,
            title=title,
            body=body,
            severity=str(params.get("severity") or "warning"),
            event_type="closed_loop.notify",
            payload={"rows": count, "total_rows": total},
        )
        return OperatorResult(
            outputs={"data": rows if isinstance(rows, list) else [rows]},
            metrics={"recipients": float(sent), "notified": 1.0,
                     "total_rows": float(total) if total is not None else float(count),
                     "threshold_rows": float(threshold)},
        )


@register_operator
class RetrainThresholdOperator(BaseOperator):
    id = "retrain_threshold"
    name = "Retrain Threshold"
    category = "closed_loop"
    description = ("Trigger AutoML retraining once the accumulated dataset "
                   "reaches the row threshold; completes the model swap on a "
                   "later invoke when the job finishes")
    inputs = [PortSpec("data", "DataTable", "Accumulated Rows")]
    outputs = [
        PortSpec("triggered", "DataTable", "Triggered"),
        PortSpec("continue", "DataTable", "Below Threshold"),
    ]
    parameters = [
        ParamSpec("dataset_artifact_id", "str", "", "Accumulated Dataset Artifact ID", required=True),
        ParamSpec("retrain_dataset_artifact_id", "str", "", "Retrain Dataset Artifact ID", required=True),
        ParamSpec("retrain_target_column", "str", "", "Retrain Target Column", required=True),
        ParamSpec("threshold_rows", "int", 12, "Threshold Rows", range_min=1),
        ParamSpec("retrain_max_trials", "int", 10, "Max Trials", range_min=5),
        ParamSpec("swap_deployment_id", "str", "", "Deployment ID to swap after completion"),
    ]

    def validate(self, inputs):
        return True

    def execute(self, context: OperatorContext, inputs, params) -> OperatorResult:
        from app.models.training import TrainingJob
        from app.services.closed_loop_actions import (
            complete_retrain_swap,
            trigger_retrain_job,
        )
        artifact_id = str(params.get("dataset_artifact_id") or "").strip()
        target_column = str(params.get("retrain_target_column") or "").strip()
        threshold = max(1, int(params.get("threshold_rows") or 12))
        if not artifact_id:
            raise RuntimeError("dataset_artifact_id is required")
        if not target_column:
            raise RuntimeError("retrain_target_column is required")
        if context.artifact_service is None or not context.project_id:
            raise RuntimeError("Artifact service and project context are required")
        db = context.artifact_service.db
        artifact = context.artifact_service.resolve(
            artifact_id, context.project_id, expected_type="dataset",
        )
        meta = dict(artifact.metadata_ or {})
        total = int(meta.get("row_count", 0))
        # Rolling cycle base: accumulated rows since the last swap/trigger.
        cycle_base = int(meta.get("cycle_base", 0))

        def _save_meta():
            artifact.metadata_ = meta
            db.commit()

        # Advance a pending retrain cycle: swap the deployment once its AutoML
        # job completed (state lives on the dataset artifact metadata).
        job_id = meta.get("retrain_job_id")
        if job_id:
            try:
                job = db.query(TrainingJob).filter(
                    TrainingJob.id == uuid.UUID(str(job_id)),
                ).first()
            except (TypeError, ValueError, AttributeError):
                job = None
            if job is None or job.status == "failed":
                meta["retrain_job_id"] = None
                meta["retrain_failed"] = True
                _save_meta()
            elif job.status == "completed" and not meta.get("swapped_model_version_id"):
                if not context.operator_id:
                    raise RuntimeError("operator context lacks an actor id")
                version = complete_retrain_swap(
                    db,
                    deployment_id=params.get("swap_deployment_id") or None,
                    job=job,
                    actor_id=context.operator_id,
                    model_name="编排闭环-自动模型",
                )
                meta["retrain_job_id"] = None
                if version is not None:
                    meta["swapped_model_version_id"] = str(version.id)
                meta["cycle_base"] = total
                _save_meta()

        pending = bool(meta.get("retrain_job_id"))
        # Recalculate cycle_rows AFTER the swap block (which updates cycle_base).
        cycle_base = int(meta.get("cycle_base", 0))
        cycle_rows = total - cycle_base
        triggered_row = {"triggered": False, "total_rows": total,
                         "cycle_rows": cycle_rows, "threshold_rows": threshold}
        continue_row = {"total_rows": total, "remaining": max(0, threshold - cycle_rows)}
        if not pending and cycle_rows >= threshold:
            if not context.operator_id:
                raise RuntimeError("operator context lacks an actor id")
            # 绑定表以 experiment_id 为主键，且重训幂等指纹含实验名；图重新
            # 发布后 total 会重置，实验名必须带周期 token 防止冲突与重放。
            cycle = uuid.uuid4().hex[:8]
            job = trigger_retrain_job(
                db,
                project_id=context.project_id,
                actor_id=context.operator_id,
                experiment_name=f"编排闭环-{total}-{cycle}",
                job_name=f"编排闭环-自动建模-{total}-{cycle}",
                dataset_artifact_id=params.get("retrain_dataset_artifact_id") or artifact.id,
                target_column=target_column,
                max_trials=int(params.get("retrain_max_trials") or 10),
            )
            meta["retrain_job_id"] = str(job.id)
            meta["cycle_base"] = total
            _save_meta()
            triggered_row["triggered"] = True
            triggered_row["job_id"] = str(job.id)
        return OperatorResult(
            outputs={"triggered": [triggered_row], "continue": [continue_row]},
            metrics={"total_rows": float(total)},
        )
