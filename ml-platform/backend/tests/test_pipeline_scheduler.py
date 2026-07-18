import unittest
from datetime import datetime, timezone


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
