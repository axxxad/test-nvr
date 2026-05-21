from pydantic import BaseModel, Field, field_validator


class CameraForm(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    rtsp_host: str = Field(min_length=1, max_length=255)
    rtsp_port: int = Field(default=554, ge=1, le=65535)
    rtsp_username: str = Field(max_length=255)
    rtsp_password: str = Field(max_length=512)
    rtsp_path: str = Field(default="/Streaming/Channels/101", max_length=512)
    retention_days: int = Field(default=2, ge=1, le=365)
    record_audio: bool = False

    @field_validator("name", "rtsp_host", "rtsp_username", "rtsp_path")
    @classmethod
    def strip_str(cls, value: str) -> str:
        return value.strip()

    @field_validator("rtsp_path")
    @classmethod
    def normalize_path(cls, value: str) -> str:
        value = value.strip() or "/Streaming/Channels/101"
        return value if value.startswith("/") else f"/{value}"
