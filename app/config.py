from pathlib import Path

from pydantic import computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    database_url: str = f"sqlite:///{BASE_DIR / 'data' / 'nvr.db'}"
    recordings_dir: Path = BASE_DIR / "recordings"
    exports_dir: Path = BASE_DIR / "exports"
    segment_duration_seconds: int = 30
    recording_maintenance_interval_seconds: int = 60
    retention_interval_seconds: int = 300
    default_retention_days: int = 2
    disk_pressure_enabled: bool = True
    disk_min_free_gb: float = 5.0
    disk_target_free_gb: float = 10.0
    disk_pressure_batch_size: int = 100
    secret_key: str = "dev-secret-change-me"
    # Must match container TZ so FFmpeg segment filenames match the UI.
    app_timezone: str = "UTC"

    @computed_field
    @property
    def disk_min_free_bytes(self) -> int:
        return int(self.disk_min_free_gb * 1024**3)

    @computed_field
    @property
    def disk_target_free_bytes(self) -> int:
        return int(self.disk_target_free_gb * 1024**3)


settings = Settings()
