import unittest
from datetime import datetime, timezone

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


if __name__ == "__main__":
    unittest.main()
