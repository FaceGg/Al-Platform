"""Strict public contracts for model registry and inference operations."""

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictFloat, StrictInt, StrictStr


class StrictSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RegisteredModelCreate(StrictSchema):
    name: StrictStr = Field(min_length=1, max_length=128)
    description: StrictStr = Field(default="", max_length=4096)


class FeatureField(StrictSchema):
    name: StrictStr = Field(min_length=1, max_length=128)
    dtype: StrictStr = Field(min_length=1, max_length=64)


class OutputSchema(StrictSchema):
    name: StrictStr = Field(min_length=1, max_length=128)
    dtype: StrictStr = Field(min_length=1, max_length=64)
    task: Literal["classification", "regression"]


class PlatformVersionCreate(StrictSchema):
    source_kind: Literal["platform_joblib"]
    source_model_library_id: UUID


class OnnxVersionCreate(StrictSchema):
    source_kind: Literal["onnx_artifact"]
    source_artifact_id: UUID
    feature_schema: list[FeatureField] = Field(min_length=1, max_length=1024)
    output_schema: OutputSchema


VersionCreate = Annotated[
    PlatformVersionCreate | OnnxVersionCreate,
    Field(discriminator="source_kind"),
]


class LifecycleComment(StrictSchema):
    comment: StrictStr = Field(default="", max_length=2048)


class DeploymentCreate(StrictSchema):
    name: StrictStr = Field(min_length=1, max_length=128)
    model_version_id: UUID


RecordValue = StrictStr | StrictInt | StrictFloat | StrictBool


class PredictRequest(StrictSchema):
    records: list[dict[str, RecordValue]] = Field(min_length=1, max_length=100)


class TargetCreate(StrictSchema):
    model_version_id: UUID
    weight_bps: StrictInt = Field(ge=0, le=10000)


class RolloutCreate(StrictSchema):
    targets: list[TargetCreate] = Field(min_length=1, max_length=100)
    strategy: Literal["immediate", "canary", "rolling"] = "canary"
    step_schedule: list[StrictInt] | None = Field(default=None, min_length=2, max_length=32)
    max_error_rate: StrictFloat | None = Field(default=None, ge=0, le=1)
    max_p95_ms: StrictFloat | None = Field(default=None, ge=0)


class RolloutCommand(StrictSchema):
    expected_lock_version: StrictInt | None = Field(default=None, ge=1)


class DeviceRecalibrateRequest(StrictSchema):
    """新设备重标定（技术方案 §7.2，三期 M9）：只重跑标定层，不动检测器主体。"""
    calibration_artifact_id: UUID
    condition_value: StrictStr = Field(min_length=1, max_length=128)
    contamination: StrictFloat | None = Field(default=None, gt=0, le=0.5)


class FleetShardCreate(StrictSchema):
    """迁移版本挂载为部署分片 target（§7.1.4，三期 M9）。"""
    model_version_id: UUID
    condition_value: StrictStr = Field(min_length=1, max_length=128)
    weight_bps: StrictInt | None = Field(default=None, ge=0, le=10000)
    # 挂载使用的工况列（§7.1.3：device_id 作为 condition_column 的一等应用）。
    # 部署已有工况列时必须与之一致，否则挂载出的分片永不被 ConditionValueRouter
    # 命中（不可达分片）——服务端据此 fail-closed 报
    # FLEET_SHARD_CONDITION_COLUMN_MISMATCH。留空=沿用部署现有工况列；部署
    # 无工况列时服务端落此值（缺省 device_id）。
    condition_column: StrictStr | None = Field(default=None, min_length=1, max_length=128)


class LabelRecalibrateRequest(StrictSchema):
    """M6 半监督档 1 标签阈值重标定（技术方案 §6.2）：不动检测器主体，
    用 confirmed/false_alarm 标签分布的加权损失最优阈值注册新版本。"""

    labeled_artifact_id: UUID
    feedback_marks: dict | None = None
    positive_label: StrictStr = Field(default="fault", min_length=1, max_length=64)


class DerivedSupervisedDatasetRequest(StrictSchema):
    """弱监督演进派生导出（技术方案 §2.3.3）：回流行带标签导出为监督数据集。"""

    labeled_artifact_id: UUID
    positive_label: StrictStr = Field(default="fault", min_length=1, max_length=64)


class ApiKeyCreate(StrictSchema):
    scopes: list[Literal["inference.predict"]] = Field(min_length=1, max_length=1)
    expires_at: datetime | None = None


class MetricQuery(StrictSchema):
    since: datetime
    until: datetime
    # 查询参数恒为字符串，StrictInt 会拒收 "1"（发布运维抽屉 422 的根因），
    # 分页字段用普通 int 走宽泛转换。
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=100, ge=1, le=200)


class RequestLogQuery(MetricQuery):
    pass


class ModelCardGuidanceUpdate(StrictSchema):
    operational_guidance: StrictStr = Field(max_length=16000)


class ProductionPredictRequest(StrictSchema):
    records: list[dict[str, RecordValue]] = Field(min_length=1, max_length=10000)


class ProductionPredictResponse(StrictSchema):
    request_id: StrictStr
    deployment_id: StrictStr
    revision_id: StrictStr
    model_version_id: StrictStr
    version_number: StrictInt
    predictions: list[object] | None = None
    probabilities: list[object] | None = None
    # 无监督（anomaly 部署）三要素（技术方案 §3.5）：非 anomaly 部署恒 None
    anomaly_score: list[object] | None = None
    is_anomaly: list[object] | None = None
    top_contributors: list[object] | None = None
    duration_ms: StrictFloat | StrictInt
