import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.config import settings
from app.models.camera import Camera
from app.models.segment import Segment

logger = logging.getLogger(__name__)


def run_retention_cleanup(db: Session) -> int:
    """Delete segment files and DB rows older than each camera's retention_days."""
    now = datetime.now(timezone.utc)
    deleted = 0

    cameras = db.query(Camera).all()
    for camera in cameras:
        cutoff = now - timedelta(days=camera.retention_days)
        old_segments = (
            db.query(Segment)
            .filter(Segment.camera_id == camera.id, Segment.end_time < cutoff)
            .all()
        )
        for segment in old_segments:
            path = settings.recordings_dir / segment.file_path
            if path.is_file():
                try:
                    path.unlink()
                    deleted += 1
                except OSError:
                    logger.warning("Could not delete %s", path)
            db.delete(segment)

    if deleted:
        logger.info("Retention cleanup removed %s file(s)", deleted)
    db.commit()
    return deleted
