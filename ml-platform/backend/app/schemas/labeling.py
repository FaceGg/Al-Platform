import re
import uuid
import math
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class LabelColumnCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    machine_key: str = Field(min_length=1, max_length=128)
    display_name: str = Field(min_length=1, max_length=256)
    value_type: Literal["int", "float", "string"]
    required: bool = False
    enum_values: list[int | float | str] = Field(default_factory=list)
    min_value: int | float | None = None
    max_value: int | float | None = None
    max_length: int | None = Field(default=None, ge=1, le=65536)

    @field_validator("machine_key")
    @classmethod
    def validate_key(cls, value: str) -> str:
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", value):
            raise ValueError("machine_key must be an identifier")
        return value

    @model_validator(mode="after")
    def validate_constraints(self):
        if self.value_type != "string" and self.max_length is not None:
            raise ValueError("max_length only applies to strings")
        if self.value_type == "string" and (self.min_value is not None or self.max_value is not None):
            raise ValueError("range constraints only apply to numeric labels")
        if self.value_type == "string" and any(not isinstance(value, str) for value in self.enum_values):
            raise ValueError("string enum values must be strings")
        if self.value_type == "int":
            numeric_constraints = [*self.enum_values, self.min_value, self.max_value]
            if any(value is not None and (isinstance(value, bool) or not isinstance(value, int)) for value in numeric_constraints):
                raise ValueError("integer constraints must contain exact integers")
        if self.value_type == "float":
            numeric_constraints = [*self.enum_values, self.min_value, self.max_value]
            if any(
                value is not None and (
                    isinstance(value, bool)
                    or not isinstance(value, (int, float))
                    or not math.isfinite(float(value))
                )
                for value in numeric_constraints
            ):
                raise ValueError("float constraints must contain finite numbers")
        if self.min_value is not None and self.max_value is not None and self.min_value > self.max_value:
            raise ValueError("min_value must not exceed max_value")
        return self


class LabelSchemaCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    project_id: uuid.UUID
    name: str = Field(min_length=1, max_length=128)
    columns: list[LabelColumnCreate] = Field(min_length=1, max_length=64)

    @field_validator("columns")
    @classmethod
    def unique_columns(cls, value):
        keys = [item.machine_key for item in value]
        if len(keys) != len(set(keys)):
            raise ValueError("label column keys must be unique")
        return value


class LabelRevisionWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")
    values: dict[str, int | float | str | None]
    base_revision: int = Field(ge=0)
