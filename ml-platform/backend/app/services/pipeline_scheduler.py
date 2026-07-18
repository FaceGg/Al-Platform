"""Calendar and persistence services for scheduled pipeline runs."""

from collections.abc import Callable
from datetime import datetime, timedelta, timezone
import uuid
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from croniter import CroniterBadCronError, croniter
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError

from app.engine.run_state import TERMINAL_RUN_STATUSES
from app.models.run import WorkflowRun
from app.models.schedule import PipelineSchedule, PipelineScheduleRun


class ScheduleError(ValueError):
    """Stable, user-facing scheduler validation error."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def next_occurrence(expression: str, timezone_name: str, base: datetime) -> datetime:
    """Return the next Cron occurrence as an aware UTC datetime."""
    try:
        zone = ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError as error:
        raise ScheduleError("SCHEDULE_INVALID_TIMEZONE", "Unknown schedule timezone") from error

    try:
        reference = base if base.tzinfo is not None else base.replace(tzinfo=timezone.utc)
        local_reference = reference.astimezone(zone)
        occurrence = croniter(expression, local_reference).get_next(datetime)
    except (CroniterBadCronError, ValueError, TypeError) as error:
        raise ScheduleError("SCHEDULE_INVALID_CRON", "Invalid Cron expression") from error
    return occurrence.astimezone(timezone.utc)


def _utc_naive(value: datetime) -> datetime:
    aware = value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
    return aware.astimezone(timezone.utc).replace(tzinfo=None)


def _workflow_snapshot(workflow) -> dict:
    return {
        "nodes": [
            {
                "id": str(node.id),
                "operator_id": node.operator_id,
                "label": node.label or "",
                "params": node.params or {},
            }
            for node in workflow.nodes
        ],
        "edges": [
            {
                "source": str(edge.source_node_id),
                "source_port": edge.source_port or "",
                "target": str(edge.target_node_id),
                "target_port": edge.target_port or "",
            }
            for edge in workflow.edges
        ],
    }


class PipelineScheduler:
    """Claim due schedules and delegate execution to the workflow dispatcher."""

    def __init__(self, enqueue: Callable[[str, int | None], str]):
        self.enqueue = enqueue

    def tick(self, db, *, now: datetime | None = None, limit: int = 100) -> list[dict]:
        current_naive = _utc_naive(now or datetime.now(timezone.utc))
        results = self._retry_due_dispatches(db, current_naive, limit)
        remaining = max(0, limit - len(results))
        if remaining == 0:
            return results
        schedules = (
            db.query(PipelineSchedule)
            .filter(
                PipelineSchedule.enabled.is_(True),
                PipelineSchedule.paused_at.is_(None),
                PipelineSchedule.next_run_at <= current_naive,
            )
            .order_by(PipelineSchedule.next_run_at, PipelineSchedule.id)
            .with_for_update()
            .limit(remaining)
            .all()
        )
        for schedule in schedules:
            scheduled_for = _utc_naive(schedule.next_run_at)
            try:
                results.append(self._process_due_schedule(db, schedule, current_naive))
            except IntegrityError:
                db.rollback()
                duplicate = db.query(PipelineScheduleRun).filter(
                    PipelineScheduleRun.schedule_id == schedule.id,
                    PipelineScheduleRun.scheduled_for == scheduled_for,
                ).first()
                if duplicate is None:
                    raise
                refreshed = db.query(PipelineSchedule).filter(
                    PipelineSchedule.id == schedule.id,
                ).one()
                if _utc_naive(refreshed.next_run_at) <= scheduled_for:
                    refreshed.next_run_at = next_occurrence(
                        refreshed.cron_expression,
                        refreshed.timezone,
                        scheduled_for.replace(tzinfo=timezone.utc),
                    ).replace(tzinfo=None)
                    db.commit()
                results.append({
                    "status": "skipped",
                    "schedule_id": str(schedule.id),
                    "scheduled_for": scheduled_for.isoformat(),
                    "skip_reason": "DUPLICATE_OCCURRENCE",
                })
        return results

    def _retry_due_dispatches(self, db, now_naive: datetime, limit: int) -> list[dict]:
        occurrences = (
            db.query(PipelineScheduleRun)
            .filter(
                PipelineScheduleRun.status == "pending",
                PipelineScheduleRun.workflow_run_id.is_not(None),
                PipelineScheduleRun.next_attempt_at.is_not(None),
                PipelineScheduleRun.next_attempt_at <= now_naive,
            )
            .order_by(PipelineScheduleRun.next_attempt_at, PipelineScheduleRun.id)
            .with_for_update()
            .limit(limit)
            .all()
        )
        return [self._attempt_dispatch(db, occurrence, now_naive) for occurrence in occurrences]

    def _process_due_schedule(self, db, schedule, now_naive: datetime) -> dict:
        scheduled_for = _utc_naive(schedule.next_run_at)
        schedule.next_run_at = next_occurrence(
            schedule.cron_expression,
            schedule.timezone,
            scheduled_for.replace(tzinfo=timezone.utc),
        ).replace(tzinfo=None)
        schedule.last_run_at = scheduled_for
        if not self._dependencies_ready(db, schedule):
            return self._record_skip(db, schedule, scheduled_for, now_naive, "DEPENDENCY_NOT_READY")
        if self._active_count(db, schedule) >= schedule.max_concurrency:
            return self._record_skip(db, schedule, scheduled_for, now_naive, "CONCURRENCY_LIMIT")
        return self._dispatch_occurrence(db, schedule, scheduled_for, now_naive)

    @staticmethod
    def _active_count(db, schedule) -> int:
        return (
            db.query(func.count(WorkflowRun.id))
            .join(PipelineScheduleRun, PipelineScheduleRun.workflow_run_id == WorkflowRun.id)
            .filter(
                PipelineScheduleRun.schedule_id == schedule.id,
                WorkflowRun.status.notin_(TERMINAL_RUN_STATUSES),
            )
            .scalar()
        )

    @staticmethod
    def _dependencies_ready(db, schedule) -> bool:
        for dependency_id in schedule.dependencies or []:
            dependency_uuid = uuid.UUID(str(dependency_id))
            latest = (
                db.query(PipelineScheduleRun)
                .filter(PipelineScheduleRun.schedule_id == dependency_uuid)
                .order_by(PipelineScheduleRun.scheduled_for.desc())
                .first()
            )
            if latest is None or latest.workflow_run is None or latest.workflow_run.status != "completed":
                return False
        return True

    @staticmethod
    def _record_skip(db, schedule, scheduled_for, now_naive, reason: str) -> dict:
        occurrence = PipelineScheduleRun(
            schedule_id=schedule.id,
            scheduled_for=scheduled_for,
            status="skipped",
            skip_reason=reason,
            finished_at=now_naive,
        )
        db.add(occurrence)
        db.commit()
        return {
            "status": "skipped",
            "schedule_id": str(schedule.id),
            "scheduled_for": scheduled_for.isoformat(),
            "skip_reason": reason,
        }

    def _dispatch_occurrence(self, db, schedule, scheduled_for, now_naive) -> dict:
        workflow_run = WorkflowRun(
            workflow_id=schedule.workflow_id,
            status="pending",
            triggered_by=schedule.created_by,
            workflow_version=schedule.workflow_version,
            workflow_snapshot=_workflow_snapshot(schedule.workflow),
            timeout_seconds=schedule.timeout_seconds,
            logs=[{"level": "info", "message": "Run created by pipeline schedule"}],
        )
        occurrence = PipelineScheduleRun(
            schedule_id=schedule.id,
            workflow_run=workflow_run,
            scheduled_for=scheduled_for,
            status="pending",
            attempt=0,
        )
        db.add(occurrence)
        db.commit()

        return self._attempt_dispatch(db, occurrence, now_naive)

    def _attempt_dispatch(self, db, occurrence, now_naive) -> dict:
        schedule = occurrence.schedule
        workflow_run = occurrence.workflow_run
        policy = schedule.retry_policy or {}
        try:
            max_attempts = max(1, min(10, int(policy.get("max_attempts", 1))))
            backoff_seconds = max(
                0.0,
                min(3600.0, float(policy.get("backoff_seconds", 0))),
            )
            max_backoff_seconds = max(
                0.0,
                min(86400.0, float(policy.get("max_backoff_seconds", 3600))),
            )
        except (TypeError, ValueError, OverflowError):
            occurrence.status = "failed"
            occurrence.finished_at = now_naive
            occurrence.error_code = "SCHEDULE_INVALID_RETRY_POLICY"
            occurrence.error_message = "Persisted retry policy is invalid"
            workflow_run.status = "failed"
            workflow_run.finished_at = now_naive
            workflow_run.error_code = "SCHEDULE_INVALID_RETRY_POLICY"
            workflow_run.error_message = "Scheduled workflow retry policy is invalid"
            schedule.last_error_code = "SCHEDULE_INVALID_RETRY_POLICY"
            db.commit()
            return {
                "status": "failed",
                "schedule_id": str(schedule.id),
                "scheduled_for": occurrence.scheduled_for.isoformat(),
                "error_code": "SCHEDULE_INVALID_RETRY_POLICY",
                "attempt": occurrence.attempt,
            }
        attempt = occurrence.attempt + 1
        occurrence.attempt = attempt
        occurrence.next_attempt_at = None

        try:
            task_id = self.enqueue(str(workflow_run.id), workflow_run.timeout_seconds)
            workflow_run.status = "queued"
            workflow_run.task_id = task_id
            occurrence.status = "claimed"
            occurrence.claimed_at = now_naive
            occurrence.error_code = None
            occurrence.error_message = None
            schedule.last_error_code = None
            db.commit()
            return {
                "status": "claimed",
                "schedule_id": str(schedule.id),
                "scheduled_for": occurrence.scheduled_for.isoformat(),
                "workflow_run_id": str(workflow_run.id),
                "task_id": task_id,
                "attempt": attempt,
            }
        except Exception as error:
            occurrence.error_code = "SCHEDULE_DISPATCH_FAILED"
            occurrence.error_message = str(error)
            schedule.last_error_code = "SCHEDULE_DISPATCH_FAILED"
            if attempt < max_attempts:
                delay = min(
                    backoff_seconds * (2 ** (attempt - 1)),
                    max_backoff_seconds,
                )
                occurrence.next_attempt_at = now_naive + timedelta(seconds=delay)
                db.commit()
                return {
                    "status": "retrying",
                    "schedule_id": str(schedule.id),
                    "scheduled_for": occurrence.scheduled_for.isoformat(),
                    "error_code": "SCHEDULE_DISPATCH_FAILED",
                    "attempt": attempt,
                    "next_attempt_at": occurrence.next_attempt_at.isoformat(),
                }

        occurrence.status = "failed"
        occurrence.finished_at = now_naive
        workflow_run.status = "failed"
        workflow_run.error_code = "SCHEDULE_DISPATCH_FAILED"
        workflow_run.error_message = "Scheduled workflow dispatch failed"
        workflow_run.finished_at = now_naive
        db.commit()
        return {
            "status": "failed",
            "schedule_id": str(schedule.id),
            "scheduled_for": occurrence.scheduled_for.isoformat(),
            "error_code": "SCHEDULE_DISPATCH_FAILED",
            "attempt": attempt,
        }

    def pause(self, db, schedule):
        if schedule.paused_at is not None:
            raise ScheduleError("SCHEDULE_ALREADY_PAUSED", "Schedule is already paused")
        schedule.paused_at = datetime.now(timezone.utc).replace(tzinfo=None)
        db.commit()
        return schedule

    def resume(self, db, schedule, *, now: datetime | None = None):
        if schedule.paused_at is None:
            raise ScheduleError("SCHEDULE_NOT_PAUSED", "Schedule is not paused")
        current = now or datetime.now(timezone.utc)
        schedule.paused_at = None
        schedule.enabled = True
        schedule.next_run_at = next_occurrence(
            schedule.cron_expression,
            schedule.timezone,
            current,
        ).replace(tzinfo=None)
        db.commit()
        return schedule

    def backfill(self, db, schedule, occurrences, *, now: datetime | None = None) -> list[dict]:
        current_naive = _utc_naive(now or datetime.now(timezone.utc))
        results = []
        for value in occurrences:
            scheduled_for = _utc_naive(value)
            existing = (
                db.query(PipelineScheduleRun)
                .filter(
                    PipelineScheduleRun.schedule_id == schedule.id,
                    PipelineScheduleRun.scheduled_for == scheduled_for,
                )
                .first()
            )
            if existing is not None:
                results.append({
                    "status": "skipped",
                    "scheduled_for": scheduled_for.isoformat(),
                    "skip_reason": "DUPLICATE_OCCURRENCE",
                })
                continue
            if not self._dependencies_ready(db, schedule):
                results.append(self._record_skip(db, schedule, scheduled_for, current_naive, "DEPENDENCY_NOT_READY"))
                continue
            if self._active_count(db, schedule) >= schedule.max_concurrency:
                results.append(self._record_skip(db, schedule, scheduled_for, current_naive, "CONCURRENCY_LIMIT"))
                continue
            results.append(self._dispatch_occurrence(db, schedule, scheduled_for, current_naive))
        return results


def recover_stale_schedule_runs(
    db,
    *,
    now: datetime | None = None,
    lease_seconds: int = 300,
    limit: int = 100,
) -> int:
    current = _utc_naive(now or datetime.now(timezone.utc))
    cutoff = current - timedelta(seconds=lease_seconds)
    stale = (
        db.query(PipelineScheduleRun)
        .filter(
            PipelineScheduleRun.status == "pending",
            PipelineScheduleRun.workflow_run_id.is_(None),
            PipelineScheduleRun.claimed_at.is_not(None),
            PipelineScheduleRun.claimed_at < cutoff,
        )
        .limit(limit)
        .all()
    )
    for occurrence in stale:
        occurrence.claimed_at = None
    db.commit()
    return len(stale)


def reconcile_schedule_runs(
    db,
    *,
    now: datetime | None = None,
    limit: int = 100,
) -> int:
    current = _utc_naive(now or datetime.now(timezone.utc))
    occurrences = (
        db.query(PipelineScheduleRun)
        .join(WorkflowRun, WorkflowRun.id == PipelineScheduleRun.workflow_run_id)
        .filter(
            PipelineScheduleRun.status == "claimed",
            WorkflowRun.status.in_(TERMINAL_RUN_STATUSES),
        )
        .order_by(PipelineScheduleRun.claimed_at, PipelineScheduleRun.id)
        .with_for_update()
        .limit(limit)
        .all()
    )
    for occurrence in occurrences:
        workflow_run = occurrence.workflow_run
        occurrence.status = (
            "completed" if workflow_run.status == "completed" else "failed"
        )
        occurrence.finished_at = workflow_run.finished_at or current
        occurrence.error_code = workflow_run.error_code
        occurrence.error_message = workflow_run.error_message
    db.commit()
    return len(occurrences)
