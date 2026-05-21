from pydantic import BaseModel, Field, field_validator


class CameraCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    rtsp_url: str = Field(min_length=1, max_length=1024)
    retention_days: int = Field(default=2, ge=1, le=365)

    @field_validator("name", "rtsp_url")
    @classmethod
    def strip_whitespace(cls, value: str) -> str:
        return value.strip()

    @field_validator("rtsp_url")
    @classmethod
    def validate_rtsp_url(cls, value: str) -> str:
        if not value.lower().startswith("rtsp://"):
            raise ValueError("RTSP URL must start with rtsp://")
        return value
