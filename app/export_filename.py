import re
from datetime import datetime


def build_export_download_name(
    export_name: str,
    camera_name: str,
    start: datetime,
    end: datetime,
) -> str:
    """Safe filename for browser download (Windows-friendly)."""
    base = (export_name or camera_name).strip()
    safe = re.sub(r"[^\w.\-]+", "_", base, flags=re.UNICODE)
    safe = safe.strip("._") or "export"
    return f"{safe}_{start.strftime('%Y%m%d_%H%M%S')}-{end.strftime('%H%M%S')}.mp4"
