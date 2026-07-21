"""Redacted inference logs and bounded minute-level telemetry."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import math
import re

from app.models.model_registry import (
    DeploymentTarget,
    InferenceMetricBucket,
    InferenceRequestLog,
)


LATENCY_BOUNDARIES = (5, 10, 25, 50, 100, 250, 500, 1000, 2500, 5000)
LOG_RETENTION_DAYS = 30
METRIC_RETENTION_DAYS = 90
MAX_QUERY_DAYS = 31
MAX_PAGE_SIZE = 200
_STATUSES = frozenset({"success", "error", "limited"})
_ERROR_CODE = re.compile(r"^[A-Z][A-Z0-9_]{0,63}$")


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _as_utc_naive(value: datetime) -> datetime:
    if not isinstance(value, datetime):
        raise InferenceObservabilityError("INFERENCE_OBSERVABILITY_TIME_INVALID")
    if value.tzinfo is None:
        return value
    return value.astimezone(timezone.utc).replace(tzinfo=None)


class InferenceObservabilityError(RuntimeError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def safe_request_log(log: InferenceRequestLog) -> dict[str, object]:
    """Return exactly fields allowed in operational log responses."""
    return {
        "id": log.id,
        "request_id": log.request_id,
        "deployment_id": log.deployment_id,
        "revision_id": log.revision_id,
        "model_version_id": log.model_version_id,
        "api_key_id": log.api_key_id,
        "batch_size": log.batch_size,
        "duration_ms": log.duration_ms,
        "status": log.status,
        "error_code": log.error_code,
        "occurred_at": log.occurred_at,
        "expires_at": log.expires_at,
    }


class InferenceObservability:
    def __init__(
        self,
        *,
        clock=utcnow,
        log_retention_days: int = LOG_RETENTION_DAYS,
        metric_retention_days: int = METRIC_RETENTION_DAYS,
    ):
        if log_retention_days < 1 or metric_retention_days < 1:
            raise ValueError("retention must be positive")
        self.clock = clock
        self.log_retention_days = log_retention_days
        self.metric_retention_days = metric_retention_days

    @staticmethod
    def _validate_request(
        request_id, batch_size, duration_ms, status, error_code,
    ) -> tuple[str, int, int, str, str | None]:
        normalized_request_id = str(request_id or "").strip()
        if not normalized_request_id or len(normalized_request_id) > 128:
            raise InferenceObservabilityError("INFERENCE_REQUEST_ID_INVALID")
        if isinstance(batch_size, bool) or not isinstance(batch_size, int) or batch_size < 1:
            raise InferenceObservabilityError("INFERENCE_BATCH_SIZE_INVALID")
        if isinstance(duration_ms, bool) or not isinstance(duration_ms, int) or duration_ms < 0:
            raise InferenceObservabilityError("INFERENCE_DURATION_INVALID")
        if status not in _STATUSES:
            raise InferenceObservabilityError("INFERENCE_LOG_STATUS_INVALID")
        if error_code is None:
            normalized_error_code = None
        else:
            normalized_error_code = str(error_code).strip()
            if not _ERROR_CODE.fullmatch(normalized_error_code):
                raise InferenceObservabilityError("INFERENCE_ERROR_CODE_INVALID")
        if status == "success" and normalized_error_code is not None:
            raise InferenceObservabilityError("INFERENCE_ERROR_CODE_INVALID")
        return (
            normalized_request_id,
            batch_size,
            duration_ms,
            status,
            normalized_error_code,
        )

    @staticmethod
    def _minute(value: datetime) -> datetime:
        return value.replace(second=0, microsecond=0)

    @staticmethod
    def _histogram(duration_ms: int) -> str:
        for boundary in LATENCY_BOUNDARIES:
            if duration_ms <= boundary:
                return str(boundary)
        return "gt_5000"

    @staticmethod
    def _empty_histogram() -> dict[str, int]:
        return {str(boundary): 0 for boundary in LATENCY_BOUNDARIES} | {"gt_5000": 0}

    @staticmethod
    def _traffic_weights(db, revision_id) -> dict[str, int]:
        if revision_id is None:
            return {}
        targets = db.query(DeploymentTarget).filter(
            DeploymentTarget.revision_id == revision_id,
        ).order_by(DeploymentTarget.model_version_id).all()
        return {str(target.model_version_id): int(target.weight_bps) for target in targets}

    def _bucket(self, db, deployment_id, minute: datetime) -> InferenceMetricBucket:
        bucket = db.query(InferenceMetricBucket).filter(
            InferenceMetricBucket.deployment_id == deployment_id,
            InferenceMetricBucket.bucket_start == minute,
        ).with_for_update().first()
        if bucket is None:
            bucket = InferenceMetricBucket(
                deployment_id=deployment_id,
                bucket_start=minute,
                latency_buckets=self._empty_histogram(),
                traffic_weights={},
            )
            db.add(bucket)
            db.flush()
        return bucket

    def record_request(
        self,
        db,
        request_id,
        deployment_id,
        revision_id,
        model_version_id,
        api_key_id,
        batch_size,
        duration_ms,
        status,
        error_code=None,
        *,
        occurred_at: datetime | None = None,
    ) -> InferenceRequestLog:
        request_id, batch_size, duration_ms, status, error_code = self._validate_request(
            request_id, batch_size, duration_ms, status, error_code,
        )
        occurred_at = _as_utc_naive(occurred_at or self.clock())
        log = InferenceRequestLog(
            request_id=request_id,
            deployment_id=deployment_id,
            revision_id=revision_id,
            model_version_id=model_version_id,
            api_key_id=api_key_id,
            batch_size=batch_size,
            duration_ms=duration_ms,
            status=status,
            error_code=error_code,
            occurred_at=occurred_at,
            expires_at=occurred_at + timedelta(days=self.log_retention_days),
        )
        db.add(log)
        bucket = self._bucket(db, deployment_id, self._minute(occurred_at))
        bucket.request_count = int(bucket.request_count or 0) + 1
        bucket.batch_size_sum = int(bucket.batch_size_sum or 0) + batch_size
        bucket.latency_sum_ms = int(bucket.latency_sum_ms or 0) + duration_ms
        bucket.latency_max_ms = max(int(bucket.latency_max_ms or 0), duration_ms)
        if status == "success":
            bucket.success_count = int(bucket.success_count or 0) + 1
        elif status == "error":
            bucket.error_count = int(bucket.error_count or 0) + 1
            if error_code == "INFERENCE_RUNTIME_LOAD_FAILED":
                bucket.load_failure_count = int(bucket.load_failure_count or 0) + 1
        else:
            bucket.limited_count = int(bucket.limited_count or 0) + 1
        histogram = self._empty_histogram()
        histogram.update({key: int(value) for key, value in (bucket.latency_buckets or {}).items() if key in histogram})
        histogram[self._histogram(duration_ms)] += 1
        bucket.latency_buckets = histogram
        bucket.traffic_weights = self._traffic_weights(db, revision_id)
        db.flush()
        return log

    def record_load_failure(self, db, deployment_id, *, occurred_at: datetime | None = None):
        occurred_at = _as_utc_naive(occurred_at or self.clock())
        bucket = self._bucket(db, deployment_id, self._minute(occurred_at))
        bucket.load_failure_count = int(bucket.load_failure_count or 0) + 1
        db.flush()
        return bucket

    @staticmethod
    def _validate_query(since, until, page, page_size) -> tuple[datetime, datetime]:
        since = _as_utc_naive(since)
        until = _as_utc_naive(until)
        if since >= until or until - since > timedelta(days=MAX_QUERY_DAYS):
            raise InferenceObservabilityError("INFERENCE_QUERY_WINDOW_INVALID")
        if isinstance(page, bool) or not isinstance(page, int) or page < 1:
            raise InferenceObservabilityError("INFERENCE_QUERY_PAGE_INVALID")
        if isinstance(page_size, bool) or not isinstance(page_size, int) or not 1 <= page_size <= MAX_PAGE_SIZE:
            raise InferenceObservabilityError("INFERENCE_QUERY_PAGE_SIZE_INVALID")
        return since, until

    def query_logs(self, db, deployment_id, since, until, *, page: int = 1, page_size: int = 100):
        since, until = self._validate_query(since, until, page, page_size)
        return [
            safe_request_log(log)
            for log in db.query(InferenceRequestLog).filter(
                InferenceRequestLog.deployment_id == deployment_id,
                InferenceRequestLog.occurred_at >= since,
                InferenceRequestLog.occurred_at < until,
            ).order_by(
                InferenceRequestLog.occurred_at.desc(), InferenceRequestLog.id.desc(),
            ).offset((page - 1) * page_size).limit(page_size).all()
        ]

    def query_metrics(self, db, deployment_id, since, until, *, page: int = 1, page_size: int = 100):
        since, until = self._validate_query(since, until, page, page_size)
        return db.query(InferenceMetricBucket).filter(
            InferenceMetricBucket.deployment_id == deployment_id,
            InferenceMetricBucket.bucket_start >= since,
            InferenceMetricBucket.bucket_start < until,
        ).order_by(InferenceMetricBucket.bucket_start.asc()).offset(
            (page - 1) * page_size,
        ).limit(page_size).all()

    @staticmethod
    def percentile_from_histogram(histogram: dict[str, int], percentile: float) -> int | None:
        if not isinstance(percentile, (int, float)) or not 0 < percentile <= 1 or not math.isfinite(percentile):
            raise InferenceObservabilityError("INFERENCE_PERCENTILE_INVALID")
        total = sum(max(0, int(count)) for count in (histogram or {}).values())
        if total == 0:
            return None
        threshold = math.ceil(total * percentile)
        seen = 0
        for boundary in LATENCY_BOUNDARIES:
            seen += max(0, int((histogram or {}).get(str(boundary), 0)))
            if seen >= threshold:
                return boundary
        return LATENCY_BOUNDARIES[-1]

    def summarize_metrics(self, buckets) -> dict[str, object]:
        buckets = list(buckets)
        histogram = self._empty_histogram()
        for bucket in buckets:
            for key, count in (bucket.latency_buckets or {}).items():
                if key in histogram:
                    histogram[key] += int(count)
        request_count = sum(int(bucket.request_count or 0) for bucket in buckets)
        latency_sum = sum(int(bucket.latency_sum_ms or 0) for bucket in buckets)
        return {
            "request_count": request_count,
            "success_count": sum(int(bucket.success_count or 0) for bucket in buckets),
            "error_count": sum(int(bucket.error_count or 0) for bucket in buckets),
            "limited_count": sum(int(bucket.limited_count or 0) for bucket in buckets),
            "load_failure_count": sum(int(bucket.load_failure_count or 0) for bucket in buckets),
            "average_batch_size": (
                sum(int(bucket.batch_size_sum or 0) for bucket in buckets) / request_count
                if request_count else 0
            ),
            "average_latency_ms": latency_sum / request_count if request_count else 0,
            "max_latency_ms": max((int(bucket.latency_max_ms or 0) for bucket in buckets), default=0),
            "latency_buckets": histogram,
            "p50_latency_ms": self.percentile_from_histogram(histogram, 0.50),
            "p95_latency_ms": self.percentile_from_histogram(histogram, 0.95),
            "p99_latency_ms": self.percentile_from_histogram(histogram, 0.99),
            "traffic_weights": dict(buckets[-1].traffic_weights or {}) if buckets else {},
        }

    def prune(self, db, now: datetime | None = None) -> int:
        now = _as_utc_naive(now or self.clock())
        log_count = db.query(InferenceRequestLog).filter(
            InferenceRequestLog.expires_at <= now,
        ).delete(synchronize_session="fetch")
        bucket_count = db.query(InferenceMetricBucket).filter(
            InferenceMetricBucket.bucket_start < now - timedelta(days=self.metric_retention_days),
        ).delete(synchronize_session="fetch")
        return int(log_count) + int(bucket_count)
