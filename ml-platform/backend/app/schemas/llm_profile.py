"""LLMProfile API schemas (AutoML Agent plan, Task A1.2)."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from app.services.llm_gateway import validate_llm_api_url


class LLMProfileCreate(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    provider: str = Field(default="openai_compatible", pattern="^(openai_compatible|custom)$")
    api_url: str = Field(min_length=1, max_length=512)
    api_key: str | None = Field(default=None, max_length=4096)
    model_id: str = Field(min_length=1, max_length=128)
    temperature: float | None = Field(default=None, ge=0, le=2)
    max_tokens: int | None = Field(default=None, ge=1)
    timeout_seconds: int = Field(default=60, ge=1, le=600)
    purpose_tags: list[str] = Field(default_factory=list)
    deployment: str = Field(default="cloud", pattern="^(cloud|private)$")
    is_default: bool = False

    @field_validator("api_url")
    @classmethod
    def _url_hardened(cls, value: str) -> str:
        validate_llm_api_url(value)
        return value


class LLMProfileUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=64)
    provider: str | None = Field(default=None, pattern="^(openai_compatible|custom)$")
    api_url: str | None = Field(default=None, min_length=1, max_length=512)
    api_key: str | None = Field(default=None, max_length=4096)
    model_id: str | None = Field(default=None, min_length=1, max_length=128)
    temperature: float | None = Field(default=None, ge=0, le=2)
    max_tokens: int | None = Field(default=None, ge=1)
    timeout_seconds: int | None = Field(default=None, ge=1, le=600)
    purpose_tags: list[str] | None = None
    deployment: str | None = Field(default=None, pattern="^(cloud|private)$")
    is_default: bool | None = None

    @field_validator("api_url")
    @classmethod
    def _url_hardened(cls, value: str | None) -> str | None:
        if value is not None:
            validate_llm_api_url(value)
        return value


class LLMProfileOut(BaseModel):
    id: UUID
    name: str
    provider: str
    api_url: str
    model_id: str
    temperature: float | None
    max_tokens: int | None
    timeout_seconds: int
    purpose_tags: list[str]
    deployment: str
    is_default: bool
    api_key_masked: str | None
    created_at: datetime
    updated_at: datetime


class LLMProfileConnectivity(BaseModel):
    ok: bool
    status_code: int | None
    latency_ms: float | None
    error: str | None
