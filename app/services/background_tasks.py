import asyncio
import logging

from app.config import settings
from app.database import SessionLocal
from app.services.recording_service import maintain_enabled_recordings
from app.services.retention_service import apply_retention_policy

logger = logging.getLogger(__name__)


def run_recording_maintenance_cycle() -> None:
    db = SessionLocal()
    try:
        maintain_enabled_recordings(db)
    except Exception:
        logger.exception("Recording maintenance cycle failed")
    finally:
        db.close()


def run_retention_cycle() -> None:
    db = SessionLocal()
    try:
        apply_retention_policy(db)
        maintain_enabled_recordings(db)
    except Exception:
        logger.exception("Retention cycle failed")
    finally:
        db.close()


async def recording_maintenance_loop(stop_event: asyncio.Event) -> None:
    while not stop_event.is_set():
        await asyncio.to_thread(run_recording_maintenance_cycle)
        try:
            await asyncio.wait_for(
                stop_event.wait(),
                timeout=settings.recording_maintenance_interval_seconds,
            )
        except asyncio.TimeoutError:
            pass


async def retention_loop(stop_event: asyncio.Event) -> None:
    while not stop_event.is_set():
        await asyncio.to_thread(run_retention_cycle)
        try:
            await asyncio.wait_for(
                stop_event.wait(),
                timeout=settings.retention_interval_seconds,
            )
        except asyncio.TimeoutError:
            pass
