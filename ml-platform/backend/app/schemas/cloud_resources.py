"""Strict contracts for Week 13 Kubernetes foundation API."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

ClusterStatus = Literal["pending", "active", "connectivity_failed", "disabled"]


class ClusterCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: UUID
    name: str = Field(min_length=1, max_length=64)
    display_name: str = Field(default="", max_length=128)
    api_server_url: str = Field(min_length=1, max_length=2083)
    secret_ref: str = Field(min_length=1, max_length=255)
    insecure_tls: bool = False
    provider: str = Field(default="generic", max_length=32)
    default_namespace: str | None = Field(default=None, max_length=63)


class ClusterUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    display_name: str | None = Field(default=None, max_length=128)
    api_server_url: str | None = Field(default=None, max_length=2083)
    secret_ref: str | None = Field(default=None, max_length=255)
    insecure_tls: bool | None = None
    default_namespace: str | None = Field(default=None, max_length=63)


class ClusterResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    project_id: UUID
    name: str
    display_name: str
    api_server_url: str
    insecure_tls: bool
    provider: str
    kubernetes_version: str | None = None
    default_namespace: str | None = None
    status: ClusterStatus
    last_check_status: str | None = None
    last_check_error_code: str | None = None
    last_check_message: str | None = None
    last_checked_at: datetime | None = None
    last_check_latency_ms: int | None = None
    stale: bool = False
    secret_ref: str | None = None
    created_at: datetime | None = None


class ConnectivityCheckResponse(BaseModel):
    check_status: Literal["ok", "failed"]
    error_code: str | None = None
    latency_ms: int
    checked_at: datetime | None = None
    kubernetes_version: str | None = None


class NamespaceEnsureRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    quota_json: dict | None = None


class NamespaceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    cluster_id: UUID
    project_id: UUID
    name: str
    status: str
    quota_cpu_millicores: int | None = None
    quota_memory_mb: int | None = None
    quota_json: dict | None = None
    last_synced_at: datetime | None = None


class ResourceGroupCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cluster_id: UUID
    name: str = Field(min_length=1, max_length=64)
    description: str = Field(default="", max_length=255)
    scheduling_policy_json: dict = Field(default_factory=dict)
    quota_json: dict = Field(default_factory=dict)


class ResourceGroupUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    description: str | None = Field(default=None, max_length=255)
    quota_json: dict | None = None
    status: Literal["active", "disabled"] | None = None


class ResourceGroupResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    cluster_id: UUID
    project_id: UUID
    name: str
    description: str
    scheduling_policy_json: dict
    quota_json: dict
    status: str
    created_at: datetime | None = None
