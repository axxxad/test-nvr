import shutil

from app.config import settings


def recordings_disk_usage() -> tuple[int, int, int]:
    """Return (total, used, free) bytes for the filesystem backing recordings_dir."""
    return shutil.disk_usage(settings.recordings_dir)


def recordings_volume_free_bytes() -> int:
    return recordings_disk_usage()[2]


def is_disk_pressure_active() -> bool:
    if not settings.disk_pressure_enabled:
        return False
    return recordings_volume_free_bytes() < settings.disk_min_free_bytes


def format_gib(num_bytes: int) -> str:
    gib = num_bytes / (1024**3)
    return f"{gib:.1f} GiB"
