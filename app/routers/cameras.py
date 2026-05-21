from pathlib import Path

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pydantic import ValidationError
from sqlalchemy.orm import Session
from starlette import status

from app.database import get_db
from app.schemas.camera import CameraCreate
from app.services import camera_service
from app.services.recording_service import (
    disable_recording,
    enable_recording,
    is_recording,
)

router = APIRouter(prefix="/cameras", tags=["cameras"])
templates = Jinja2Templates(directory=str(Path(__file__).resolve().parent.parent / "templates"))


def _parse_form(
    name: str, rtsp_url: str, retention_days: int = 2
) -> tuple[CameraCreate | None, dict[str, str]]:
    try:
        return CameraCreate(name=name, rtsp_url=rtsp_url, retention_days=retention_days), {}
    except ValidationError as exc:
        errors: dict[str, str] = {}
        for err in exc.errors():
            field = str(err["loc"][0]) if err["loc"] else "_form"
            errors[field] = err["msg"]
        return None, errors


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
        {"errors": {}, "name": "", "rtsp_url": "", "retention_days": 2},
    )


@router.post("/new")
def create_camera(
    request: Request,
    name: str = Form(""),
    rtsp_url: str = Form(""),
    retention_days: int = Form(2),
    db: Session = Depends(get_db),
):
    data, errors = _parse_form(name, rtsp_url, retention_days)
    if data is None:
        return templates.TemplateResponse(
            request,
            "cameras/form.html",
            {
                "errors": errors,
                "name": name,
                "rtsp_url": rtsp_url,
                "retention_days": retention_days,
            },
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        )

    camera_service.create_camera(db, data)
    return RedirectResponse(
        url="/cameras?flash=Camera+added+successfully",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.post("/{camera_id}/recording/enable")
def recording_enable(camera_id: int, db: Session = Depends(get_db)):
    camera = camera_service.get_camera(db, camera_id)
    if camera is None:
        return RedirectResponse(url="/cameras", status_code=status.HTTP_303_SEE_OTHER)

    enable_recording(db, camera)
    return RedirectResponse(
        url="/cameras?flash=Recording+started",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.post("/{camera_id}/recording/disable")
def recording_disable(camera_id: int, db: Session = Depends(get_db)):
    camera = camera_service.get_camera(db, camera_id)
    if camera is None:
        return RedirectResponse(url="/cameras", status_code=status.HTTP_303_SEE_OTHER)

    disable_recording(db, camera)
    return RedirectResponse(
        url="/cameras?flash=Recording+stopped",
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
