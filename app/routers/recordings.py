import json
from datetime import datetime, time, timedelta
from pathlib import Path
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from starlette import status
from urllib.parse import quote

from app.config import settings
from app.database import get_db
from app.models.segment import Segment
from app.services import camera_service
from app.services.export_service import ExportError, export_clip
from app.services.recording_service import is_recording
from app.services.segment_indexer import index_recordings
from app.services.segment_service import (
    get_latest_segment_end,
    list_segments_for_range,
)
from app.timezone_util import (
    format_form_local,
    get_tz,
    now,
    parse_form_local,
    start_of_day,
    tz_label,
)

router = APIRouter(prefix="/cameras", tags=["recordings"])
templates = Jinja2Templates(
    directory=str(Path(__file__).resolve().parent.parent / "templates")
)


def _default_range_for_camera(
    db: Session,
    camera_id: int,
    *,
    recording_active: bool,
) -> tuple[str, str, str]:
    """Returns (from_val, to_val, hint describing the to default)."""
    current = now()
    latest_end = get_latest_segment_end(db, camera_id)

    if recording_active:
        to_dt = current
        to_hint = "now (recording)"
    elif latest_end is not None:
        to_dt = latest_end
        to_hint = f"latest recording ({format_form_local(latest_end).split('T', 1)[1]})"
    else:
        to_dt = current
        to_hint = "now"

    from_dt = start_of_day(to_dt)
    return (
        format_form_local(from_dt),
        format_form_local(to_dt),
        to_hint,
    )


def _range_presets(
    db: Session,
    camera_id: int,
    *,
    recording_active: bool,
) -> dict[str, tuple[str, str, str]]:
    current = now()
    latest_end = get_latest_segment_end(db, camera_id)

    def to_dt() -> datetime:
        if recording_active:
            return current
        return latest_end or current

    today_to = to_dt()
    today_from = start_of_day(today_to)

    yesterday_date = current.date() - timedelta(days=1)
    y_from = datetime.combine(yesterday_date, time.min, tzinfo=get_tz())
    y_to = datetime.combine(yesterday_date, time(23, 59, 59), tzinfo=get_tz())

    last24_from = current - timedelta(hours=24)

    def pack(start: datetime, end: datetime) -> tuple[str, str]:
        return format_form_local(start), format_form_local(end)

    return {
        "today": pack(today_from, today_to),
        "yesterday": pack(y_from, y_to),
        "last24h": pack(last24_from, today_to),
    }


def _preset_url(camera_id: int, from_val: str, to_val: str) -> str:
    return f"/cameras/{camera_id}/recordings?{urlencode({'from': from_val, 'to': to_val})}"


def _segments_json(segments: list[Segment], camera_id: int) -> str:
    payload = [
        {
            "id": seg.id,
            "start": seg.start_time.isoformat(),
            "end": seg.end_time.isoformat(),
            "url": f"/cameras/{camera_id}/segments/{seg.id}/play",
        }
        for seg in segments
    ]
    return json.dumps(payload)


def _get_segment_or_404(db: Session, camera_id: int, segment_id: int) -> Segment:
    segment = (
        db.query(Segment)
        .filter(Segment.id == segment_id, Segment.camera_id == camera_id)
        .first()
    )
    if segment is None:
        raise HTTPException(status_code=404, detail="Segment not found")
    return segment


@router.get("/{camera_id}/recordings", response_class=HTMLResponse)
def browse_recordings(
    request: Request,
    camera_id: int,
    db: Session = Depends(get_db),
):
    camera = camera_service.get_camera(db, camera_id)
    if camera is None:
        return RedirectResponse(url="/cameras", status_code=status.HTTP_303_SEE_OTHER)

    index_recordings(db)

    recording_active = is_recording(camera_id)
    default_from, default_to, to_hint = _default_range_for_camera(
        db, camera_id, recording_active=recording_active
    )
    has_range_query = "from" in request.query_params or "to" in request.query_params
    from_val = request.query_params.get("from", default_from)
    to_val = request.query_params.get("to", default_to)
    if not has_range_query:
        from_val, to_val = default_from, default_to

    presets = _range_presets(db, camera_id, recording_active=recording_active)
    preset_links = {key: _preset_url(camera_id, p[0], p[1]) for key, p in presets.items()}
    active_preset = next(
        (key for key, p in presets.items() if from_val == p[0] and to_val == p[1]),
        None,
    )

    error = request.query_params.get("error")
    flash = request.query_params.get("flash")

    segments: list[Segment] = []
    start_dt = parse_form_local(from_val)
    end_dt = parse_form_local(to_val)

    if start_dt and end_dt:
        if end_dt <= start_dt:
            error = error or "End time must be after start time."
        else:
            segments = list_segments_for_range(db, camera_id, start_dt, end_dt)

    range_start_iso = segments[0].start_time.isoformat() if segments else ""
    range_end_iso = segments[-1].end_time.isoformat() if segments else ""

    return templates.TemplateResponse(
        request,
        "recordings/browse.html",
        {
            "camera": camera,
            "segments": segments,
            "segments_json": _segments_json(segments, camera_id),
            "from_val": from_val,
            "to_val": to_val,
            "selection_start_iso": start_dt.isoformat() if start_dt else "",
            "selection_end_iso": end_dt.isoformat() if end_dt else "",
            "range_start_iso": range_start_iso,
            "range_end_iso": range_end_iso,
            "error": error,
            "flash": flash,
            "recording_active": recording_active,
            "segment_duration": settings.segment_duration_seconds,
            "to_hint": to_hint,
            "preset_links": preset_links,
            "active_preset": active_preset,
            "tz_label": tz_label(),
        },
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
    db: Session = Depends(get_db),
):
    camera = camera_service.get_camera(db, camera_id)
    if camera is None:
        return RedirectResponse(url="/cameras", status_code=status.HTTP_303_SEE_OTHER)

    start_dt = parse_form_local(from_time)
    end_dt = parse_form_local(to_time)
    query = f"from={from_time}&to={to_time}"

    if not start_dt or not end_dt:
        return RedirectResponse(
            url=f"/cameras/{camera_id}/recordings?{query}&error=Invalid+date+or+time",
            status_code=status.HTTP_303_SEE_OTHER,
        )
    if end_dt <= start_dt:
        return RedirectResponse(
            url=f"/cameras/{camera_id}/recordings?{query}&error=End+time+must+be+after+start",
            status_code=status.HTTP_303_SEE_OTHER,
        )

    try:
        output_path = export_clip(db, camera_id, start_dt, end_dt)
    except ExportError as exc:
        return RedirectResponse(
            url=f"/cameras/{camera_id}/recordings?{query}&error={quote(str(exc))}",
            status_code=status.HTTP_303_SEE_OTHER,
        )

    filename = (
        f"{camera.name.replace(' ', '_')}_"
        f"{start_dt.strftime('%Y%m%d_%H%M%S')}-{end_dt.strftime('%H%M%S')}.mp4"
    )
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
    default_from, default_to, _ = _default_range_for_camera(
        db, camera_id, recording_active=is_recording(camera_id)
    )
    query = urlencode({"from": default_from, "to": default_to, "flash": "Settings saved"})
    return RedirectResponse(
        url=f"/cameras/{camera_id}/recordings?{query}",
        status_code=status.HTTP_303_SEE_OTHER,
    )
