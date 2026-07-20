"""Strict public contracts for model registry and inference operations."""

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
