import logging
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

from app.config import settings
from app.timezone_util import ensure_aware, parse_filename_timestamp

logger = logging.getLogger(__name__)

_SEGMENT_PATH = re.compile(
    r"^cam(?P<camera_id>\d+)/(?P<year>\d{4})/(?P<month>\d{2})/(?P<day>\d{2})/"
    r"(?P<hour>\d{2})-(?P<minute>\d{2})-(?P<second>\d{2})\.mp4$"
)


@dataclass(frozen=True)
class SegmentInfo:
    camera_id: int
    file_path: str
    start_time: datetime
    end_time: datetime
    size_bytes: int

    @property
    def id(self) -> str:
        return self.file_path


def parse_segment_relative_path(relative: str) -> tuple[int, datetime] | None:
    match = _SEGMENT_PATH.match(relative.replace("\\", "/"))
    if not match:
        return None
    camera_id = int(match.group("camera_id"))
    start = parse_filename_timestamp(
        int(match.group("year")),
        int(match.group("month")),
        int(match.group("day")),
        int(match.group("hour")),
        int(match.group("minute")),
        int(match.group("second")),
    )
    return camera_id, start


def _segment_duration() -> timedelta:
    return timedelta(seconds=settings.segment_duration_seconds)


def segment_info_from_path(path: Path, *, recordings_dir: Path | None = None) -> SegmentInfo | None:
    root = recordings_dir or settings.recordings_dir
    try:
        relative = path.relative_to(root).as_posix()
    except ValueError:
        return None

    parsed = parse_segment_relative_path(relative)
    if parsed is None:
        return None

    camera_id, start_time = parsed
    try:
        size_bytes = path.stat().st_size
    except OSError:
        size_bytes = 0

    end_time = start_time + _segment_duration()
    return SegmentInfo(
        camera_id=camera_id,
        file_path=relative,
        start_time=start_time,
        end_time=end_time,
        size_bytes=size_bytes,
    )


def resolve_playback_path(camera_id: int, relative_path: str) -> Path | None:
    """Return absolute path if relative_path is a valid clip for this camera."""
    normalized = relative_path.replace("\\", "/").lstrip("/")
    expected_prefix = f"cam{camera_id}/"
    if not normalized.startswith(expected_prefix):
        return None

    parsed = parse_segment_relative_path(normalized)
    if parsed is None or parsed[0] != camera_id:
        return None

    full = (settings.recordings_dir / normalized).resolve()
    root = settings.recordings_dir.resolve()
    try:
        full.relative_to(root)
    except ValueError:
        return None

    if not full.is_file():
        return None
    return full


def _days_in_range(start: datetime, end: datetime) -> list[date]:
    start = ensure_aware(start)
    end = ensure_aware(end)
    current = start.date()
    last = end.date()
    days: list[date] = []
    while current <= last:
        days.append(current)
        current += timedelta(days=1)
    return days


def _iter_camera_clips(camera_id: int, start: datetime, end: datetime):
    recordings_dir = settings.recordings_dir
    cam_dir = recordings_dir / f"cam{camera_id}"
    if not cam_dir.is_dir():
        return

    for day in _days_in_range(start, end):
        day_dir = cam_dir / day.strftime("%Y/%m/%d")
        if not day_dir.is_dir():
            continue
        for path in sorted(day_dir.glob("*.mp4")):
            if not path.is_file():
                continue
            info = segment_info_from_path(path, recordings_dir=recordings_dir)
            if info is not None:
                yield info


def list_segments_for_range(
    camera_id: int,
    start: datetime,
    end: datetime,
) -> list[SegmentInfo]:
    """Clips that overlap [start, end], ordered by start_time."""
    start = ensure_aware(start)
    end = ensure_aware(end)
    segments: list[SegmentInfo] = []
    for info in _iter_camera_clips(camera_id, start, end):
        if info.start_time < end and info.end_time > start:
            segments.append(info)
    return segments


def iter_all_segments() -> list[SegmentInfo]:
    """All clips under recordings_dir (for retention / disk pressure)."""
    recordings_dir = settings.recordings_dir
    if not recordings_dir.exists():
        return []

    segments: list[SegmentInfo] = []
    for path in recordings_dir.rglob("*.mp4"):
        if not path.is_file():
            continue
        info = segment_info_from_path(path, recordings_dir=recordings_dir)
        if info is not None:
            segments.append(info)
    return segments


def iter_segments_for_camera(camera_id: int) -> list[SegmentInfo]:
    cam_dir = settings.recordings_dir / f"cam{camera_id}"
    if not cam_dir.is_dir():
        return []

    segments: list[SegmentInfo] = []
    for path in cam_dir.rglob("*.mp4"):
        if not path.is_file():
            continue
        info = segment_info_from_path(path)
        if info is not None and info.camera_id == camera_id:
            segments.append(info)
    return segments


def get_latest_segment_end(camera_id: int) -> datetime | None:
    latest: datetime | None = None
    for info in iter_segments_for_camera(camera_id):
        end = ensure_aware(info.end_time)
        if latest is None or end > latest:
            latest = end
    return latest


def get_earliest_segment_start(camera_id: int) -> datetime | None:
    earliest: datetime | None = None
    for info in iter_segments_for_camera(camera_id):
        start = ensure_aware(info.start_time)
        if earliest is None or start < earliest:
            earliest = start
    return earliest


def list_segments_for_day(
    camera_id: int,
    day_start: datetime,
    day_end: datetime,
) -> list[SegmentInfo]:
    return list_segments_for_range(camera_id, day_start, day_end)
