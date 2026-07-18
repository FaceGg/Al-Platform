"""Calendar and persistence services for scheduled pipeline runs."""

from datetime import datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from croniter import CroniterBadCronError, croniter


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
