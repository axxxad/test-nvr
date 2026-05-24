import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)

from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from app.config import settings
from app.timezone_util import tz_label
from app.database import Base, SessionLocal, engine
from app.db_migrate import migrate_schema
from app.models import Camera  # noqa: F401 — register models
from app.routers import cameras, recordings
from app.services.background_tasks import (
    recording_maintenance_loop,
    retention_loop,
    run_recording_maintenance_cycle,
    run_retention_cycle,
)
from app.services.recording_manager import recording_manager
from app.services.recording_service import restore_enabled_recordings

STATIC_DIR = Path(__file__).resolve().parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    db_path = settings.database_url.replace("sqlite:///", "")
    if db_path and not db_path.startswith(":"):
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    settings.recordings_dir.mkdir(parents=True, exist_ok=True)
    settings.exports_dir.mkdir(parents=True, exist_ok=True)
    Base.metadata.create_all(bind=engine)
    migrate_schema()
    logging.getLogger(__name__).info("App timezone: %s", tz_label())

    db = SessionLocal()
    try:
        restore_enabled_recordings(db)
        run_recording_maintenance_cycle()
        run_retention_cycle()
    finally:
        db.close()

    stop_event = asyncio.Event()
    maintenance_task = asyncio.create_task(recording_maintenance_loop(stop_event))
    retention_task = asyncio.create_task(retention_loop(stop_event))

    yield

    stop_event.set()
    await asyncio.gather(maintenance_task, retention_task, return_exceptions=True)
    recording_manager.stop_all()


app = FastAPI(title="CCTV NVR", lifespan=lifespan)

if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

app.include_router(cameras.router)
app.include_router(recordings.router)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/")
def root():
    return RedirectResponse(url="/cameras", status_code=303)
