from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request
from fastapi.responses import FileResponse, RedirectResponse
from sqlalchemy.orm import Session
from starlette import status

from app.database import get_db
from app.export_filename import build_export_download_name
from app.services import camera_service
from app.services.camera_show import _default_range_for_camera
from app.services.export_service import ExportError, export_clip
from app.services.recording_service import is_recording
from app.services.retention_service import apply_retention_policy
from app.services.segment_service import resolve_playback_path
from app.timezone_util import parse_form_local

router = APIRouter(prefix="/cameras", tags=["recordings"])


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


@router.get("/{camera_id}/recordings/play")
def play_recording(
    camera_id: int,
    path: str = Query(..., min_length=1),
    db: Session = Depends(get_db),
):
    if camera_service.get_camera(db, camera_id) is None:
        raise HTTPException(status_code=404, detail="Camera not found")

    file_path = resolve_playback_path(camera_id, path)
    if file_path is None:
        raise HTTPException(status_code=404, detail="Recording not found")
    return FileResponse(file_path, media_type="video/mp4")


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
        output_path = export_clip(camera_id, start_dt, end_dt)
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
        camera_id, recording_active=is_recording(camera_id)
    )
    flash = "Settings saved"
    removed = age_deleted + disk_deleted
    if removed:
        flash = f"Settings saved; removed {removed} old clip(s)"
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
