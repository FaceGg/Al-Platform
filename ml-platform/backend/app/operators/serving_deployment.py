"""Deployment-bound model loading for serving graphs (spec v0.9 §12.2/§12.3).

``load_deployment_model`` binds an inference deployment id and resolves the
CURRENT joblib artifact at invoke time. Closed-loop retrain swaps rotate
``deployments.model_version_id``; serving graphs bound to a deployment follow
the swap without republishing. Static ``model_artifact_id`` binding stays
available for frozen snapshots.

Execution reuses the sealed-artifact loading contract: artifact access goes
through the project-scoped ArtifactService resolve, and the platform seal
(Mimosa 2026-11-03) is verified before deserialization.
"""
from __future__ import annotations

import io

import joblib

from app.engine.base_operator import BaseOperator, PortSpec, ParamSpec
from app.engine.operator_contract import OperatorContext, OperatorResult
from app.engine.registry import register_operator
from app.services.model_artifact_sealing import seal_is_valid


@register_operator
class LoadDeploymentModelOperator(BaseOperator):
    id = "load_deployment_model"
    name = "Load Deployment Model"
    category = "closed_loop"
    description = (
        "Bind an inference deployment and load its CURRENT joblib model "
        "(follows closed-loop retrain swaps without republishing)"
    )
    inputs = []
    outputs = [PortSpec("model", "Model", "Loaded Model")]
    parameters = [
        ParamSpec(
            "deployment_id", "str", "",
            "Inference Deployment ID", required=True,
        ),
        ParamSpec(
            "model_artifact_id", "str", "",
            "Model Artifact ID (static fallback)", required=False,
        ),
    ]

    def validate(self, inputs):
        return True

    @staticmethod
    def _current_artifact_id(context: OperatorContext, params) -> str:
        import uuid as _uuid

        from app.models.model_library import ModelLibrary
        from app.models.model_registry import InferenceDeployment, ModelVersion

        deployment_id = str(params.get("deployment_id") or "").strip()
        if not deployment_id:
            # 无 deployment 绑定时回退静态工件绑定
            return str(params.get("model_artifact_id") or "").strip()
        try:
            deployment_uuid = _uuid.UUID(deployment_id)
        except (TypeError, ValueError) as error:
            raise RuntimeError(
                f"deployment_id 不是合法 UUID: {deployment_id!r}"
            ) from error
        db = context.artifact_service.db
        deployment = (
            db.query(InferenceDeployment)
            .filter(
                InferenceDeployment.id == deployment_uuid,
                InferenceDeployment.project_id == context.project_id,
            )
            .first()
        )
        if deployment is None:
            raise RuntimeError(
                f"当前项目内找不到该推理部署: {deployment_id}"
            )
        version = (
            db.query(ModelVersion)
            .filter(ModelVersion.id == deployment.model_version_id)
            .first()
        )
        if version is None or version.source_model_library_id is None:
            raise RuntimeError(
                "部署当前模型版本没有平台 joblib 源；请改用静态 model_artifact_id 绑定"
            )
        library = (
            db.query(ModelLibrary)
            .filter(ModelLibrary.id == version.source_model_library_id)
            .first()
        )
        if library is None or not library.model_artifact_id:
            raise RuntimeError("部署模型库条目缺少 joblib 工件")
        return str(library.model_artifact_id)

    def execute(self, context: OperatorContext, inputs, params) -> OperatorResult:
        if context.artifact_service is None or not context.project_id:
            raise RuntimeError("Artifact service and project context are required")
        artifact_id = self._current_artifact_id(context, params)
        if not artifact_id:
            raise RuntimeError(
                "deployment_id（或回退 model_artifact_id）必填"
            )
        try:
            artifact = context.artifact_service.resolve(
                artifact_id, context.project_id, expected_type="model",
            )
            with context.artifact_service.storage.open(artifact.storage_uri) as handle:
                payload = handle.read()
        except Exception as error:
            raise RuntimeError(f"模型工件加载失败: {error}") from error
        artifact_metadata = getattr(artifact, "metadata_", None) or {}
        if not seal_is_valid(
            artifact_metadata,
            str(artifact_metadata.get("sha256") or ""),
        ):
            raise RuntimeError(
                "MODEL_SEAL_INVALID: 模型工件缺少平台密封标签或标签与内容不符"
                "（仅平台训练产物可加载）"
            )
        try:
            loaded = joblib.load(io.BytesIO(payload))
        except Exception as error:
            raise RuntimeError(
                f"部署当前模型工件无法按 joblib 反序列化: {error}"
            ) from error
        model = loaded
        if isinstance(loaded, dict):
            package = loaded
            for key in ("model", "estimator", "clf", "pipeline", "best_model"):
                candidate = package.get(key)
                if candidate is not None and hasattr(candidate, "predict"):
                    model = candidate
                    break
            else:
                raise RuntimeError(
                    "模型工件是打包字典但不含可 predict 的估计器"
                    "（期望键 model/estimator/clf/pipeline/best_model）"
                )
        if not hasattr(model, "predict"):
            raise RuntimeError("加载的对象没有 predict 方法，不能作为模型端口输出")
        return OperatorResult(
            outputs={"model": model, "model_artifact_id": artifact_id},
        )