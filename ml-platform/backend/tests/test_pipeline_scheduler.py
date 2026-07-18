import os
import time
import unittest
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models.project import Project
from app.models.run import WorkflowRun
from app.models.schedule import PipelineSchedule, PipelineScheduleRun
from app.models.user import User
from app.models.workflow import Workflow, WorkflowNode

class TestScheduleModels(unittest.TestCase):
    def test_schedule_models_register_tables_and_constraints(self):
        from app.database import Base
        from app.models.schedule import PipelineSchedule, PipelineScheduleRun

        self.assertEqual(PipelineSchedule.__tablename__, "pipeline_schedules")
        self.assertEqual(PipelineScheduleRun.__tablename__, "pipeline_schedule_runs")
        self.assertIn("pipeline_schedules", Base.metadata.tables)
        self.assertIn("pipeline_schedule_runs", Base.metadata.tables)
        constraints = Base.metadata.tables["pipeline_schedule_runs"].constraints
        self.assertTrue(
            any(
                constraint.name == "uq_pipeline_schedule_runs_schedule_time"
                for constraint in constraints
            )
        )

    def test_schedule_tables_have_due_and_history_indexes(self):
        from app.database import Base
        from app.models.schedule import PipelineSchedule, PipelineScheduleRun  # noqa: F401

        due_indexes = {index.name for index in Base.metadata.tables["pipeline_schedules"].indexes}
        history_indexes = {index.name for index in Base.metadata.tables["pipeline_schedule_runs"].indexes}
        self.assertIn("ix_pipeline_schedules_due", due_indexes)
        self.assertIn("ix_pipeline_schedule_runs_history", history_indexes)
        self.assertIn("ix_pipeline_schedule_runs_retry", history_indexes)


class TestScheduleCalendar(unittest.TestCase):
    def test_next_occurrence_uses_cron_and_utc(self):
        from app.services.pipeline_scheduler import next_occurrence

        base = datetime(2026, 7, 18, 12, 1, tzinfo=timezone.utc)
        self.assertEqual(
            next_occurrence("*/5 * * * *", "UTC", base),
            datetime(2026, 7, 18, 12, 5, tzinfo=timezone.utc),
        )

    def test_next_occurrence_converts_named_timezone_to_utc(self):
        from app.services.pipeline_scheduler import next_occurrence

        base = datetime(2026, 7, 18, 19, 1, tzinfo=timezone.utc)
        self.assertEqual(
            next_occurrence("0 4 * * *", "Asia/Shanghai", base),
            datetime(2026, 7, 18, 20, 0, tzinfo=timezone.utc),
        )

    def test_invalid_expression_has_stable_error_code(self):
        from app.services.pipeline_scheduler import ScheduleError, next_occurrence

        with self.assertRaises(ScheduleError) as raised:
            next_occurrence("not-a-cron", "UTC", datetime.now(timezone.utc))
        self.assertEqual(raised.exception.code, "SCHEDULE_INVALID_CRON")


class TestSchedulerClaims(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.session_factory = sessionmaker(bind=self.engine)
        self.db = self.session_factory()
        self.user = User(username="scheduler-user", password_hash="hash")
        self.db.add(self.user)
        self.db.flush()
        self.project = Project(name="Scheduler project", owner_id=self.user.id)
        self.db.add(self.project)
        self.db.flush()
        self.workflow = Workflow(
            project_id=self.project.id,
            name="Scheduled workflow",
            created_by=self.user.id,
        )
        self.db.add(self.workflow)
        self.db.flush()
        self.now = datetime(2026, 7, 18, 12, 1, tzinfo=timezone.utc)
        self.schedule = PipelineSchedule(
            project_id=self.project.id,
            workflow_id=self.workflow.id,
            created_by=self.user.id,
            name="Daily schedule",
            cron_expression="0 12 * * *",
            timezone="UTC",
            next_run_at=datetime(2026, 7, 18, 12, 0),
        )
        self.db.add(self.schedule)
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def test_two_ticks_create_one_due_occurrence_and_one_workflow_run(self):
        from app.services.pipeline_scheduler import PipelineScheduler

        enqueued = []
        scheduler = PipelineScheduler(
            enqueue=lambda run_id, timeout_seconds=None: enqueued.append(
                (run_id, timeout_seconds)
            ) or "task-1"
        )
        first = scheduler.tick(self.db, now=self.now)
        second = scheduler.tick(self.db, now=self.now)

        self.assertEqual(len(first), 1)
        self.assertEqual(second, [])
        self.assertEqual(len(enqueued), 1)
        self.assertEqual(enqueued[0][1], None)
        self.assertEqual(self.db.query(PipelineScheduleRun).count(), 1)
        self.assertEqual(self.db.query(WorkflowRun).count(), 1)
        self.assertEqual(self.db.query(PipelineScheduleRun).one().status, "claimed")
        self.assertEqual(self.db.query(WorkflowRun).one().task_id, "task-1")
        self.assertEqual(
            self.schedule.next_run_at,
            datetime(2026, 7, 19, 12, 0),
        )


class TestSchedulerPolicies(TestSchedulerClaims):
    def test_pause_and_resume_block_then_recalculate_future_occurrence(self):
        from app.services.pipeline_scheduler import PipelineScheduler

        scheduler = PipelineScheduler(enqueue=lambda run_id, timeout_seconds=None: "unused")
        scheduler.pause(self.db, self.schedule)
        self.assertIsNotNone(self.schedule.paused_at)
        self.assertEqual(scheduler.tick(self.db, now=self.now), [])

        scheduler.resume(self.db, self.schedule, now=self.now)
        self.assertIsNone(self.schedule.paused_at)
        self.assertGreater(self.schedule.next_run_at, self.now.replace(tzinfo=None))

    def test_backfill_is_bounded_and_duplicate_occurrences_are_suppressed(self):
        from app.services.pipeline_scheduler import PipelineScheduler

        scheduler = PipelineScheduler(
            enqueue=lambda run_id, timeout_seconds=None: "backfill-task"
        )
        occurrence = datetime(2026, 7, 17, 12, 0, tzinfo=timezone.utc)
        results = scheduler.backfill(
            self.db,
            self.schedule,
            [occurrence, occurrence],
            now=self.now,
        )

        self.assertEqual([result["status"] for result in results], ["claimed", "skipped"])
        self.assertEqual(results[1]["skip_reason"], "DUPLICATE_OCCURRENCE")
        self.assertEqual(self.db.query(PipelineScheduleRun).count(), 1)

    def test_dependency_not_ready_skips_without_creating_workflow_run(self):
        from app.services.pipeline_scheduler import PipelineScheduler

        dependency = PipelineSchedule(
            project_id=self.project.id,
            workflow_id=self.workflow.id,
            created_by=self.user.id,
            name="Dependency schedule",
            cron_expression="0 12 * * *",
            timezone="UTC",
            next_run_at=datetime(2026, 7, 19, 12, 0),
        )
        self.db.add(dependency)
        self.db.flush()
        self.schedule.dependencies = [str(dependency.id)]
        self.db.commit()

        result = PipelineScheduler(
            enqueue=lambda run_id, timeout_seconds=None: "unused"
        ).tick(
            self.db,
            now=self.now,
        )[0]

        self.assertEqual(result["status"], "skipped")
        self.assertEqual(result["skip_reason"], "DEPENDENCY_NOT_READY")
        self.assertEqual(self.db.query(WorkflowRun).count(), 0)

    def test_dispatch_retry_waits_for_persisted_backoff_deadline(self):
        from app.services.pipeline_scheduler import PipelineScheduler

        attempts = []

        def enqueue(run_id, timeout_seconds=None):
            attempts.append((run_id, timeout_seconds))
            if len(attempts) == 1:
                raise RuntimeError("temporary broker failure")
            return "retry-task"

        self.schedule.retry_policy = {
            "max_attempts": 2,
            "backoff_seconds": 30,
            "max_backoff_seconds": 60,
        }
        self.db.commit()
        scheduler = PipelineScheduler(enqueue=enqueue)
        first = scheduler.tick(self.db, now=self.now)[0]
        before_deadline = scheduler.tick(
            self.db,
            now=self.now + timedelta(seconds=29),
        )
        after_deadline = scheduler.tick(
            self.db,
            now=self.now + timedelta(seconds=30),
        )[0]

        self.assertEqual(first["status"], "retrying")
        self.assertEqual(before_deadline, [])
        self.assertEqual(after_deadline["status"], "claimed")
        self.assertEqual(after_deadline["attempt"], 2)
        self.assertEqual(len(attempts), 2)

    def test_timeout_is_persisted_and_passed_to_dispatcher(self):
        from app.services.pipeline_scheduler import PipelineScheduler

        dispatched = []
        self.schedule.timeout_seconds = 90
        self.db.commit()

        result = PipelineScheduler(
            enqueue=lambda run_id, timeout_seconds=None: dispatched.append(
                (run_id, timeout_seconds)
            ) or "timeout-task"
        ).tick(self.db, now=self.now)[0]

        workflow_run = self.db.query(WorkflowRun).one()
        self.assertEqual(result["status"], "claimed")
        self.assertEqual(workflow_run.timeout_seconds, 90)
        self.assertEqual(dispatched, [(str(workflow_run.id), 90)])

    def test_malformed_persisted_retry_policy_fails_only_its_occurrence(self):
        from app.services.pipeline_scheduler import PipelineScheduler

        self.schedule.retry_policy = {
            "max_attempts": "not-an-integer",
            "backoff_seconds": 30,
        }
        self.db.commit()
        dispatched = []

        result = PipelineScheduler(
            enqueue=lambda run_id, timeout_seconds=None: dispatched.append(run_id)
        ).tick(self.db, now=self.now)[0]

        occurrence = self.db.query(PipelineScheduleRun).one()
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["error_code"], "SCHEDULE_INVALID_RETRY_POLICY")
        self.assertEqual(occurrence.error_code, "SCHEDULE_INVALID_RETRY_POLICY")
        self.assertEqual(dispatched, [])

    def test_terminal_workflow_state_is_reconciled_to_occurrence(self):
        from app.services.pipeline_scheduler import (
            PipelineScheduler,
            reconcile_schedule_runs,
        )

        PipelineScheduler(
            enqueue=lambda run_id, timeout_seconds=None: "terminal-task"
        ).tick(self.db, now=self.now)
        workflow_run = self.db.query(WorkflowRun).one()
        workflow_run.status = "failed"
        workflow_run.error_code = "TASK_HARD_TIMEOUT"
        workflow_run.error_message = "Workflow task exceeded its time limit"
        workflow_run.finished_at = self.now.replace(tzinfo=None)
        self.db.commit()

        self.assertEqual(reconcile_schedule_runs(self.db, now=self.now), 1)
        occurrence = self.db.query(PipelineScheduleRun).one()
        self.assertEqual(occurrence.status, "failed")
        self.assertEqual(occurrence.error_code, "TASK_HARD_TIMEOUT")
        self.assertEqual(occurrence.finished_at, self.now.replace(tzinfo=None))

    def test_stale_pending_occurrence_is_released_for_recovery(self):
        from app.services.pipeline_scheduler import recover_stale_schedule_runs

        occurrence = PipelineScheduleRun(
            schedule_id=self.schedule.id,
            scheduled_for=datetime(2026, 7, 17, 12, 0),
            status="pending",
            claimed_at=datetime.now(timezone.utc) - timedelta(minutes=10),
        )
        self.db.add(occurrence)
        self.db.commit()

        self.assertEqual(recover_stale_schedule_runs(self.db, lease_seconds=60), 1)
        self.assertIsNone(occurrence.claimed_at)
        self.assertEqual(occurrence.status, "pending")

    def test_concurrency_limit_records_skip_without_workflow_run(self):
        from app.services.pipeline_scheduler import PipelineScheduler

        self.schedule.max_concurrency = 1
        active_run = WorkflowRun(
            workflow_id=self.workflow.id,
            status="running",
            workflow_snapshot={"nodes": [], "edges": []},
        )
        self.db.add(active_run)
        self.db.flush()
        self.db.add(
            PipelineScheduleRun(
                schedule_id=self.schedule.id,
                workflow_run_id=active_run.id,
                scheduled_for=datetime(2026, 7, 17, 12, 0),
                status="claimed",
            )
        )
        self.db.commit()

        scheduler = PipelineScheduler(enqueue=lambda run_id, timeout_seconds=None: "unused")
        result = scheduler.tick(self.db, now=self.now)

        self.assertEqual(result[0]["status"], "skipped")
        self.assertEqual(result[0]["skip_reason"], "CONCURRENCY_LIMIT")
        self.assertEqual(self.db.query(WorkflowRun).count(), 1)

    def test_existing_occurrence_suppresses_competing_tick(self):
        from app.services.pipeline_scheduler import PipelineScheduler

        self.db.add(
            PipelineScheduleRun(
                schedule_id=self.schedule.id,
                scheduled_for=datetime(2026, 7, 18, 12, 0),
                status="claimed",
            )
        )
        self.db.commit()
        enqueued = []

        result = PipelineScheduler(
            enqueue=lambda run_id, timeout_seconds=None: enqueued.append(run_id) or "duplicate"
        ).tick(self.db, now=self.now)

        self.assertEqual(result[0]["status"], "skipped")
        self.assertEqual(result[0]["skip_reason"], "DUPLICATE_OCCURRENCE")
        self.assertEqual(enqueued, [])
        self.assertEqual(self.db.query(PipelineScheduleRun).count(), 1)


class TestSchedulerTasks(unittest.TestCase):
    def test_scheduler_tasks_are_registered_and_beat_is_configured(self):
        from app.tasks.celery_app import celery_app

        self.assertIn("ml_platform.scheduler_tick", celery_app.tasks)
        self.assertIn("ml_platform.recover_pipeline_schedules", celery_app.tasks)
        beat_entries = celery_app.conf.beat_schedule.values()
        task_names = {entry["task"] for entry in beat_entries}
        self.assertIn("ml_platform.scheduler_tick", task_names)

    def test_scheduler_tick_uses_short_lived_scheduler_service(self):
        from app.tasks.scheduler_tasks import scheduler_tick

        self.assertEqual(scheduler_tick.name, "ml_platform.scheduler_tick")

    def test_celery_dispatch_applies_schedule_timeout(self):
        from unittest.mock import patch

        from app.tasks.scheduler_tasks import _enqueue_workflow

        with patch(
            "app.tasks.scheduler_tasks.celery_app.send_task"
        ) as send_task:
            send_task.return_value.id = "scheduled-task"
            task_id = _enqueue_workflow("run-1", 90)

        self.assertEqual(task_id, "scheduled-task")
        send_task.assert_called_once_with(
            "ml_platform.execute_workflow",
            args=["run-1"],
            time_limit=90,
        )


@unittest.skipUnless(
    os.getenv("RUN_SCHEDULER_INTEGRATION") == "1",
    "RUN_SCHEDULER_INTEGRATION is not enabled",
)
class TestSchedulerProductionStack(unittest.TestCase):
    def test_postgres_redis_worker_schedule_lifecycle(self):
        from app.database import SessionLocal
        from app.services.pipeline_scheduler import (
            PipelineScheduler,
            reconcile_schedule_runs,
        )
        from app.tasks.scheduler_tasks import _enqueue_workflow

        unique = uuid.uuid4().hex
        now = datetime.now(timezone.utc)
        with SessionLocal() as db:
            user = User(
                username=f"scheduler-integration-{unique}",
                password_hash="integration-only-hash",
            )
            db.add(user)
            db.flush()
            project = Project(
                name=f"Scheduler integration {unique}",
                owner_id=user.id,
            )
            db.add(project)
            db.flush()
            workflow = Workflow(
                project_id=project.id,
                name="Scheduled mechanism workflow",
                created_by=user.id,
            )
            db.add(workflow)
            db.flush()
            db.add(WorkflowNode(
                workflow_id=workflow.id,
                operator_id="mechanism_thermal",
                label="Integration mechanism",
                position_x=0,
                position_y=0,
                params={},
            ))
            schedule = PipelineSchedule(
                project_id=project.id,
                workflow_id=workflow.id,
                created_by=user.id,
                name="Integration schedule",
                cron_expression="0 0 * * *",
                timezone="UTC",
                next_run_at=(now - timedelta(seconds=1)).replace(tzinfo=None),
            )
            db.add(schedule)
            db.commit()
            schedule_id = schedule.id

            scheduler = PipelineScheduler(enqueue=_enqueue_workflow)
            first = scheduler.tick(db, now=now)
            second = scheduler.tick(db, now=now)
            self.assertEqual(first[0]["status"], "claimed")
            self.assertEqual(second, [])
            self.assertEqual(
                db.query(PipelineScheduleRun).filter(
                    PipelineScheduleRun.schedule_id == schedule_id,
                ).count(),
                1,
            )

            first_run_id = uuid.UUID(first[0]["workflow_run_id"])
            self._wait_for_run(db, first_run_id, "completed")
            self.assertEqual(reconcile_schedule_runs(db), 1)

            scheduler.pause(db, schedule)
            self.assertEqual(scheduler.tick(db, now=now), [])
            scheduler.resume(db, schedule, now=now)
            backfill_at = now - timedelta(days=1)
            backfill = scheduler.backfill(db, schedule, [backfill_at], now=now)
            self.assertEqual(backfill[0]["status"], "claimed")
            self._wait_for_run(
                db,
                uuid.UUID(backfill[0]["workflow_run_id"]),
                "completed",
            )
            self.assertEqual(reconcile_schedule_runs(db), 1)
            self.assertEqual(
                db.query(PipelineScheduleRun).filter(
                    PipelineScheduleRun.schedule_id == schedule_id,
                    PipelineScheduleRun.status == "completed",
                ).count(),
                2,
            )

    @staticmethod
    def _wait_for_run(db, run_id, expected_status: str, timeout: float = 30) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            db.expire_all()
            status = db.query(WorkflowRun.status).filter(
                WorkflowRun.id == run_id,
            ).scalar()
            if status == expected_status:
                return
            if status in {"failed", "cancelled"}:
                raise AssertionError(f"Workflow run ended as {status}")
            time.sleep(0.2)
        raise AssertionError(f"Workflow run did not reach {expected_status}")

if __name__ == "__main__":
    unittest.main()
