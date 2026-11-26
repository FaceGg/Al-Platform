"""Safe domain-event contract for production inference workflows."""

from collections.abc import Mapping as MappingABC
from dataclasses import dataclass
from datetime import datetime
import math
from types import MappingProxyType
from typing import Mapping, Protocol
from uuid import UUID, uuid4

from sqlalchemy.orm import Session


SAFE_EVENT_TYPES = frozenset({
    "rollout.started",
    "rollout.failed",
    "rollout.completed",
    "rollback.completed",
    "runtime.load_failed",
    "rate_limit.threshold_exceeded",
    "inference.error_rate.threshold_exceeded",
    "inference.unknown_condition",
    # 推理结果明细异步落库失败（B1-16/D4）：推理响应不受影响，只告警
    "inference.result_persist_failed",
    # 预警 SLA 两档（F2a/D21）：临期与超时通知，走 outbox→订阅路由投递
    "quality.alert.sla_due",
    "quality.alert.sla_overdue",
    # 漂移严重级报告（F4/D40）：只通知，不自动处置
    "drift.severe",
    # 统一审批队列三事件（S1/D6）：过期前提醒、过期回收、决策回执
    "approval.expiring",
    "approval.expired",
    "approval.decided",
    "annotation_return.accepted",
    "annotation_return.returned_for_changes",
    "annotation_comment.replied",
    "annotation_comment.status_changed",
})

SAFE_PAYLOAD_KEYS = frozenset({
    "revision_id",
    "deployment_id",
    "model_version_ids",
    "error_code",
    "step",
    "return_batch_id",
    "comment_id",
    "parent_comment_id",
    "status",
    "condition_column",
    "unknown_values",
    # 预警 SLA 事件载荷（F2a/D21）
    "alert_id",
    "title",
    "severity",
    "sla_due_at",
    # 漂移严重级事件载荷（F4/D40）
    "report_id",
    "drifted_feature_count",
    # 审批队列事件载荷（S1/D6）
    "approval_id",
    "approval_type",
    "decision",
    "decision_note",
    "expires_at",
})


def _deep_freeze(value: object) -> object:
    """Copy nested payload values into immutable containers."""
    if isinstance(value, MappingABC):
        return MappingProxyType({key: _deep_freeze(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_deep_freeze(item) for item in value)
    return value


def _validate_json_value(value: object) -> None:
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("DOMAIN_EVENT_PAYLOAD_INVALID")
    if value is None or isinstance(value, (bool, int, float, str)):
        return
    if isinstance(value, MappingABC):
        if any(not isinstance(key, str) for key in value):
            raise ValueError("DOMAIN_EVENT_PAYLOAD_INVALID")
        for item in value.values():
            _validate_json_value(item)
        return
    if isinstance(value, (list, tuple)):
        for item in value:
            _validate_json_value(item)
        return
    raise ValueError("DOMAIN_EVENT_PAYLOAD_INVALID")


def _thaw_for_storage(value: object) -> object:
    if isinstance(value, MappingABC):
        return {key: _thaw_for_storage(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_thaw_for_storage(item) for item in value]
    return value


def to_storage_payload(payload: Mapping[str, object]) -> dict[str, object]:
    """Return a detached JSON-compatible payload for Outbox and storage writers."""
    return {
        key: _thaw_for_storage(value)
        for key, value in payload.items()
    }


@dataclass(frozen=True)
class DomainEvent:
    event_id: UUID
    idempotency_key: str
    event_type: str
    severity: str
    occurred_at: datetime
    project_id: UUID | None
    actor_id: UUID | None
    resource_type: str
    resource_id: str | None
    payload: Mapping[str, object]

    def __post_init__(self) -> None:
        if self.event_type not in SAFE_EVENT_TYPES:
            raise ValueError("DOMAIN_EVENT_TYPE_INVALID")
        safe_payload = {
            key: value
            for key, value in self.payload.items()
            if key in SAFE_PAYLOAD_KEYS
        }
        for value in safe_payload.values():
            _validate_json_value(value)
        frozen_payload = {
            key: _deep_freeze(value)
            for key, value in safe_payload.items()
        }
        object.__setattr__(self, "payload", MappingProxyType(frozen_payload))


class DomainEventRecorder(Protocol):
    def record(self, db: Session, event: DomainEvent) -> None:
        raise NotImplementedError


class NullDomainEventRecorder:
    def record(self, db: Session, event: DomainEvent) -> None:
        return None


def create_domain_event(
    *,
    idempotency_key: str,
    event_type: str,
    severity: str,
    occurred_at: datetime,
    project_id: UUID | None,
    actor_id: UUID | None,
    resource_type: str,
    resource_id: str | None,
    payload: Mapping[str, object],
) -> DomainEvent:
    """Create an immutable event while filtering payload to safe fields."""
    return DomainEvent(
        event_id=uuid4(),
        idempotency_key=idempotency_key,
        event_type=event_type,
        severity=severity,
        occurred_at=occurred_at,
        project_id=project_id,
        actor_id=actor_id,
        resource_type=resource_type,
        resource_id=resource_id,
        payload=payload,
    )
