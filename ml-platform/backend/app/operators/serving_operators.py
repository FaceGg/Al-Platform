# -*- coding: utf-8 -*-
"""Serving-path operators for orchestration APIs published from workflows.

`api_input` receives the single record injected by the invoke endpoint;
`load_model_artifact` binds a frozen trained-model artifact so the serving
graph never retrains per row (training stays in the training workflow).
"""
import io
import joblib
import uuid

from app.engine.operator_contract import OperatorContext, OperatorResult
from app.engine.base_operator import BaseOperator, PortSpec, ParamSpec
from app.engine.registry import register_operator


@register_operator
class ApiInputOperator(BaseOperator):
    id = "api_input"
    name = "API Input"
    category = "io"
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
    category = "ml"
    description = "Load a frozen trained-model artifact for serving"
    inputs = []
    outputs = [PortSpec("model", "Model", "Loaded Model")]
    parameters = [
        ParamSpec("model_artifact_id", "str", "", "Model Artifact ID", required=True),
    ]

    def validate(self, inputs):
        return True

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
        loaded = joblib.load(io.BytesIO(payload))
        if isinstance(loaded, dict):
            # Model-library/AutoML artifacts package the estimator inside a
            # metadata dict; unwrap it for apply_model.
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
    category = "io"
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
    category = "io"
    description = "Send an in-app notification to the project owner and platform admins"
    inputs = [PortSpec("data", "DataTable", "Trigger Rows")]
    outputs = [PortSpec("data", "DataTable", "Trigger Rows")]
    parameters = [
        ParamSpec("title", "str", "", "Notification Title", required=True),
        ParamSpec("message", "str", "", "Notification Body", required=True),
        ParamSpec("severity", "select", "warning", "Severity",
                  options=["info", "warning", "critical"]),
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
        sent = notify_project_admins(
            context.artifact_service.db,
            context.project_id,
            title=title,
            body=body,
            severity=str(params.get("severity") or "warning"),
            event_type="closed_loop.notify",
            payload={"rows": count},
        )
        return OperatorResult(
            outputs={"data": rows if isinstance(rows, list) else [rows]},
            metrics={"recipients": float(sent)},
        )


@register_operator
class RetrainThresholdOperator(BaseOperator):
    id = "retrain_threshold"
    name = "Retrain Threshold"
    category = "control"
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
            job = trigger_retrain_job(
                db,
                project_id=context.project_id,
                actor_id=context.operator_id,
                experiment_name=f"编排闭环-{total}",
                job_name=f"编排闭环-自动建模-{total}",
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
