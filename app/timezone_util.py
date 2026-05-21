"""Single app timezone for filenames, DB, and UI (must match container TZ for FFmpeg)."""

from datetime import datetime, time
from functools import lru_cache
from zoneinfo import ZoneInfo

from app.config import settings


@lru_cache
def get_tz() -> ZoneInfo:
    return ZoneInfo(settings.app_timezone)


def now() -> datetime:
    return datetime.now(get_tz())


def parse_filename_timestamp(
    year: int,
    month: int,
    day: int,
    hour: int,
    minute: int,
    second: int,
) -> datetime:
    """Wall-clock time encoded in segment path / FFmpeg strftime."""
    return datetime(year, month, day, hour, minute, second, tzinfo=get_tz())


def parse_form_local(value: str) -> datetime | None:
    """Parse HTML datetime-local value as local app time."""
    value = value.strip()
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=get_tz())
    return dt.astimezone(get_tz())


def format_form_local(dt: datetime) -> str:
    """Value for <input type=\"datetime-local\"> (no offset suffix)."""
    local = dt.astimezone(get_tz()) if dt.tzinfo else dt.replace(tzinfo=get_tz())
    return local.strftime("%Y-%m-%dT%H:%M")


def start_of_day(dt: datetime) -> datetime:
    local = dt.astimezone(get_tz())
    return datetime.combine(local.date(), time.min, tzinfo=get_tz())


def format_display(dt: datetime) -> str:
    return dt.astimezone(get_tz()).strftime("%Y-%m-%d %H:%M:%S")


def tz_label() -> str:
    return settings.app_timezone
