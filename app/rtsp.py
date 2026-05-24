"""Build and parse RTSP URLs with correct credential encoding for FFmpeg."""

import re
from urllib.parse import quote, unquote

HIKVISION_MAIN_CHANNEL = "101"
HIKVISION_SUB_CHANNEL = "102"
DEFAULT_MAIN_PATH = "/Streaming/Channels/101"
DEFAULT_SUB_PATH = "/Streaming/Channels/102"


def build_rtsp_url(
    host: str,
    port: int,
    username: str,
    password: str,
    path: str,
) -> str:
    host = host.strip()
    username = username.strip()
    password = password  # allow special chars; encode below
    path = path.strip() or DEFAULT_MAIN_PATH
    if not path.startswith("/"):
        path = "/" + path

    user = quote(username, safe="")
    pw = quote(password, safe="")
    return f"rtsp://{user}:{pw}@{host}:{port}{path}"


def parse_rtsp_url(url: str) -> dict[str, str | int]:
    """Best-effort parse; uses rightmost @ before host (password may contain @)."""
    raw = url.strip()
    if not raw.lower().startswith("rtsp://"):
        raise ValueError("URL must start with rtsp://")

    rest = raw[7:]
    if "/" in rest:
        authority, path_part = rest.split("/", 1)
        path = "/" + path_part
    else:
        authority = rest
        path = DEFAULT_MAIN_PATH

    if "@" not in authority:
        raise ValueError("URL must include credentials (user:pass@host)")

    creds, hostport = authority.rsplit("@", 1)
    if ":" in creds:
        username, password = creds.split(":", 1)
        username = unquote(username)
        password = unquote(password)
    else:
        username = unquote(creds)
        password = ""

    if ":" in hostport:
        host, port_str = hostport.rsplit(":", 1)
        port = int(port_str)
    else:
        host = hostport
        port = 554

    return {
        "host": host,
        "port": port,
        "username": username,
        "password": password,
        "path": path,
    }


def with_stream_channel(stored_url: str, channel: str) -> str:
    """Return an RTSP URL with the Hikvision channel id swapped (e.g. 101 → 102)."""
    parts = parse_rtsp_url(stored_url)
    path = str(parts["path"])
    if re.search(r"/Channels/\d+", path, re.IGNORECASE):
        path = re.sub(r"/Channels/\d+", f"/Channels/{channel}", path, flags=re.IGNORECASE)
    elif re.search(r"(?<=/)\d{3}$", path):
        path = re.sub(r"\d{3}$", channel, path)
    else:
        path = f"/Streaming/Channels/{channel}"
    return build_rtsp_url(
        str(parts["host"]),
        int(parts["port"]),
        str(parts["username"]),
        str(parts["password"]),
        path,
    )


def rtsp_substream_url_for_ffmpeg(stored_url: str) -> str:
    """Substream (102) for lightweight previews; recording keeps stored main URL."""
    return rtsp_url_for_ffmpeg(with_stream_channel(stored_url, HIKVISION_SUB_CHANNEL))


def rtsp_url_for_ffmpeg(stored_url: str) -> str:
    """Re-build URL with encoded credentials (use after loading from DB)."""
    parts = parse_rtsp_url(stored_url)
    return build_rtsp_url(
        str(parts["host"]),
        int(parts["port"]),
        str(parts["username"]),
        str(parts["password"]),
        str(parts["path"]),
    )


def mask_rtsp_url(url: str) -> str:
    try:
        parts = parse_rtsp_url(url)
    except ValueError:
        return url
    return build_rtsp_url(
        str(parts["host"]),
        int(parts["port"]),
        str(parts["username"]),
        "********",
        str(parts["path"]),
    )
