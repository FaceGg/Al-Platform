# Week 7 Pipeline Scheduling Design

**Status:** Draft for review

**Goal:** Add a durable, idempotent Pipeline scheduler based on Celery Beat and PostgreSQL, while reusing the existing `WorkflowRun` execution contract.

## Scope

This design covers the first Week 7 subsystem: pipeline scheduling. It includes Cron schedules, timezone-aware next-run calculation, persisted schedule instances, dependency and concurrency checks, retry/backoff policy, timeout configuration, pause/resume, manual backfill, stale-claim recovery, and schedule/run query APIs.

Project roles and audit events are a separate follow-up design and are not included here.

## Architecture

Celery Beat invokes a short `scheduler_tick` task at a fixed interval. The task does not execute workflows itself. It claims due schedules in the database, validates each due occurrence, creates one `PipelineScheduleRun`, creates a snapshot-bound `WorkflowRun`, and enqueues the existing `execute_workflow_task`.

The database is the source of truth for schedule ownership, occurrence idempotency, next-run state, and recovery. PostgreSQL uses row locks/conditional updates for competing scheduler instances. SQLite/local mode keeps the same service interface with a transaction-safe conditional claim suitable for tests and local fallback.

The scheduler and workflow executor remain separate boundaries:

```text
Celery Beat -> scheduler_tick -> PipelineSchedule/PipelineScheduleRun
                                      -> WorkflowRun snapshot
                                      -> execute_workflow_task
```

## Persistence Model

### `pipeline_schedules`

- `id`: UUID primary key
- `project_id`: owned project foreign key
- `workflow_id`: workflow foreign key
- `name`: project-scoped display name
- `cron_expression`: standard five-field Cron expression
- `timezone`: IANA timezone name
- `enabled`: whether the schedule may create new instances
- `paused_at`: nullable pause timestamp
- `max_concurrency`: positive integer, default 1
- `dependencies`: JSON list of prerequisite schedule UUIDs
- `retry_policy`: JSON containing max attempts, backoff base, and maximum delay
- `timeout_seconds`: nullable positive workflow timeout override
- `workflow_version`: nullable fixed version
- `next_run_at`: timezone-normalized UTC timestamp
- `last_run_at`: nullable UTC timestamp
- `last_error_code`: nullable stable scheduler error code
- `created_by`, `created_at`, `updated_at`

### `pipeline_schedule_runs`

- `id`: UUID primary key
- `schedule_id`: schedule foreign key
- `workflow_run_id`: created workflow run foreign key
- `scheduled_for`: UTC occurrence timestamp
- `claimed_at`: nullable UTC timestamp
- `finished_at`: nullable UTC timestamp
- `status`: `pending`, `claimed`, `skipped`, `failed`, or `completed`
- `attempt`: integer dispatch attempt
- `skip_reason`: nullable stable code
- `error_code`, `error_message`: nullable structured failure information
- `created_at`

Constraints and indexes:

- Unique `(schedule_id, scheduled_for)` prevents duplicate occurrences.
- Index due schedules by `(enabled, next_run_at)`.
- Index schedule history by `(schedule_id, scheduled_for)`.
- Foreign keys use project/workflow ownership boundaries and cascade only where existing workflow deletion semantics permit it.

## State and Idempotency

The scheduler claims one due schedule occurrence using a transaction and row lock/conditional update. It advances `next_run_at` in the same transaction as the occurrence claim. A duplicate tick therefore sees either a future `next_run_at` or the unique occurrence constraint and performs no second dispatch.

Pause changes only schedule eligibility. Existing `WorkflowRun` instances continue under their own lifecycle. Resume recalculates from the current time and does not replay every missed occurrence unless the caller explicitly requests backfill.

Backfill accepts a bounded time range or one occurrence timestamp. Each requested occurrence uses the same uniqueness rule and the saved workflow version/snapshot contract. Backfill is rejected for disabled/deleted workflows and reports per-occurrence results.

## Dependency and Concurrency Rules

- Dependency checks run before creating `WorkflowRun`.
- A dependency failure creates a `PipelineScheduleRun(status="skipped", skip_reason="DEPENDENCY_NOT_READY")`.
- `max_concurrency` counts non-terminal workflow runs for the schedule.
- A concurrency limit creates a skipped schedule instance with `CONCURRENCY_LIMIT` and advances the schedule; it does not silently retry forever.
- The schedule history API exposes skipped occurrences and reasons.

## Retry and Timeout Semantics

Dispatch failures are retried according to the persisted policy with exponential backoff capped by the configured maximum. Workflow execution failures remain owned by `WorkflowRun`; the scheduler records the linked schedule-run outcome and does not duplicate executor retry semantics.

Timeout configuration is copied to the created run/task metadata. A timeout is terminal for that occurrence and uses the existing `TASK_HARD_TIMEOUT`/workflow error contracts. Scheduler ticks are short and must never hold a database transaction while waiting for a task or external service.

## API Contract

- `POST /api/projects/{project_id}/schedules`: create and validate a schedule.
- `GET /api/projects/{project_id}/schedules`: list schedules with next/last run state.
- `GET /api/schedules/{schedule_id}`: return schedule configuration and status.
- `PATCH /api/schedules/{schedule_id}`: update Cron, timezone, policy, concurrency, or enabled state.
- `POST /api/schedules/{schedule_id}/pause`: pause future occurrences.
- `POST /api/schedules/{schedule_id}/resume`: resume and recalculate next run.
- `POST /api/schedules/{schedule_id}/backfill`: request bounded manual occurrences.
- `GET /api/schedules/{schedule_id}/runs`: paginated occurrence history.
- `POST /api/schedules/tick`: protected operational/test endpoint; production scheduling uses Celery Beat.

All IDs are parsed as UUIDs, all schedule resources are project-owned, and errors use stable codes such as `SCHEDULE_INVALID_CRON`, `SCHEDULE_DEPENDENCY_NOT_READY`, `SCHEDULE_CONCURRENCY_LIMIT`, `SCHEDULE_ALREADY_PAUSED`, and `SCHEDULE_DISPATCH_FAILED`.

## Failure Recovery

- A claimed schedule occurrence with no linked task is eligible for stale recovery after a bounded lease timeout.
- A schedule whose worker disappears is reconciled through the existing workflow stale-run recovery path.
- Failed database commits leave the occurrence unclaimed and safe to retry.
- External dispatch errors are stored without leaking credentials or connection strings.
- A malformed Cron expression is rejected at API validation and never reaches the scheduler loop.

## Testing and Acceptance

TDD coverage must include:

1. Cron validation, timezone conversion, next-run calculation, and invalid input errors.
2. Concurrent scheduler ticks producing one occurrence and one `WorkflowRun`.
3. Pause/resume and bounded backfill behavior.
4. Dependency and concurrency skips with stable reasons.
5. Retry/backoff, dispatch failure, stale lease recovery, and idempotency.
6. Workflow version/snapshot binding for scheduled and backfilled runs.
7. API project ownership, pagination, and state transitions.
8. Alembic double upgrade/current/check and downgrade coverage.
9. Celery Beat/worker smoke integration with PostgreSQL and Redis in the production composition.
10. Existing Week 1-6 backend, frontend, Chromium, and readiness regressions.

## Non-goals

- Kubernetes scheduling or distributed cluster routing.
- Arbitrary Cron dialects beyond standard five-field expressions.
- Project roles, audit log storage, SSO, or enterprise notifications; these belong to the second Week 7 subsystem.
- Replacing the existing workflow executor or training scheduler.
