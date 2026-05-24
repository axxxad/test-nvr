import logging
import subprocess
import uuid
from datetime import datetime
from pathlib import Path

from app.config import settings
from app.services.segment_service import SegmentInfo, list_segments_for_range
from app.timezone_util import ensure_aware

logger = logging.getLogger(__name__)


class ExportError(Exception):
    pass


def _trim_for_range(
    segment: SegmentInfo,
    range_start: datetime,
    range_end: datetime,
) -> tuple[float, float] | None:
    """Seconds into segment file (ss) and duration for the overlap with [range_start, range_end]."""
    seg_start = ensure_aware(segment.start_time)
    seg_end = ensure_aware(segment.end_time)
    range_start = ensure_aware(range_start)
    range_end = ensure_aware(range_end)
    overlap_start = max(seg_start, range_start)
    overlap_end = min(seg_end, range_end)
    if overlap_start >= overlap_end:
        return None
    ss = (overlap_start - seg_start).total_seconds()
    duration = (overlap_end - overlap_start).total_seconds()
    if duration <= 0:
        return None
    return ss, duration


def _extract_part(
    source: Path,
    ss: float,
    duration: float,
    dest: Path,
) -> None:
    cmd = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "warning",
        "-y",
        "-ss",
        f"{ss:.3f}",
        "-i",
        str(source),
        "-t",
        f"{duration:.3f}",
        "-c",
        "copy",
        "-avoid_negative_ts",
        "make_zero",
        str(dest),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        dest.unlink(missing_ok=True)
        logger.error("Export trim failed: %s", result.stderr)
        raise ExportError("FFmpeg failed to trim a segment. Check server logs.")


def export_clip(
    camera_id: int,
    start: datetime,
    end: datetime,
) -> Path:
    start = ensure_aware(start)
    end = ensure_aware(end)
    segments = list_segments_for_range(camera_id, start, end)
    if not segments:
        raise ExportError("No recordings found for the selected time range.")

    settings.exports_dir.mkdir(parents=True, exist_ok=True)
    job_id = uuid.uuid4().hex[:12]
    output_path = settings.exports_dir / f"export_cam{camera_id}_{job_id}.mp4"
    part_paths: list[Path] = []

    try:
        for index, segment in enumerate(segments):
            trim = _trim_for_range(segment, start, end)
            if trim is None:
                continue
            ss, duration = trim
            full_path = settings.recordings_dir / segment.file_path
            if not full_path.is_file():
                continue
            part_path = settings.exports_dir / f"{job_id}_part{index:04d}.mp4"
            _extract_part(full_path, ss, duration, part_path)
            if part_path.is_file() and part_path.stat().st_size > 0:
                part_paths.append(part_path)

        if not part_paths:
            raise ExportError("Recording files are missing on disk.")

        if len(part_paths) == 1:
            part_paths[0].rename(output_path)
            part_paths.clear()
            return output_path

        concat_path = settings.exports_dir / f"{job_id}.txt"
        lines = []
        for part in part_paths:
            escaped = str(part.resolve()).replace("'", "'\\''")
            lines.append(f"file '{escaped}'")
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
        if result.returncode != 0:
            output_path.unlink(missing_ok=True)
            logger.error("Export concat failed: %s", result.stderr)
            raise ExportError("FFmpeg failed to create export. Check server logs.")
    finally:
        for part in part_paths:
            part.unlink(missing_ok=True)
        concat_file = settings.exports_dir / f"{job_id}.txt"
        concat_file.unlink(missing_ok=True)

    if not output_path.is_file() or output_path.stat().st_size == 0:
        output_path.unlink(missing_ok=True)
        raise ExportError("Export produced an empty file.")

    return output_path
