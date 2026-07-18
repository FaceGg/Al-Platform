# Week 7 Pipeline Scheduling Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement a durable, idempotent Pipeline scheduler using Celery Beat, PostgreSQL-backed schedule state, and the existing WorkflowRun executor.

**Architecture:** Add schedule and occurrence models with a new Alembic revision. Keep Cron calculation and scheduling decisions in a dependency-light service; keep Celery task wiring in `app.tasks.scheduler_tasks`; keep API validation/ownership in a dedicated router. The scheduler creates snapshot-bound `WorkflowRun` rows and delegates execution to `execute_workflow_task`, so workflow execution semantics remain unchanged.

**Tech Stack:** FastAPI, Pydantic v2, SQLAlchemy 2, Alembic, PostgreSQL/SQLite, Celery 5, Redis, `croniter`, Python `zoneinfo`, unittest.

---

## File Map

- Create `ml-platform/backend/app/models/schedule.py`: schedule and schedule-occurrence ORM models.
- Create `ml-platform/backend/app/schemas/schedule.py`: request/response validation and stable error payload types.
- Create `ml-platform/backend/app/services/pipeline_scheduler.py`: Cron calculation, claims, dependency/concurrency checks, occurrence creation, backfill, pause/resume, and stale claim recovery.
- Create `ml-platform/backend/app/tasks/scheduler_tasks.py`: Celery Beat tick and recovery tasks.
- Create `ml-platform/backend/app/api/schedules.py`: project-owned schedule CRUD and operational endpoints.
- Create `ml-platform/backend/alembic/versions/20260718_05_pipeline_scheduling.py`: PostgreSQL/SQLite-compatible schema migration.
- Create `ml-platform/backend/tests/test_pipeline_scheduler.py`: service-level TDD coverage.
- Create `ml-platform/backend/tests/test_api_schedules.py`: API ownership and state transition coverage.
- Modify `ml-platform/backend/app/models/__init__.py`: register new models.
- Modify `ml-platform/backend/alembic/env.py`: import schedule models for metadata checks.
- Modify `ml-platform/backend/app/main.py`: import and include schedule router and model registration.
- Modify `ml-platform/backend/app/tasks/celery_app.py`: register scheduler task module and Beat schedule.
- Modify `ml-platform/backend/requirements.txt`: add `croniter`.
- Modify `docker-compose.yml`: add a non-root scheduler/Beat service with the same production environment and migration dependencies as worker.
- Modify `ml-platform/backend/tests/week_manifest.py`: assign new tests to Week 7.
- Modify `DEVELOPMENT_PLAN.md`, `PLATFORM_STATUS.md`, and `DEVELOPMENT_EXPERIENCE.md`: record status, evidence, and reusable lessons.

### Task 1: Add Cron dependency and failing calendar tests

**Files:**
- Modify: `ml-platform/backend/requirements.txt`
- Create: `ml-platform/backend/tests/test_pipeline_scheduler.py`

- [ ] **Step 1: Write failing tests for Cron and timezone behavior**

Add tests for `next_occurrence("*/5 * * * *", "UTC", datetime(2026, 7, 18, 12, 1, tzinfo=UTC)) == 12:05 UTC`, conversion from `Asia/Shanghai` to UTC, and invalid expressions raising `SCHEDULE_INVALID_CRON`.

- [ ] **Step 2: Run the focused tests and confirm the expected RED state**

Run from `ml-platform/backend`:

```powershell
python -m unittest tests.test_pipeline_scheduler.TestScheduleCalendar -v
```

Expected: import failure because `app.services.pipeline_scheduler` does not exist.

- [ ] **Step 3: Add the pinned dependency**

Append `croniter==6.*` to `requirements.txt`. Every dependency installation command in development/CI must continue to run `pip config set global.index-url https://mirrors.aliyun.com/pypi/simple/` first.

- [ ] **Step 4: Commit the dependency/test baseline**

```powershell
git add ml-platform/backend/requirements.txt ml-platform/backend/tests/test_pipeline_scheduler.py
git commit -m "test: define pipeline schedule calendar contract"
```

### Task 2: Implement schedule models and Alembic migration

**Files:**
- Create: `ml-platform/backend/app/models/schedule.py`
- Modify: `ml-platform/backend/app/models/__init__.py`
- Modify: `ml-platform/backend/alembic/env.py`
- Create: `ml-platform/backend/alembic/versions/20260718_05_pipeline_scheduling.py`
- Test: `ml-platform/backend/tests/test_pipeline_scheduler.py`

- [ ] **Step 1: Add model contract tests**

Assert that `PipelineSchedule` has project/workflow ownership, UTC `next_run_at`, `max_concurrency >= 1`, and a unique `(schedule_id, scheduled_for)` occurrence constraint. Assert the model metadata contains both new tables and the required indexes.

- [ ] **Step 2: Run model tests to confirm RED**

```powershell
python -m unittest tests.test_pipeline_scheduler.TestScheduleModels -v
```

Expected: `ImportError`/missing table metadata.

- [ ] **Step 3: Implement ORM models and imports**

Use the existing UUID, relationship, JSON, DateTime, and `created_at` conventions from `app.models.run`. Keep schedule occurrences linked to `WorkflowRun` and do not add a second execution model.

- [ ] **Step 4: Add the migration**

Create revision `20260718_05` with `down_revision = "20260717_04"`. Create both tables, the unique occurrence constraint, due/history indexes, project/workflow/run foreign keys, and a complete downgrade. Do not use `Base.metadata.create_all` in the migration.

- [ ] **Step 5: Run migration checks**

```powershell
alembic upgrade head
alembic upgrade head
alembic current
alembic check
```

Expected: head is `20260718_05`, second upgrade is a no-op, and `alembic check` reports no pending operations.

- [ ] **Step 6: Commit the persistence layer**

```powershell
git add ml-platform/backend/app/models ml-platform/backend/alembic ml-platform/backend/tests/test_pipeline_scheduler.py
git commit -m "feat: persist pipeline schedules and occurrences"
```

### Task 3: Implement scheduler service and idempotent claims

**Files:**
- Create: `ml-platform/backend/app/services/pipeline_scheduler.py`
- Modify: `ml-platform/backend/tests/test_pipeline_scheduler.py`

- [ ] **Step 1: Add RED tests for claims and idempotency**

Cover two scheduler calls against one due schedule, asserting one `PipelineScheduleRun`, one `WorkflowRun`, one enqueue call, and an advanced `next_run_at`. Add a concurrency-limit test that records `CONCURRENCY_LIMIT` without creating a workflow run.

- [ ] **Step 2: Run the tests and confirm RED**

```powershell
python -m unittest tests.test_pipeline_scheduler.TestSchedulerClaims -v
```

Expected: missing service symbols.

- [ ] **Step 3: Implement the minimal service boundary**

Expose typed functions/classes with these stable signatures:

```python
class PipelineScheduler:
    def tick(self, db, now=None, limit=100) -> list[dict]: ...
    def backfill(self, db, schedule, occurrences, enqueue) -> list[dict]: ...
    def pause(self, db, schedule) -> PipelineSchedule: ...
    def resume(self, db, schedule, now=None) -> PipelineSchedule: ...

def next_occurrence(expression: str, timezone_name: str, base: datetime) -> datetime: ...
def recover_stale_schedule_runs(db, now=None, lease_seconds=300, limit=100) -> int: ...
```

Use an explicit transaction boundary around claim/occurrence/workflow-row creation. Never hold the transaction while calling Celery. Use the existing workflow snapshot normalization helpers or extract a small shared helper without changing executor semantics.

- [ ] **Step 4: Verify the service tests pass**

```powershell
python -m unittest tests.test_pipeline_scheduler.TestScheduleCalendar tests.test_pipeline_scheduler.TestSchedulerClaims -v
```

- [ ] **Step 5: Commit the scheduler service**

```powershell
git add ml-platform/backend/app/services/pipeline_scheduler.py ml-platform/backend/tests/test_pipeline_scheduler.py
git commit -m "feat: add idempotent pipeline scheduler service"
```

### Task 4: Add dependency, retry, timeout, pause/resume, and backfill semantics

**Files:**
- Modify: `ml-platform/backend/app/services/pipeline_scheduler.py`
- Modify: `ml-platform/backend/tests/test_pipeline_scheduler.py`

- [ ] **Step 1: Add RED behavior tests**

Test dependency failure (`DEPENDENCY_NOT_READY`), pause/resume, bounded backfill with duplicate occurrence suppression, dispatch retry/backoff, malformed retry policy, and stale claimed occurrence recovery.

- [ ] **Step 2: Run behavior tests and confirm the expected failures**

```powershell
python -m unittest tests.test_pipeline_scheduler.TestSchedulerPolicies -v
```

- [ ] **Step 3: Implement policy handling**

Validate `max_attempts >= 1`, positive backoff values, and a maximum delay. Store stable codes in occurrence rows. Advance `next_run_at` for skipped dependency/concurrency occurrences. Copy `timeout_seconds`, selected workflow version, and the immutable workflow snapshot into the created `WorkflowRun`.

- [ ] **Step 4: Verify all service tests**

```powershell
python -m unittest tests.test_pipeline_scheduler -v
```

- [ ] **Step 5: Commit policy behavior**

```powershell
git add ml-platform/backend/app/services/pipeline_scheduler.py ml-platform/backend/tests/test_pipeline_scheduler.py
git commit -m "feat: add pipeline schedule policies and recovery"
```

### Task 5: Wire Celery Beat and scheduler recovery

**Files:**
- Create: `ml-platform/backend/app/tasks/scheduler_tasks.py`
- Modify: `ml-platform/backend/app/tasks/celery_app.py`
- Modify: `ml-platform/backend/tests/test_pipeline_scheduler.py`

- [ ] **Step 1: Add RED task-registration tests**

Assert `ml_platform.scheduler_tick` and `ml_platform.recover_pipeline_schedules` are registered, the Beat schedule runs `scheduler_tick` at the configured interval, and task execution calls `PipelineScheduler.tick` without holding a session across enqueue calls.

- [ ] **Step 2: Run registration tests and confirm RED**

```powershell
python -m unittest tests.test_pipeline_scheduler.TestSchedulerTasks -v
```

- [ ] **Step 3: Implement task wiring**

Include `app.tasks.scheduler_tasks` in the Celery app, configure a one-minute Beat schedule, and make the task open short-lived `SessionLocal` transactions. Keep recovery as a separate periodic task. Preserve existing task serializer, late ack, and worker prefetch settings.

- [ ] **Step 4: Verify task tests and import smoke**

```powershell
python -m unittest tests.test_pipeline_scheduler.TestSchedulerTasks -v
python -c "from app.tasks.celery_app import celery_app; assert 'ml_platform.scheduler_tick' in celery_app.tasks"
```

- [ ] **Step 5: Commit Celery wiring**

```powershell
git add ml-platform/backend/app/tasks ml-platform/backend/tests/test_pipeline_scheduler.py
git commit -m "feat: run pipeline scheduler through Celery Beat"
```

### Task 6: Add schedule API and ownership validation

**Files:**
- Create: `ml-platform/backend/app/schemas/schedule.py`
- Create: `ml-platform/backend/app/api/schedules.py`
- Modify: `ml-platform/backend/app/main.py`
- Create: `ml-platform/backend/tests/test_api_schedules.py`

- [ ] **Step 1: Add RED API tests**

Cover create/list/detail/update, invalid Cron/timezone, pause/resume, bounded backfill, occurrence pagination, missing schedule, and project ownership. Assert stable error codes and that cross-project resources return the existing hidden-resource behavior.

- [ ] **Step 2: Run API tests and confirm RED**

```powershell
python -m unittest tests.test_api_schedules -v
```

Expected: router import/route failures.

- [ ] **Step 3: Implement Pydantic schemas and router**

Use strict UUID parsing, bounded page sizes, `extra="forbid"` for create/update payloads, and the existing `get_current_user`/project owner checks. The router must call `PipelineScheduler` rather than duplicate scheduling rules.

- [ ] **Step 4: Register the router and verify API tests**

Import `schedules` in `app.main`, include its router, and run:

```powershell
python -m unittest tests.test_api_schedules -v
```

- [ ] **Step 5: Commit the API**

```powershell
git add ml-platform/backend/app/api/schedules.py ml-platform/backend/app/schemas/schedule.py ml-platform/backend/app/main.py ml-platform/backend/tests/test_api_schedules.py
git commit -m "feat: expose project pipeline schedule API"
```

### Task 7: Add scheduler service to Compose and CI

**Files:**
- Modify: `ml-platform/backend/Dockerfile.worker`
- Modify: `docker-compose.yml`
- Modify: `.github/workflows/ci.yml`
- Modify: `ml-platform/backend/tests/test_ci_workflow.py`

- [ ] **Step 1: Add RED composition assertions**

Assert the production composition contains a scheduler service using the worker image, runs `celery ... beat`, depends on migration/Redis, and uses the same production environment. Assert CI starts and waits for the scheduler service in the experiment integration job.

- [ ] **Step 2: Run composition tests and confirm RED**

```powershell
python -m unittest tests.test_ci_workflow -v
```

- [ ] **Step 3: Implement the scheduler service**

Add a `scheduler` Compose service with command `celery -A app.tasks.celery_app:celery_app beat --loglevel=INFO --schedule=/tmp/celerybeat-schedule`, the existing worker image/environment, and migration/Redis dependencies. Do not run Beat inside the API or worker process.

- [ ] **Step 4: Update CI and validate YAML/Compose**

```powershell
python -m unittest tests.test_ci_workflow -v
```

On a Docker-capable environment also run:

```bash
docker compose config --quiet
docker compose build scheduler
```

- [ ] **Step 5: Commit deployment wiring**

```powershell
git add ml-platform/backend/Dockerfile.worker docker-compose.yml .github/workflows/ci.yml ml-platform/backend/tests/test_ci_workflow.py
git commit -m "ci: deploy pipeline scheduler with Celery Beat"
```

### Task 8: Add Week 7 manifest, integration tests, documentation, and final verification

**Files:**
- Modify: `ml-platform/backend/tests/week_manifest.py`
- Modify: `ml-platform/backend/tests/test_pipeline_scheduler.py`
- Modify: `ml-platform/backend/tests/test_api_schedules.py`
- Modify: `DEVELOPMENT_PLAN.md`
- Modify: `PLATFORM_STATUS.md`
- Modify: `C:\Users\17723\.codex\DEVELOPMENT_EXPERIENCE.md`

- [ ] **Step 1: Add real integration coverage**

Run a PostgreSQL/Redis/Celery smoke path that creates a schedule, ticks it twice, verifies one occurrence and one workflow task, then pauses/resumes and backfills one bounded occurrence.

- [ ] **Step 2: Register new Week 7 test modules**

Add `test_pipeline_scheduler`, `test_api_schedules`, and `test_ci_workflow` to `WEEK_TEST_MODULES[7]`; keep `test_ci_workflow` assigned only once so the manifest remains complete.

- [ ] **Step 3: Run focused and Week 7 suites**

```powershell
python -m unittest tests.test_pipeline_scheduler tests.test_api_schedules tests.test_ci_workflow -v
python run_suite.py --week 7
```

- [ ] **Step 4: Run migration and full regressions**

```powershell
alembic upgrade head
alembic upgrade head
alembic current
alembic check
python run_suite.py
git diff --check
```

- [ ] **Step 5: Update status and reusable experience**

Record completed tasks, test counts, remote CI URL, unresolved risks, and any scheduler-specific root causes in `DEVELOPMENT_PLAN.md`, `PLATFORM_STATUS.md`, and the shared experience file. Do not mark Week 7 complete until local tests, production integration, and remote CI all pass.

- [ ] **Step 6: Commit the final Week 7 scheduler delivery**

```powershell
git add ml-platform/backend/tests DEVELOPMENT_PLAN.md PLATFORM_STATUS.md
git commit -m "feat: complete week 7 pipeline scheduling"
```

## Verification Checklist

- [ ] `test_pipeline_scheduler` passes, including concurrent claim and stale recovery cases.
- [ ] `test_api_schedules` passes with project ownership isolation.
- [ ] `test_ci_workflow` passes with scheduler service assertions.
- [ ] Week 7 manifest has one owner for every new test module.
- [ ] Alembic double upgrade/current/check passes.
- [ ] `docker compose config --quiet` and scheduler build pass in Docker-capable CI.
- [ ] Existing Week 1-6 suites remain green.
- [ ] Final remote quality, production, experiment, and browser acceptance jobs are green.
