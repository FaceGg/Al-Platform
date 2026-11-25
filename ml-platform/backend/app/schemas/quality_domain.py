"""Strict public contracts for the quality domain (scene / station / spec-limit).

技术方案 §2.2：field_roles 角色键合法性、规格 statistic 枚举（DB CHECK +
pydantic 双层）、绑定部署时 condition_column 一致性（一致性校验在 API 层，
需要查库，不进契约层）。
"""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models.quality_domain import FIELD_ROLE_KEYS, SPEC_STATISTICS

FieldRoleKey = Literal[
    "sample_key", "product", "batch", "shift", "collected_at", "time",
    "group", "target", "feature", "ignore", "waveform", "condition",
]

SpecStatistic = Literal["value", "mean", "min", "max", "rms"]


def validate_field_roles(raw: object) -> dict[str, str]:
    """Validate a {role: column} mapping; raise ValueError on any violation."""
    if not isinstance(raw, dict):
        raise ValueError("field_roles must be an object of {role: column}")
    if len(raw) > 32:
        raise ValueError("field_roles supports at most 32 roles")
    invalid_keys = set(raw) - set(FIELD_ROLE_KEYS)
    if invalid_keys:
        raise ValueError(
            f"unknown field role(s): {', '.join(sorted(map(str, invalid_keys)))}"
        )
    seen_columns: set[str] = set()
    for role, column in raw.items():
        if not isinstance(column, str) or not column.strip():
            raise ValueError(f"field role {role} must map to a non-empty column name")
        if len(column) > 256:
            raise ValueError(f"field role {role} column name too long (max 256)")
        if column in seen_columns:
            raise ValueError(
                f"column {column} cannot carry multiple roles"
            )
        seen_columns.add(column)
    return {str(role): column.strip() for role, column in raw.items()}


def _statistic_literal(statistic: object) -> str:
    if statistic not in SPEC_STATISTICS:
        raise ValueError(f"statistic must be one of {', '.join(SPEC_STATISTICS)}")
    return str(statistic)


class QualitySceneCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=128)
    description: str | None = Field(default=None, max_length=4000)
    deployment_id: str | None = None
    condition_column: str | None = Field(default=None, max_length=128)
    field_roles: dict[str, str] = Field(default_factory=dict)
    waveform_column: str | None = Field(default=None, max_length=256)

    @field_validator("field_roles")
    @classmethod
    def _check_field_roles(cls, value):
        return validate_field_roles(value)


class QualitySceneUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=128)
    description: str | None = Field(default=None, max_length=4000)
    deployment_id: str | None = None
    condition_column: str | None = Field(default=None, max_length=128)
    waveform_column: str | None = Field(default=None, max_length=256)


class QualitySceneFieldRoles(BaseModel):
    """整体替换语义（PUT）；空对象 = 清空全部角色。"""

    model_config = ConfigDict(extra="forbid")

    field_roles: dict[str, str] = Field(default_factory=dict)

    @field_validator("field_roles")
    @classmethod
    def _check_field_roles(cls, value):
        return validate_field_roles(value)


class QualityStationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=128)
    description: str | None = Field(default=None, max_length=4000)
    scene_id: str
    factory: str | None = Field(default=None, max_length=128)
    workshop: str | None = Field(default=None, max_length=128)
    production_line: str | None = Field(default=None, max_length=128)
    edge_device_id: str | None = None
    responsible_user_id: str | None = None
    enabled: bool = True


class QualityStationUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=128)
    description: str | None = Field(default=None, max_length=4000)
    scene_id: str | None = None
    factory: str | None = Field(default=None, max_length=128)
    workshop: str | None = Field(default=None, max_length=128)
    production_line: str | None = Field(default=None, max_length=128)
    edge_device_id: str | None = None
    responsible_user_id: str | None = None
    enabled: bool | None = None


class QualitySpecLimitCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    field: str = Field(min_length=1, max_length=256)
    statistic: SpecStatistic = "value"
    usl: float | None = None
    lsl: float | None = None
    target: float | None = None
    unit: str | None = Field(default=None, max_length=32)

    @model_validator(mode="after")
    def _check_bounds(self):
        if self.usl is not None and self.lsl is not None and self.usl < self.lsl:
            raise ValueError("usl must be greater than or equal to lsl")
        return self


class QualitySpecLimitUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    statistic: SpecStatistic | None = None
    usl: float | None = None
    lsl: float | None = None
    target: float | None = None
    unit: str | None = Field(default=None, max_length=32)

    @model_validator(mode="after")
    def _check_bounds(self):
        if self.usl is not None and self.lsl is not None and self.usl < self.lsl:
            raise ValueError("usl must be greater than or equal to lsl")
        return self
