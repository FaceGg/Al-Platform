"""Quality alert API schemas (补齐路线第一批 F2a, 技术方案 §9.7)."""
from __future__ import annotations

import uuid

from pydantic import BaseModel, Field, field_validator, model_validator


ALLOWED_DISPOSITION_FIELDS = {
    "type",
    "cause",
    "action",
    "downtime",
    "rework",
    "expanded_inspection",
}


class AlertSettingsUpdate(BaseModel):
    """场景级预警规则（D14）；触发下限独立于分级阈值。"""

    trigger_threshold: float | None = Field(default=None, ge=0.0, le=1.0)
    high_threshold: float | None = Field(default=None, ge=0.0, le=1.0)
    critical_threshold: float | None = Field(default=None, ge=0.0, le=1.0)
    sla_hours: int | None = Field(default=None, ge=1, le=720)
    merge_window_minutes: int | None = Field(default=None, ge=1, le=1440)

    @model_validator(mode="after")
    def _threshold_order(self):
        pairs = [
            ("trigger", self.trigger_threshold),
            ("high", self.high_threshold),
            ("critical", self.critical_threshold),
        ]
        present = [(name, value) for name, value in pairs if value is not None]
        for (lower_name, lower), (upper_name, upper) in zip(present, present[1:]):
            if lower > upper:
                raise ValueError(
                    f"{lower_name}_threshold 必须不大于 {upper_name}_threshold"
                )
        return self


class AlertAckRequest(BaseModel):
    """确认动作：责任人必填（路线 B1-01 防呆）。"""

    assignee_id: str
    note: str | None = None


class AlertAssignRequest(BaseModel):
    assignee_id: str
    note: str | None = None


class AlertTransitionRequest(BaseModel):
    to_status: str
    note: str | None = None
    resolution: str | None = None


class DispositionRequest(BaseModel):
    """处置表单（B1-02）：类型/原因/措施/停机/返工/扩大检查 + 关闭结论。"""

    resolution: str
    type: str | None = None
    cause: str | None = None
    action: str | None = None
    downtime: bool = False
    rework: bool = False
    expanded_inspection: bool = False
    note: str | None = None
    # 误报结论可选同时指派复核标注员（标注主体 id）；不传则任务建成待指派
    review_annotator_ids: list[str] = Field(default_factory=list, max_length=20)

    @field_validator("resolution")
    @classmethod
    def _resolution_allowed(cls, value: str) -> str:
        if value not in ("false_positive", "confirmed_issue", "other"):
            raise ValueError("resolution must be false_positive/confirmed_issue/other")
        return value


class AlertTransferRequest(BaseModel):
    assignee_id: str
    note: str | None = None


class SopContent(BaseModel):
    """三类处置指引（E07）：规格越限 / SPC 越限 / AI 风险。"""

    spec_exceed: list[str] = Field(default_factory=list)
    spc_exceed: list[str] = Field(default_factory=list)
    ai_risk: list[str] = Field(default_factory=list)


class SopCreate(BaseModel):
    code: str = Field(min_length=1, max_length=64)
    title: str = Field(min_length=1, max_length=256)
    content: SopContent
    scene_id: str | None = None
    condition_value: str | None = Field(default=None, max_length=128)


class SpcBaselineFreezeRequest(BaseModel):
    """基线冻结（E08）：指定数据集版本里的稳定时段，数值由服务端取出。

    服务端按行序取数并统一做 I-MR 计算与校验（20–500 个样本、时段内恒定
    拒绝）。不让客户端直接传数值——那样服务端无从复算，也达不到「所引用的
    事件序号可追溯」的验收口径。行号范围走 SQL 过滤；时间窗在取数时过滤
    （需要场景的时间字段角色）。
    """

    dataset_version_id: str
    field: str = Field(min_length=1, max_length=256)
    statistic: str = Field(default="value", max_length=16)
    station_id: str | None = None
    condition_value: str | None = Field(default=None, max_length=128)
    row_index_from: int | None = Field(default=None, ge=0)
    row_index_to: int | None = Field(default=None, ge=0)
    time_from: str | None = None
    time_to: str | None = None

    @field_validator("statistic")
    @classmethod
    def _statistic_allowed(cls, value: str) -> str:
        if value not in ("value", "mean", "min", "max", "rms"):
            raise ValueError("statistic must be value/mean/min/max/rms")
        return value


def parse_uuid(value: str | None, code: str) -> uuid.UUID:
    try:
        return uuid.UUID(str(value))
    except (TypeError, ValueError, AttributeError):
        from fastapi import HTTPException

        raise HTTPException(422, {"code": code}) from None
