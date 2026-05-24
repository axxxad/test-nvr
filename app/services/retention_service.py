import logging
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from app.config import settings
from app.models.camera import Camera
from app.services.disk_service import recordings_volume_free_bytes
from app.services.recording_service import maintain_enabled_recordings
from app.services.segment_service import SegmentInfo, iter_all_segments, iter_segments_for_camera
from app.timezone_util import ensure_aware, now

logger = logging.getLogger(__name__)


def retention_cutoff(retention_days: int) -> datetime:
    """Clips with end_time before this instant are outside the retention window."""
    return now() - timedelta(days=retention_days)


def _segment_expired(segment: SegmentInfo, cutoff: datetime) -> bool:
    return ensure_aware(segment.end_time) < cutoff


def _delete_segment_files(segments: list[SegmentInfo]) -> int:
    deleted_files = 0
    for segment in segments:
        path = settings.recordings_dir / segment.file_path
        if path.is_file():
            try:
                path.unlink()
                deleted_files += 1
            except OSError:
                logger.warning("Could not delete %s", path)
    return deleted_files


def run_retention_cleanup(db: Session, *, camera_id: int | None = None) -> int:
    """Delete clip files older than each camera's retention_days."""
    deleted = 0
    cameras = db.query(Camera).all()
    if camera_id is not None:
        cameras = [camera for camera in cameras if camera.id == camera_id]

    for camera in cameras:
        cutoff = retention_cutoff(camera.retention_days)
        segments = iter_segments_for_camera(camera.id)
        expired = [segment for segment in segments if _segment_expired(segment, cutoff)]
        if not expired:
            continue
        deleted += _delete_segment_files(expired)
        logger.info(
            "Retention removed %s clip(s) for camera %s (retention_days=%s, cutoff=%s)",
            len(expired),
            camera.id,
            camera.retention_days,
            cutoff.isoformat(),
        )

    if deleted:
        logger.info("Retention cleanup removed %s file(s)", deleted)
    return deleted


def run_disk_pressure_cleanup(db: Session) -> int:
    """Delete oldest clips when free space on the recordings volume is below minimum."""
    if not settings.disk_pressure_enabled:
        return 0

    free = recordings_volume_free_bytes()
    if free >= settings.disk_min_free_bytes:
        return 0

    deleted = 0
    while free < settings.disk_target_free_bytes:
        all_segments = sorted(
            iter_all_segments(),
            key=lambda s: ensure_aware(s.end_time),
        )
        batch = all_segments[: settings.disk_pressure_batch_size]
        if not batch:
            logger.warning(
                "Disk pressure: no clips left to delete (free=%s bytes, min=%s bytes)",
                free,
                settings.disk_min_free_bytes,
            )
            break

        deleted += _delete_segment_files(batch)
        free = recordings_volume_free_bytes()
        logger.info(
            "Disk pressure removed %s clip(s); free space now %s bytes",
            len(batch),
            free,
        )

    if deleted:
        logger.info("Disk pressure cleanup removed %s file(s) total", deleted)
    return deleted


def apply_retention_policy(db: Session, *, camera_id: int | None = None) -> tuple[int, int]:
    """Run age-based retention, then disk-pressure purge if needed."""
    age_deleted = run_retention_cleanup(db, camera_id=camera_id)
    disk_deleted = run_disk_pressure_cleanup(db)
    if disk_deleted:
        maintain_enabled_recordings(db)
    return age_deleted, disk_deleted
