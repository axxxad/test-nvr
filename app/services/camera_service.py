from sqlalchemy.orm import Session

from app.models.camera import Camera
from app.schemas.camera import CameraCreate
from app.services.recording_service import stop_before_delete


def list_cameras(db: Session) -> list[Camera]:
    return db.query(Camera).order_by(Camera.name).all()


def get_camera(db: Session, camera_id: int) -> Camera | None:
    return db.query(Camera).filter(Camera.id == camera_id).first()


def create_camera(db: Session, data: CameraCreate) -> Camera:
    camera = Camera(
        name=data.name,
        rtsp_url=data.rtsp_url,
        retention_days=data.retention_days,
    )
    db.add(camera)
    db.commit()
    db.refresh(camera)
    return camera


def delete_camera(db: Session, camera: Camera) -> None:
    stop_before_delete(camera.id)
    db.delete(camera)
    db.commit()
