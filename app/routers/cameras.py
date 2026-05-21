from pathlib import Path

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from pydantic import ValidationError
from sqlalchemy.orm import Session
from starlette import status

from app.database import get_db
from app.rtsp import mask_rtsp_url, parse_rtsp_url
from app.schemas.camera import CameraForm
from app.services import camera_service
from app.services.live_preview import mjpeg_stream
from app.services.recording_service import (
    disable_recording,
    enable_recording,
    is_recording,
)

router = APIRouter(prefix="/cameras", tags=["cameras"])
templates = Jinja2Templates(directory=str(Path(__file__).resolve().parent.parent / "templates"))


def _form_checkbox(value: str | None) -> bool:
    return value is not None and value.lower() not in ("", "0", "false", "off")


def _parse_form(
    name: str,
    rtsp_host: str,
    rtsp_port: int,
    rtsp_username: str,
    rtsp_password: str,
    rtsp_path: str,
    retention_days: int,
    record_audio: str | None = None,
) -> tuple[CameraForm | None, dict[str, str]]:
    try:
        return CameraForm(
            name=name,
            rtsp_host=rtsp_host,
            rtsp_port=rtsp_port,
            rtsp_username=rtsp_username,
            rtsp_password=rtsp_password,
            rtsp_path=rtsp_path,
            retention_days=retention_days,
            record_audio=_form_checkbox(record_audio),
        ), {}
    except ValidationError as exc:
        errors: dict[str, str] = {}
        for err in exc.errors():
            field = str(err["loc"][0]) if err["loc"] else "_form"
            errors[field] = err["msg"]
        return None, errors


def _form_context(errors: dict, values: dict) -> dict:
    return {**values, "errors": errors}


def _recording_states(cameras) -> dict[int, dict[str, bool]]:
    return {
        camera.id: {
            "enabled": camera.recording_enabled,
            "active": is_recording(camera.id),
        }
        for camera in cameras
    }


@router.get("", response_class=HTMLResponse)
def list_cameras(request: Request, db: Session = Depends(get_db)):
    flash = request.query_params.get("flash")
    cameras = camera_service.list_cameras(db)
    return templates.TemplateResponse(
        request,
        "cameras/list.html",
        {
            "cameras": cameras,
            "flash": flash,
            "recording": _recording_states(cameras),
        },
    )


@router.get("/new", response_class=HTMLResponse)
def new_camera_form(request: Request):
    return templates.TemplateResponse(
        request,
        "cameras/form.html",
        {
            "title": "Add camera",
            "submit_label": "Add camera",
            "action_url": "/cameras/new",
            **_form_context({}, camera_service.form_defaults()),
        },
    )


@router.post("/new")
def create_camera(
    request: Request,
    name: str = Form(""),
    rtsp_host: str = Form(""),
    rtsp_port: int = Form(554),
    rtsp_username: str = Form(""),
    rtsp_password: str = Form(""),
    rtsp_path: str = Form("/Streaming/Channels/101"),
    retention_days: int = Form(2),
    record_audio: str | None = Form(None),
    db: Session = Depends(get_db),
):
    values = {
        "name": name,
        "rtsp_host": rtsp_host,
        "rtsp_port": rtsp_port,
        "rtsp_username": rtsp_username,
        "rtsp_password": rtsp_password,
        "rtsp_path": rtsp_path,
        "retention_days": retention_days,
        "record_audio": _form_checkbox(record_audio),
    }
    data, errors = _parse_form(
        name=name,
        rtsp_host=rtsp_host,
        rtsp_port=rtsp_port,
        rtsp_username=rtsp_username,
        rtsp_password=rtsp_password,
        rtsp_path=rtsp_path,
        retention_days=retention_days,
        record_audio=record_audio,
    )
    if data is None:
        return templates.TemplateResponse(
            request,
            "cameras/form.html",
            {
                "title": "Add camera",
                "submit_label": "Add camera",
                "action_url": "/cameras/new",
                **_form_context(errors, values),
            },
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        )

    camera = camera_service.create_camera(db, data)
    return RedirectResponse(
        url=f"/cameras/{camera.id}?flash=Camera+added",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.get("/{camera_id}", response_class=HTMLResponse)
def camera_detail(request: Request, camera_id: int, db: Session = Depends(get_db)):
    camera = camera_service.get_camera(db, camera_id)
    if camera is None:
        return RedirectResponse(url="/cameras", status_code=status.HTTP_303_SEE_OTHER)

    flash = request.query_params.get("flash")
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

    return templates.TemplateResponse(
        request,
        "cameras/detail.html",
        {
            "camera": camera,
            "flash": flash,
            "masked_url": mask_rtsp_url(camera.rtsp_url),
            "connection": connection,
            "recording_enabled": camera.recording_enabled,
            "recording_active": is_recording(camera_id),
        },
    )


@router.get("/{camera_id}/edit", response_class=HTMLResponse)
def edit_camera_form(request: Request, camera_id: int, db: Session = Depends(get_db)):
    camera = camera_service.get_camera(db, camera_id)
    if camera is None:
        return RedirectResponse(url="/cameras", status_code=status.HTTP_303_SEE_OTHER)

    return templates.TemplateResponse(
        request,
        "cameras/form.html",
        {
            "title": "Edit camera",
            "submit_label": "Save changes",
            "action_url": f"/cameras/{camera_id}/edit",
            **_form_context({}, camera_service.form_defaults(camera)),
        },
    )


@router.post("/{camera_id}/edit")
def update_camera(
    request: Request,
    camera_id: int,
    name: str = Form(""),
    rtsp_host: str = Form(""),
    rtsp_port: int = Form(554),
    rtsp_username: str = Form(""),
    rtsp_password: str = Form(""),
    rtsp_path: str = Form("/Streaming/Channels/101"),
    retention_days: int = Form(2),
    record_audio: str | None = Form(None),
    db: Session = Depends(get_db),
):
    camera = camera_service.get_camera(db, camera_id)
    if camera is None:
        return RedirectResponse(url="/cameras", status_code=status.HTTP_303_SEE_OTHER)

    was_recording = camera.recording_enabled
    values = {
        "name": name,
        "rtsp_host": rtsp_host,
        "rtsp_port": rtsp_port,
        "rtsp_username": rtsp_username,
        "rtsp_password": rtsp_password,
        "rtsp_path": rtsp_path,
        "retention_days": retention_days,
        "record_audio": _form_checkbox(record_audio),
    }
    data, errors = _parse_form(
        name=name,
        rtsp_host=rtsp_host,
        rtsp_port=rtsp_port,
        rtsp_username=rtsp_username,
        rtsp_password=rtsp_password,
        rtsp_path=rtsp_path,
        retention_days=retention_days,
        record_audio=record_audio,
    )
    if data is None:
        return templates.TemplateResponse(
            request,
            "cameras/form.html",
            {
                "title": "Edit camera",
                "submit_label": "Save changes",
                "action_url": f"/cameras/{camera_id}/edit",
                **_form_context(errors, values),
            },
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        )

    camera_service.update_camera(db, camera, data)
    if was_recording:
        disable_recording(db, camera)
        camera = camera_service.get_camera(db, camera_id)
        if camera:
            enable_recording(db, camera)

    return RedirectResponse(
        url=f"/cameras/{camera_id}?flash=Camera+updated",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.get("/{camera_id}/live", response_class=HTMLResponse)
def live_preview_page(request: Request, camera_id: int, db: Session = Depends(get_db)):
    camera = camera_service.get_camera(db, camera_id)
    if camera is None:
        return RedirectResponse(url="/cameras", status_code=status.HTTP_303_SEE_OTHER)

    return templates.TemplateResponse(
        request,
        "cameras/live.html",
        {"camera": camera},
    )


@router.get("/{camera_id}/live/stream")
def live_preview_stream(camera_id: int, db: Session = Depends(get_db)):
    camera = camera_service.get_camera(db, camera_id)
    if camera is None:
        return RedirectResponse(url="/cameras", status_code=status.HTTP_303_SEE_OTHER)

    return StreamingResponse(
        mjpeg_stream(camera.rtsp_url),
        media_type="multipart/x-mixed-replace; boundary=frame",
    )


@router.post("/{camera_id}/recording/enable")
def recording_enable(camera_id: int, db: Session = Depends(get_db)):
    camera = camera_service.get_camera(db, camera_id)
    if camera is None:
        return RedirectResponse(url="/cameras", status_code=status.HTTP_303_SEE_OTHER)

    enable_recording(db, camera)
    return RedirectResponse(
        url=f"/cameras/{camera_id}?flash=Recording+started",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.post("/{camera_id}/recording/disable")
def recording_disable(camera_id: int, db: Session = Depends(get_db)):
    camera = camera_service.get_camera(db, camera_id)
    if camera is None:
        return RedirectResponse(url="/cameras", status_code=status.HTTP_303_SEE_OTHER)

    disable_recording(db, camera)
    return RedirectResponse(
        url=f"/cameras/{camera_id}?flash=Recording+stopped",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.post("/{camera_id}/delete")
def delete_camera(camera_id: int, db: Session = Depends(get_db)):
    camera = camera_service.get_camera(db, camera_id)
    if camera is None:
        return RedirectResponse(url="/cameras", status_code=status.HTTP_303_SEE_OTHER)

    camera_service.delete_camera(db, camera)
    return RedirectResponse(
        url="/cameras?flash=Camera+removed",
        status_code=status.HTTP_303_SEE_OTHER,
    )