import logging
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)


class RecordingManager:
    """Manages one ffmpeg segment-recording process per camera."""

    def __init__(self) -> None:
        self._processes: dict[int, subprocess.Popen] = {}

    def is_active(self, camera_id: int) -> bool:
        proc = self._processes.get(camera_id)
        if proc is None:
            return False
        if proc.poll() is not None:
            self._processes.pop(camera_id, None)
            return False
        return True

    def active_camera_ids(self) -> set[int]:
        self._prune_dead()
        return set(self._processes.keys())

    def _prune_dead(self) -> None:
        for camera_id, proc in list(self._processes.items()):
            if proc.poll() is not None:
                code = proc.returncode
                logger.warning("ffmpeg for camera %s exited with code %s", camera_id, code)
                self._processes.pop(camera_id, None)

    def start(self, camera_id: int, rtsp_url: str, output_dir: Path) -> None:
        if self.is_active(camera_id):
            return

        output_dir.mkdir(parents=True, exist_ok=True)
        output_pattern = str(output_dir / "%Y" / "%m" / "%d" / "%H-%M-%S.mp4")

        cmd = [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "warning",
            "-rtsp_transport",
            "tcp",
            "-i",
            rtsp_url,
            "-c",
            "copy",
            "-f",
            "segment",
            "-segment_time",
            "30",
            "-reset_timestamps",
            "1",
            "-strftime",
            "1",
            output_pattern,
        ]

        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
        self._processes[camera_id] = proc
        logger.info("Started recording for camera %s → %s", camera_id, output_pattern)

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
        logger.info("Stopped recording for camera %s", camera_id)

    def stop_all(self) -> None:
        for camera_id in list(self._processes.keys()):
            self.stop(camera_id)


recording_manager = RecordingManager()
