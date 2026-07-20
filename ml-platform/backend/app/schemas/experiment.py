from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ExperimentCreate(BaseModel):
    project_id: UUID
    name: str = Field(min_length=1, max_length=128)
    description: str = Field(default="", max_length=4096)

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Experiment name must not be empty")
        return normalized


class ExperimentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    project_id: UUID
    created_by: UUID
    name: str
    description: str
    mlflow_experiment_id: str
    created_at: datetime
    updated_at: datetime
    run_count: int = 0


class ExperimentList(BaseModel):
    items: list[ExperimentResponse]
    total: int


class RunCompareRequest(BaseModel):
    run_ids: list[str] = Field(min_length=2, max_length=10)

    @field_validator("run_ids")
    @classmethod
    def require_unique_runs(cls, values: list[str]) -> list[str]:
        normalized = [value.strip() for value in values]
        if any(not value for value in normalized):
            raise ValueError("Run IDs must not be empty")
        if len(normalized) != len(set(normalized)):
            raise ValueError("Run IDs must be unique")
        return normalized


class RunList(BaseModel):
    items: list[dict[str, Any]]
    total: int
    offset: int
    limit: int


class RunComparison(BaseModel):
    run_ids: list[str]
    param_names: list[str]
    metric_names: list[str]
    runs: list[dict[str, Any]]
