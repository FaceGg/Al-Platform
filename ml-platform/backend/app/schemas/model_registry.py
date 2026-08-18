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


class ApiKeyCreate(StrictSchema):
    scopes: list[Literal["inference.predict"]] = Field(min_length=1, max_length=1)
    expires_at: datetime | None = None


class MetricQuery(StrictSchema):
    since: datetime
    until: datetime
    page: StrictInt = Field(default=1, ge=1)
    page_size: StrictInt = Field(default=100, ge=1, le=200)


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
    duration_ms: StrictFloat | StrictInt
