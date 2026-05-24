import logging
import re
import threading
from datetime import datetime, timedelta
from pathlib import Path

from sqlalchemy import func, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import settings
from app.models.segment import Segment
from app.timezone_util import ensure_aware, now, parse_filename_timestamp

logger = logging.getLogger(__name__)

_index_lock = threading.Lock()
_prune_cursor = 0

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
    """Re-derive start/end from filenames (run manually after APP_TIMEZONE change)."""
    segment_duration = timedelta(seconds=settings.segment_duration_seconds)
    updated = 0
    for segment in db.query(Segment).all():
        parsed = parse_segment_relative_path(segment.file_path)
        if parsed is None:
            continue
        _, start_time = parsed
        end_time = start_time + segment_duration
        seg_start = ensure_aware(segment.start_time)
        seg_end = ensure_aware(segment.end_time)
        if seg_start != start_time or seg_end != end_time:
            segment.start_time = start_time
            segment.end_time = end_time
            updated += 1
    if updated:
        db.commit()
        logger.info("Refreshed segment times for %s row(s)", updated)
    return updated


def _day_path_prefix(dt: datetime) -> str:
    return dt.strftime("%Y/%m/%d")


def _recent_day_prefixes(days_back: int) -> list[str]:
    current = now()
    prefixes: list[str] = []
    for offset in range(days_back + 1):
        day = current - timedelta(days=offset)
        prefixes.append(_day_path_prefix(day))
    return prefixes


def _iter_segment_files(recordings_dir: Path, *, full_scan: bool):
    if full_scan:
        yield from (p for p in recordings_dir.rglob("*.mp4") if p.is_file())
        return

    days_back = max(1, settings.index_scan_days)
    seen_dirs: set[Path] = set()
    for prefix in _recent_day_prefixes(days_back):
        for day_dir in recordings_dir.glob(f"cam*/{prefix}"):
            if not day_dir.is_dir() or day_dir in seen_dirs:
                continue
            seen_dirs.add(day_dir)
            for path in day_dir.glob("*.mp4"):
                if path.is_file():
                    yield path


def _existing_paths_for_scan(db: Session, recordings_dir: Path, *, full_scan: bool) -> set[str]:
    if full_scan:
        return {row[0] for row in db.query(Segment.file_path).all()}

    days_back = max(1, settings.index_scan_days)
    prefixes = _recent_day_prefixes(days_back)
    clauses = [Segment.file_path.like(f"cam%/{prefix}/%") for prefix in prefixes]
    if not clauses:
        return set()
    return {row[0] for row in db.query(Segment.file_path).filter(or_(*clauses)).all()}


def _insert_segment(
    db: Session,
    *,
    camera_id: int,
    relative: str,
    start_time: datetime,
    size_bytes: int,
    existing_paths: set[str],
) -> bool:
    if relative in existing_paths:
        return False

    segment_duration = timedelta(seconds=settings.segment_duration_seconds)
    segment = Segment(
        camera_id=camera_id,
        file_path=relative,
        start_time=start_time,
        end_time=start_time + segment_duration,
        size_bytes=size_bytes,
    )
    db.add(segment)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        existing_paths.add(relative)
        return False

    existing_paths.add(relative)
    return True


def _index_recordings_unlocked(db: Session, *, full_scan: bool) -> int:
    recordings_dir = settings.recordings_dir
    if not recordings_dir.exists():
        return 0

    existing_paths = _existing_paths_for_scan(db, recordings_dir, full_scan=full_scan)
    added = 0

    for path in _iter_segment_files(recordings_dir, full_scan=full_scan):
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

        if _insert_segment(
            db,
            camera_id=camera_id,
            relative=relative,
            start_time=start_time,
            size_bytes=size_bytes,
            existing_paths=existing_paths,
        ):
            added += 1

    if added:
        logger.info(
            "Indexed %s new segment(s) (%s scan)",
            added,
            "full" if full_scan else f"last {settings.index_scan_days} days",
        )
    return added


def index_recordings(db: Session, *, full_scan: bool = False) -> int:
    """Scan recordings dir and insert new segment rows."""
    with _index_lock:
        return _index_recordings_unlocked(db, full_scan=full_scan)


def prune_missing_files(db: Session) -> int:
    """Remove DB rows whose files are missing; processes a batch each call."""
    global _prune_cursor

    total = db.query(func.count(Segment.id)).scalar() or 0
    if total == 0:
        return 0

    batch_size = max(100, settings.prune_batch_size)
    if _prune_cursor >= total:
        _prune_cursor = 0

    segments = (
        db.query(Segment)
        .order_by(Segment.id)
        .offset(_prune_cursor)
        .limit(batch_size)
        .all()
    )
    _prune_cursor = (_prune_cursor + batch_size) % total

    removed = 0
    for segment in segments:
        full_path = settings.recordings_dir / segment.file_path
        if not full_path.is_file():
            db.delete(segment)
            removed += 1

    if removed:
        db.commit()
        logger.info("Pruned %s missing segment row(s) (batch %s)", removed, batch_size)
    return removed
