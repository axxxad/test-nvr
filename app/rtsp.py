"""Build and parse RTSP URLs with correct credential encoding for FFmpeg."""

from urllib.parse import quote, unquote


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
    path = path.strip() or "/Streaming/Channels/101"
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
        path = "/Streaming/Channels/101"

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
