from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import FileResponse, RedirectResponse
from sqlalchemy.orm import Session
from starlette import status

from app.config import settings
from app.database import get_db
from app.export_filename import build_export_download_name
from app.models.segment import Segment
from app.services import camera_service
from app.services.camera_show import _default_range_for_camera
from app.services.export_service import ExportError, export_clip
from app.services.recording_service import is_recording
from app.services.retention_service import apply_retention_policy
from app.timezone_util import parse_form_local

router = APIRouter(prefix="/cameras", tags=["recordings"])


def _get_segment_or_404(db: Session, camera_id: int, segment_id: int) -> Segment:
    segment = (
        db.query(Segment)
        .filter(Segment.id == segment_id, Segment.camera_id == camera_id)
        .first()
    )
    if segment is None:
        raise HTTPException(status_code=404, detail="Segment not found")
    return segment


def _recordings_tab_url(camera_id: int, **params: str) -> str:
    query = {"tab": "recordings", **params}
    return f"/cameras/{camera_id}?{urlencode(query)}"


@router.get("/{camera_id}/recordings")
def browse_recordings(
    request: Request,
    camera_id: int,
    db: Session = Depends(get_db),
):
    if camera_service.get_camera(db, camera_id) is None:
        return RedirectResponse(url="/cameras", status_code=status.HTTP_303_SEE_OTHER)

    params = dict(request.query_params)
    params["tab"] = "recordings"
    return RedirectResponse(
        url=f"/cameras/{camera_id}?{urlencode(params)}",
        status_code=status.HTTP_307_TEMPORARY_REDIRECT,
    )


@router.get("/{camera_id}/segments/{segment_id}/play")
def play_segment(
    camera_id: int,
    segment_id: int,
    db: Session = Depends(get_db),
):
    segment = _get_segment_or_404(db, camera_id, segment_id)
    path = settings.recordings_dir / segment.file_path
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Recording file missing")
    return FileResponse(path, media_type="video/mp4")


@router.post("/{camera_id}/recordings/export")
def export_recording(
    camera_id: int,
    from_time: str = Form(""),
    to_time: str = Form(""),
    export_name: str = Form(""),
    db: Session = Depends(get_db),
):
    camera = camera_service.get_camera(db, camera_id)
    if camera is None:
        return RedirectResponse(url="/cameras", status_code=status.HTTP_303_SEE_OTHER)

    start_dt = parse_form_local(from_time)
    end_dt = parse_form_local(to_time)
    export_params = {
        "from": from_time,
        "to": to_time,
        "export_name": export_name.strip(),
    }

    if not start_dt or not end_dt:
        return RedirectResponse(
            url=_recordings_tab_url(camera_id, error="Invalid date or time", **export_params),
            status_code=status.HTTP_303_SEE_OTHER,
        )
    if end_dt <= start_dt:
        return RedirectResponse(
            url=_recordings_tab_url(
                camera_id, error="End time must be after start", **export_params
            ),
            status_code=status.HTTP_303_SEE_OTHER,
        )

    try:
        output_path = export_clip(db, camera_id, start_dt, end_dt)
    except ExportError as exc:
        return RedirectResponse(
            url=_recordings_tab_url(camera_id, error=str(exc), **export_params),
            status_code=status.HTTP_303_SEE_OTHER,
        )

    filename = build_export_download_name(export_name, camera.name, start_dt, end_dt)
    return FileResponse(
        path=output_path,
        media_type="video/mp4",
        filename=filename,
    )


@router.post("/{camera_id}/settings")
def update_camera_settings(
    camera_id: int,
    retention_days: int = Form(2),
    db: Session = Depends(get_db),
):
    camera = camera_service.get_camera(db, camera_id)
    if camera is None:
        return RedirectResponse(url="/cameras", status_code=status.HTTP_303_SEE_OTHER)

    camera.retention_days = max(1, min(retention_days, 365))
    db.commit()
    age_deleted, disk_deleted = apply_retention_policy(db, camera_id=camera_id)
    default_from, default_to, _ = _default_range_for_camera(
        db, camera_id, recording_active=is_recording(camera_id)
    )
    flash = "Settings saved"
    removed = age_deleted + disk_deleted
    if removed:
        flash = f"Settings saved; removed {removed} old segment(s)"
    query = urlencode(
        {
            "tab": "recordings",
            "from": default_from,
            "to": default_to,
            "flash": flash,
        }
    )
    return RedirectResponse(
        url=f"/cameras/{camera_id}?{query}",
        status_code=status.HTTP_303_SEE_OTHER,
    )
