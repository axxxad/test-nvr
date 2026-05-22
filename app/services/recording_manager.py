import logging
import subprocess
from datetime import datetime, timedelta
from pathlib import Path

from app.timezone_util import now

logger = logging.getLogger(__name__)


def segment_day_dir(output_dir: Path, dt: datetime) -> Path:
    return (
        output_dir
        / dt.strftime("%Y")
        / dt.strftime("%m")
        / dt.strftime("%d")
    )


def ensure_segment_day_dirs(output_dir: Path) -> None:
    """Create today and tomorrow segment folders in app timezone.

    FFmpeg -strftime_mkdir often fails at midnight on Windows/SMB mounts;
    pre-creating paths avoids the segment muxer exiting when the date rolls.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    local_now = now()
    segment_day_dir(output_dir, local_now).mkdir(parents=True, exist_ok=True)
    segment_day_dir(output_dir, local_now + timedelta(days=1)).mkdir(
        parents=True, exist_ok=True
    )


def _segment_output_pattern(output_dir: Path) -> str:
    ensure_segment_day_dirs(output_dir)
    return str(output_dir / "%Y" / "%m" / "%d" / "%H-%M-%S.mp4")


def _read_stderr_tail(proc: subprocess.Popen, max_chars: int = 2000) -> str:
    if proc.stderr is None:
        return ""
    try:
        raw = proc.stderr.read() or b""
    except Exception:
        return ""
    return raw.decode(errors="replace")[-max_chars:].strip()


class RecordingManager:
    """Manages one ffmpeg segment-recording process per camera."""

    def __init__(self) -> None:
        self._processes: dict[int, subprocess.Popen] = {}

    def _log_exit(self, camera_id: int, proc: subprocess.Popen) -> None:
        code = proc.returncode
        tail = _read_stderr_tail(proc)
        if tail:
            logger.warning(
                "ffmpeg for camera %s exited with code %s: %s",
                camera_id,
                code,
                tail,
            )
        else:
            logger.warning("ffmpeg for camera %s exited with code %s", camera_id, code)

    def is_active(self, camera_id: int) -> bool:
        proc = self._processes.get(camera_id)
        if proc is None:
            return False
        if proc.poll() is not None:
            self._log_exit(camera_id, proc)
            self._processes.pop(camera_id, None)
            return False
        return True

    def active_camera_ids(self) -> set[int]:
        self._prune_dead()
        return set(self._processes.keys())

    def _prune_dead(self) -> None:
        for camera_id, proc in list(self._processes.items()):
            if proc.poll() is not None:
                self._log_exit(camera_id, proc)
                self._processes.pop(camera_id, None)

    def _output_codec_args(self, record_audio: bool) -> list[str]:
        if record_audio:
            return [
                "-map",
                "0:v:0",
                "-map",
                "0:a:0?",
                "-c:v",
                "copy",
                "-c:a",
                "aac",
                "-b:a",
                "128k",
            ]
        return ["-map", "0:v:0", "-an", "-c", "copy"]

    def start(
        self,
        camera_id: int,
        rtsp_url: str,
        output_dir: Path,
        *,
        record_audio: bool = False,
    ) -> None:
        if self.is_active(camera_id):
            return

        output_pattern = _segment_output_pattern(output_dir)

        cmd = [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "warning",
            "-rtsp_transport",
            "tcp",
            "-i",
            rtsp_url,
            *self._output_codec_args(record_audio),
            "-f",
            "segment",
            "-segment_time",
            "30",
            "-reset_timestamps",
            "1",
            "-strftime",
            "1",
            "-strftime_mkdir",
            "1",
            output_pattern,
        ]

        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
        self._processes[camera_id] = proc
        logger.info(
            "Started recording for camera %s (audio=%s) → %s",
            camera_id,
            record_audio,
            output_pattern,
        )

    def stop(self, camera_id: int) -> None:
        proc = self._processes.pop(camera_id, None)
        if proc is None:
            return
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
        if proc.poll() is not None:
            self._log_exit(camera_id, proc)
        logger.info("Stopped recording for camera %s", camera_id)

    def stop_all(self) -> None:
        for camera_id in list(self._processes.keys()):
            self.stop(camera_id)


recording_manager = RecordingManager()
