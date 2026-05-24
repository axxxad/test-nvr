from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.camera import Camera
from app.rtsp import build_rtsp_url, parse_rtsp_url
from app.schemas.camera import CameraForm
from app.services.recording_service import stop_before_delete


def list_cameras(db: Session) -> list[Camera]:
    return (
        db.query(Camera)
        .order_by(Camera.sort_order.asc(), Camera.id.asc())
        .all()
    )


def _next_sort_order(db: Session) -> int:
    current_max = db.query(func.max(Camera.sort_order)).scalar()
    return (current_max or 0) + 1


def reorder_cameras(db: Session, camera_ids: list[int]) -> None:
    if not camera_ids:
        return
    known_ids = {
        row[0]
        for row in db.query(Camera.id).filter(Camera.id.in_(camera_ids)).all()
    }
    for index, camera_id in enumerate(camera_ids):
        if camera_id not in known_ids:
            continue
        db.query(Camera).filter(Camera.id == camera_id).update(
            {"sort_order": index},
            synchronize_session=False,
        )
    db.commit()


def get_camera(db: Session, camera_id: int) -> Camera | None:
    return db.query(Camera).filter(Camera.id == camera_id).first()


def form_defaults(camera: Camera | None = None) -> dict:
    if camera is None:
        return {
            "name": "",
            "rtsp_host": "",
            "rtsp_port": 554,
            "rtsp_username": "",
            "rtsp_password": "",
            "rtsp_path": "/Streaming/Channels/101",
            "retention_days": 2,
            "record_audio": False,
        }
    try:
        parts = parse_rtsp_url(camera.rtsp_url)
    except ValueError:
        parts = {
            "host": "",
            "port": 554,
            "username": "",
            "password": "",
            "path": "/Streaming/Channels/101",
        }
    return {
        "name": camera.name,
        "rtsp_host": str(parts["host"]),
        "rtsp_port": int(parts["port"]),
        "rtsp_username": str(parts["username"]),
        "rtsp_password": str(parts["password"]),
        "rtsp_path": str(parts["path"]),
        "retention_days": camera.retention_days,
        "record_audio": camera.record_audio,
    }


def _rtsp_url_from_form(data: CameraForm) -> str:
    return build_rtsp_url(
        data.rtsp_host,
        data.rtsp_port,
        data.rtsp_username,
        data.rtsp_password,
        data.rtsp_path,
    )


def create_camera(db: Session, data: CameraForm) -> Camera:
    camera = Camera(
        name=data.name,
        rtsp_url=_rtsp_url_from_form(data),
        retention_days=data.retention_days,
        record_audio=data.record_audio,
        sort_order=_next_sort_order(db),
    )
    db.add(camera)
    db.commit()
    db.refresh(camera)
    return camera


def update_camera(db: Session, camera: Camera, data: CameraForm) -> Camera:
    retention_changed = camera.retention_days != data.retention_days
    camera.name = data.name
    camera.rtsp_url = _rtsp_url_from_form(data)
    camera.retention_days = data.retention_days
    camera.record_audio = data.record_audio
    db.commit()
    db.refresh(camera)
    if retention_changed:
        from app.services.retention_service import apply_retention_policy

        apply_retention_policy(db, camera_id=camera.id)
    return camera


def delete_camera(db: Session, camera: Camera) -> None:
    stop_before_delete(camera.id)
    db.delete(camera)
    db.commit()
