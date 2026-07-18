import unittest
from datetime import datetime, timedelta, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models.project import Project
from app.models.run import WorkflowRun
from app.models.schedule import PipelineSchedule, PipelineScheduleRun
from app.models.user import User
from app.models.workflow import Workflow

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
        scheduler = PipelineScheduler(enqueue=lambda run_id: enqueued.append(run_id) or "task-1")
        first = scheduler.tick(self.db, now=self.now)
        second = scheduler.tick(self.db, now=self.now)

        self.assertEqual(len(first), 1)
        self.assertEqual(second, [])
        self.assertEqual(len(enqueued), 1)
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

        scheduler = PipelineScheduler(enqueue=lambda run_id: "unused")
        scheduler.pause(self.db, self.schedule)
        self.assertIsNotNone(self.schedule.paused_at)
        self.assertEqual(scheduler.tick(self.db, now=self.now), [])

        scheduler.resume(self.db, self.schedule, now=self.now)
        self.assertIsNone(self.schedule.paused_at)
        self.assertGreater(self.schedule.next_run_at, self.now.replace(tzinfo=None))

    def test_backfill_is_bounded_and_duplicate_occurrences_are_suppressed(self):
        from app.services.pipeline_scheduler import PipelineScheduler

        scheduler = PipelineScheduler(enqueue=lambda run_id: "backfill-task")
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

        result = PipelineScheduler(enqueue=lambda run_id: "unused").tick(
            self.db,
            now=self.now,
        )[0]

        self.assertEqual(result["status"], "skipped")
        self.assertEqual(result["skip_reason"], "DEPENDENCY_NOT_READY")
        self.assertEqual(self.db.query(WorkflowRun).count(), 0)

    def test_dispatch_retries_with_bounded_attempts(self):
        from app.services.pipeline_scheduler import PipelineScheduler

        attempts = []

        def enqueue(run_id):
            attempts.append(run_id)
            if len(attempts) == 1:
                raise RuntimeError("temporary broker failure")
            return "retry-task"

        self.schedule.retry_policy = {"max_attempts": 2, "backoff_seconds": 0}
        self.db.commit()
        result = PipelineScheduler(enqueue=enqueue).tick(self.db, now=self.now)[0]

        self.assertEqual(result["status"], "claimed")
        self.assertEqual(result["attempt"], 2)
        self.assertEqual(len(attempts), 2)

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

        scheduler = PipelineScheduler(enqueue=lambda run_id: "unused")
        result = scheduler.tick(self.db, now=self.now)

        self.assertEqual(result[0]["status"], "skipped")
        self.assertEqual(result[0]["skip_reason"], "CONCURRENCY_LIMIT")
        self.assertEqual(self.db.query(WorkflowRun).count(), 1)


if __name__ == "__main__":
    unittest.main()
