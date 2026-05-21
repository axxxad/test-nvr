from datetime import datetime, time, timedelta, timezone

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.segment import Segment


def list_segments_for_range(
    db: Session,
    camera_id: int,
    start: datetime,
    end: datetime,
) -> list[Segment]:
    """Segments that overlap [start, end], ordered by start_time."""
    return (
        db.query(Segment)
        .filter(
            Segment.camera_id == camera_id,
            Segment.start_time < end,
            Segment.end_time > start,
        )
        .order_by(Segment.start_time)
        .all()
    )


def get_latest_segment_end(db: Session, camera_id: int) -> datetime | None:
    return (
        db.query(func.max(Segment.end_time))
        .filter(Segment.camera_id == camera_id)
        .scalar()
    )


def get_earliest_segment_start(db: Session, camera_id: int) -> datetime | None:
    return (
        db.query(func.min(Segment.start_time))
        .filter(Segment.camera_id == camera_id)
        .scalar()
    )


def list_segments_for_day(
    db: Session,
    camera_id: int,
    day_start: datetime,
    day_end: datetime,
) -> list[Segment]:
    return list_segments_for_range(db, camera_id, day_start, day_end)
