import asyncio
import logging

from app.config import settings
from app.database import SessionLocal
from app.services.recording_service import maintain_enabled_recordings
from app.services.retention_service import run_retention_cleanup
from app.services.segment_indexer import index_recordings, prune_missing_files

logger = logging.getLogger(__name__)


def run_index_cycle() -> None:
    db = SessionLocal()
    try:
        maintain_enabled_recordings(db)
        index_recordings(db)
        prune_missing_files(db)
    except Exception:
        logger.exception("Index cycle failed")
    finally:
        db.close()


def run_retention_cycle() -> None:
    db = SessionLocal()
    try:
        run_retention_cleanup(db)
        index_recordings(db)
    except Exception:
        logger.exception("Retention cycle failed")
    finally:
        db.close()


async def index_loop(stop_event: asyncio.Event) -> None:
    while not stop_event.is_set():
        await asyncio.to_thread(run_index_cycle)
        try:
            await asyncio.wait_for(
                stop_event.wait(),
                timeout=settings.index_interval_seconds,
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
