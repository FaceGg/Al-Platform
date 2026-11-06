"""LLMProfile API schemas (AutoML Agent plan, Task A1.2)."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from app.services.llm_gateway import validate_llm_api_url


class LLMProfileCreate(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    # API 格式：openai_compatible=Chat Completions（存量） / responses / anthropic
    provider: str = Field(default="openai_compatible", pattern="^(openai_compatible|responses|anthropic|custom)$")
    api_url: str = Field(min_length=1, max_length=512)
    api_key: str | None = Field(default=None, max_length=4096)
    model_id: str = Field(min_length=1, max_length=128)
    temperature: float | None = Field(default=None, ge=0, le=2)
    max_tokens: int | None = Field(default=None, ge=1)
    timeout_seconds: int = Field(default=60, ge=1, le=600)
    purpose_tags: list[str] = Field(default_factory=list)
    deployment: str = Field(default="cloud", pattern="^(cloud|private)$")
    is_default: bool = False
    enabled: bool = True
    model_config_json: dict | None = None

    @field_validator("api_url")
    @classmethod
    def _url_hardened(cls, value: str) -> str:
        validate_llm_api_url(value)
        return value


class LLMModelListRequest(BaseModel):
    """「获取模型列表」代理：用表单里的 URL/Key 拉上游模型目录。"""

    api_url: str = Field(min_length=1, max_length=512)
    api_key: str | None = Field(default=None, max_length=4096)
    provider: str = Field(default="openai_compatible", pattern="^(openai_compatible|responses|anthropic)$")
    profile_id: UUID | None = None  # 编辑档案时 Key 留空 → 复用已存 Key

    @field_validator("api_url")
    @classmethod
    def _url_hardened(cls, value: str) -> str:
        validate_llm_api_url(value)
        return value


class LLMProfileUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=64)
    provider: str | None = Field(default=None, pattern="^(openai_compatible|responses|anthropic|custom)$")
    api_url: str | None = Field(default=None, min_length=1, max_length=512)
    api_key: str | None = Field(default=None, max_length=4096)
    model_id: str | None = Field(default=None, min_length=1, max_length=128)
    temperature: float | None = Field(default=None, ge=0, le=2)
    max_tokens: int | None = Field(default=None, ge=1)
    timeout_seconds: int | None = Field(default=None, ge=1, le=600)
    purpose_tags: list[str] | None = None
    deployment: str | None = Field(default=None, pattern="^(cloud|private)$")
    is_default: bool | None = None
    enabled: bool | None = None
    model_config_json: dict | None = None
    model_config_json: dict | None = None
    enabled: bool | None = None

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
    enabled: bool
    model_config_json: dict | None
    api_key_masked: str | None
    created_at: datetime
    updated_at: datetime


class LLMProfileConnectivity(BaseModel):
    ok: bool
    status_code: int | None
    latency_ms: float | None
    error: str | None


class LLMProfileClone(BaseModel):
    """从源档案克隆新模型：复制 URL/格式/Key 等全部配置，仅替换模型与名称
    （供应商自动获取目录后「一键添加候选模型」用——前端只有掩码，无法自填 Key）。"""

    model_id: str = Field(min_length=1, max_length=128)
    name: str | None = Field(default=None, max_length=128)
    model_config_json: dict | None = Field(default=None)
