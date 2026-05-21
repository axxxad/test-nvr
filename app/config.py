from pathlib import Path

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
    index_interval_seconds: int = 60
    retention_interval_seconds: int = 300
    default_retention_days: int = 2
    secret_key: str = "dev-secret-change-me"
    # Must match container TZ so FFmpeg segment filenames match the indexer.
    app_timezone: str = "UTC"


settings = Settings()
