import logging
import subprocess
import uuid
from datetime import datetime
from pathlib import Path

from sqlalchemy.orm import Session

from app.config import settings
from app.services.segment_service import list_segments_for_range

logger = logging.getLogger(__name__)


class ExportError(Exception):
    pass


def export_clip(
    db: Session,
    camera_id: int,
    start: datetime,
    end: datetime,
) -> Path:
    segments = list_segments_for_range(db, camera_id, start, end)
    if not segments:
        raise ExportError("No recordings found for the selected time range.")

    settings.exports_dir.mkdir(parents=True, exist_ok=True)
    job_id = uuid.uuid4().hex[:12]
    concat_path = settings.exports_dir / f"{job_id}.txt"
    output_path = settings.exports_dir / f"export_cam{camera_id}_{job_id}.mp4"

    lines: list[str] = []
    for segment in segments:
        full_path = settings.recordings_dir / segment.file_path
        if not full_path.is_file():
            continue
        escaped = str(full_path.resolve()).replace("'", "'\\''")
        lines.append(f"file '{escaped}'")

    if not lines:
        raise ExportError("Recording files are missing on disk.")

    concat_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    cmd = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "warning",
        "-y",
        "-f",
        "concat",
        "-safe",
        "0",
        "-i",
        str(concat_path),
        "-c",
        "copy",
        str(output_path),
    ]

    result = subprocess.run(cmd, capture_output=True, text=True)
    concat_path.unlink(missing_ok=True)

    if result.returncode != 0:
        output_path.unlink(missing_ok=True)
        logger.error("Export ffmpeg failed: %s", result.stderr)
        raise ExportError("FFmpeg failed to create export. Check server logs.")

    if not output_path.is_file() or output_path.stat().st_size == 0:
        output_path.unlink(missing_ok=True)
        raise ExportError("Export produced an empty file.")

    return output_path
