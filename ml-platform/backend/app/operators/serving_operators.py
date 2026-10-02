# -*- coding: utf-8 -*-
"""Serving-path operators for orchestration APIs published from workflows.

`api_input` receives the single record injected by the invoke endpoint;
`load_model_artifact` binds a frozen trained-model artifact so the serving
graph never retrains per row (training stays in the training workflow).
"""
import io
import joblib

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
