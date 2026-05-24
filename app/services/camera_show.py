import json
from datetime import datetime, time, timedelta
from urllib.parse import quote, urlencode

from fastapi import Request
from sqlalchemy.orm import Session

from app.config import settings
from app.rtsp import mask_rtsp_url, parse_rtsp_url
from app.services import camera_service
from app.services.disk_service import (
    format_gib,
    is_disk_pressure_active,
    recordings_disk_usage,
)
from app.services.recording_service import is_recording
from app.services.segment_service import (
    SegmentInfo,
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

SHOW_TABS = frozenset({"live", "recordings", "details"})


def parse_active_tab(value: str | None) -> str:
    if value in SHOW_TABS:
        return value
    return "recordings"


def connection_context(camera) -> tuple[dict | None, str]:
    try:
        parts = parse_rtsp_url(camera.rtsp_url)
        connection = {
            "host": parts["host"],
            "port": parts["port"],
            "username": parts["username"],
            "path": parts["path"],
        }
    except ValueError:
        connection = None
    return connection, mask_rtsp_url(camera.rtsp_url)


def _default_range_for_camera(
    camera_id: int,
    *,
    recording_active: bool,
) -> tuple[str, str, str]:
    current = now()
    latest_end = get_latest_segment_end(camera_id)

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
    camera_id: int,
    *,
    recording_active: bool,
) -> dict[str, tuple[str, str, str]]:
    current = now()
    latest_end = get_latest_segment_end(camera_id)

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
    return f"/cameras/{camera_id}?{urlencode({'tab': 'recordings', 'from': from_val, 'to': to_val})}"


def _segments_json(segments: list[SegmentInfo], camera_id: int) -> str:
    payload = [
        {
            "id": seg.id,
            "path": seg.file_path,
            "start": seg.start_time.isoformat(),
            "end": seg.end_time.isoformat(),
            "url": (
                f"/cameras/{camera_id}/recordings/play"
                f"?path={quote(seg.file_path, safe='')}"
            ),
        }
        for seg in segments
    ]
    return json.dumps(payload)


def build_recordings_tab_context(
    request: Request,
    db: Session,
    camera_id: int,
) -> dict:
    recording_active = is_recording(camera_id)
    default_from, default_to, to_hint = _default_range_for_camera(
        camera_id, recording_active=recording_active
    )
    has_range_query = "from" in request.query_params or "to" in request.query_params
    from_val = request.query_params.get("from", default_from)
    to_val = request.query_params.get("to", default_to)
    if not has_range_query:
        from_val, to_val = default_from, default_to

    presets = _range_presets(camera_id, recording_active=recording_active)
    preset_links = {key: _preset_url(camera_id, p[0], p[1]) for key, p in presets.items()}
    active_preset = next(
        (key for key, p in presets.items() if from_val == p[0] and to_val == p[1]),
        None,
    )

    recordings_error = request.query_params.get("error")

    segments: list[SegmentInfo] = []
    start_dt = parse_form_local(from_val)
    end_dt = parse_form_local(to_val)

    if start_dt and end_dt:
        if end_dt <= start_dt:
            recordings_error = recordings_error or "End time must be after start time."
        else:
            segments = list_segments_for_range(camera_id, start_dt, end_dt)

    range_start_iso = segments[0].start_time.isoformat() if segments else ""
    range_end_iso = segments[-1].end_time.isoformat() if segments else ""

    disk_total, _, disk_free = recordings_disk_usage()

    return {
        "segments": segments,
        "disk_free_gib": format_gib(disk_free),
        "disk_total_gib": format_gib(disk_total),
        "disk_pressure_active": is_disk_pressure_active(),
        "segments_json": _segments_json(segments, camera_id),
        "from_val": from_val,
        "to_val": to_val,
        "selection_start_iso": start_dt.isoformat() if start_dt else "",
        "selection_end_iso": end_dt.isoformat() if end_dt else "",
        "range_start_iso": range_start_iso,
        "range_end_iso": range_end_iso,
        "recordings_error": recordings_error,
        "recording_active": recording_active,
        "segment_duration": settings.segment_duration_seconds,
        "to_hint": to_hint,
        "preset_links": preset_links,
        "active_preset": active_preset,
        "tz_label": tz_label(),
        "export_name_val": request.query_params.get("export_name", ""),
    }


def build_camera_show_context(
    request: Request,
    db: Session,
    camera_id: int,
    *,
    active_tab: str,
) -> dict | None:
    camera = camera_service.get_camera(db, camera_id)
    if camera is None:
        return None

    connection, masked_url = connection_context(camera)
    flash = request.query_params.get("flash")

    ctx: dict = {
        "camera": camera,
        "active_tab": active_tab,
        "flash": flash,
        "masked_url": masked_url,
        "connection": connection,
        "recording_enabled": camera.recording_enabled,
        "recording_active": is_recording(camera_id),
    }

    if active_tab == "recordings":
        recordings_ctx = build_recordings_tab_context(request, db, camera_id)
        if not recordings_ctx["export_name_val"]:
            recordings_ctx["export_name_val"] = camera.name
        ctx.update(recordings_ctx)

    return ctx
