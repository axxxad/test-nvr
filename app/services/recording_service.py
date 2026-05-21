import logging
from pathlib import Path

from sqlalchemy.orm import Session

from app.config import settings
from app.models.camera import Camera
from app.rtsp import rtsp_url_for_ffmpeg
from app.services.recording_manager import recording_manager

logger = logging.getLogger(__name__)


def camera_recordings_dir(camera_id: int) -> Path:
    return settings.recordings_dir / f"cam{camera_id}"


def is_recording(camera_id: int) -> bool:
    return recording_manager.is_active(camera_id)


def start_recording(camera: Camera) -> None:
    ffmpeg_url = rtsp_url_for_ffmpeg(camera.rtsp_url)
    recording_manager.start(camera.id, ffmpeg_url, camera_recordings_dir(camera.id))


def stop_recording(camera_id: int) -> None:
    recording_manager.stop(camera_id)


def enable_recording(db: Session, camera: Camera) -> None:
    camera.recording_enabled = True
    db.commit()
    start_recording(camera)


def disable_recording(db: Session, camera: Camera) -> None:
    camera.recording_enabled = False
    db.commit()
    stop_recording(camera.id)


def restore_enabled_recordings(db: Session) -> None:
    cameras = db.query(Camera).filter(Camera.recording_enabled.is_(True)).all()
    for camera in cameras:
        try:
            start_recording(camera)
        except Exception:
            logger.exception("Failed to restore recording for camera %s", camera.id)


def stop_before_delete(camera_id: int) -> None:
    stop_recording(camera_id)
