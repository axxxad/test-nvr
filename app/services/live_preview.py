import logging
import subprocess
from collections.abc import Generator

from app.rtsp import rtsp_substream_url_for_ffmpeg, rtsp_url_for_ffmpeg

logger = logging.getLogger(__name__)

_BOUNDARY = b"--frame"
_JPEG_START = b"\xff\xd8"
_JPEG_END = b"\xff\xd9"


def _iter_jpeg_frames(stream) -> Generator[bytes, None, None]:
    buffer = b""
    while True:
        chunk = stream.read(16384)
        if not chunk:
            break
        buffer += chunk
        while True:
            start = buffer.find(_JPEG_START)
            if start == -1:
                buffer = b""
                break
            end = buffer.find(_JPEG_END, start + 2)
            if end == -1:
                buffer = buffer[start:]
                break
            yield buffer[start : end + 2]
            buffer = buffer[end + 2 :]


def mjpeg_stream(
    stored_rtsp_url: str,
    *,
    substream: bool = False,
    max_height: int = 720,
    fps: int = 8,
) -> Generator[bytes, None, None]:
    """Yield multipart MJPEG chunks for browser <img src=...>."""
    if substream:
        rtsp_url = rtsp_substream_url_for_ffmpeg(stored_rtsp_url)
    else:
        rtsp_url = rtsp_url_for_ffmpeg(stored_rtsp_url)
    cmd = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-rtsp_transport",
        "tcp",
        "-i",
        rtsp_url,
        "-an",
        "-vf",
        f"fps={fps},scale=-2:{max_height}",
        "-c:v",
        "mjpeg",
        "-q:v",
        "6",
        "-f",
        "mpjpeg",
        "pipe:1",
    ]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if proc.stdout is None:
        proc.kill()
        raise RuntimeError("Failed to start preview FFmpeg")

    try:
        for frame in _iter_jpeg_frames(proc.stdout):
            yield _BOUNDARY + b"\r\nContent-Type: image/jpeg\r\n\r\n" + frame + b"\r\n"
    finally:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                proc.kill()
        stderr = proc.stderr.read().decode() if proc.stderr else ""
        if stderr:
            logger.warning("Preview ffmpeg ended: %s", stderr[:500])
