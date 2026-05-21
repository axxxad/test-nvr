import logging
import re
from datetime import datetime, timedelta
from pathlib import Path

from sqlalchemy.orm import Session

from app.config import settings
from app.models.segment import Segment
from app.timezone_util import parse_filename_timestamp

logger = logging.getLogger(__name__)

_SEGMENT_PATH = re.compile(
    r"^cam(?P<camera_id>\d+)/(?P<year>\d{4})/(?P<month>\d{2})/(?P<day>\d{2})/"
    r"(?P<hour>\d{2})-(?P<minute>\d{2})-(?P<second>\d{2})\.mp4$"
)


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


def refresh_segment_times_from_paths(db: Session) -> int:
    """Re-derive start/end from filenames (fixes timezone after APP_TIMEZONE change)."""
    segment_duration = timedelta(seconds=settings.segment_duration_seconds)
    updated = 0
    for segment in db.query(Segment).all():
        parsed = parse_segment_relative_path(segment.file_path)
        if parsed is None:
            continue
        _, start_time = parsed
        end_time = start_time + segment_duration
        if segment.start_time != start_time or segment.end_time != end_time:
            segment.start_time = start_time
            segment.end_time = end_time
            updated += 1
    if updated:
        db.commit()
        logger.info("Refreshed segment times for %s row(s)", updated)
    return updated


def index_recordings(db: Session) -> int:
    """Scan recordings dir and upsert segment rows. Returns count of new segments."""
    recordings_dir = settings.recordings_dir
    if not recordings_dir.exists():
        return 0

    existing_paths = {
        row[0]
        for row in db.query(Segment.file_path).all()
    }
    segment_duration = timedelta(seconds=settings.segment_duration_seconds)
    added = 0

    for path in recordings_dir.rglob("*.mp4"):
        if not path.is_file():
            continue
        try:
            relative = path.relative_to(recordings_dir).as_posix()
        except ValueError:
            continue

        parsed = parse_segment_relative_path(relative)
        if parsed is None:
            continue

        camera_id, start_time = parsed
        if relative in existing_paths:
            continue

        try:
            size_bytes = path.stat().st_size
        except OSError:
            size_bytes = 0

        segment = Segment(
            camera_id=camera_id,
            file_path=relative,
            start_time=start_time,
            end_time=start_time + segment_duration,
            size_bytes=size_bytes,
        )
        db.add(segment)
        existing_paths.add(relative)
        added += 1

    if added:
        db.commit()
        logger.info("Indexed %s new segment(s)", added)

    refresh_segment_times_from_paths(db)
    return added


def prune_missing_files(db: Session) -> int:
    """Remove DB rows when the file no longer exists on disk."""
    removed = 0
    for segment in db.query(Segment).all():
        full_path = settings.recordings_dir / segment.file_path
        if not full_path.is_file():
            db.delete(segment)
            removed += 1
    if removed:
        db.commit()
        logger.info("Pruned %s missing segment row(s)", removed)
    return removed
