"""Paralelismo, resiliência, custo e parâmetros de mídia."""

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class RenderSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", frozen=True)

    max_parallel_jobs: int = Field(default=2, ge=1, le=32)
    max_parallel_tts: int = Field(default=6, ge=1, le=64)
    max_parallel_video: int = Field(default=4, ge=1, le=64)
    max_parallel_ffmpeg: int = Field(default=2, ge=1, le=32)
    http_max_attempts: int = Field(default=3, ge=1, le=10)
    video_timeout_s: float = Field(default=300, gt=0, le=3600)
    default_max_budget_usd: float = Field(default=2.0, gt=0, le=100)
    loudness_lufs: float = Field(default=-14, ge=-30, le=-5)
    sync_tolerance_s: float = Field(default=0.2, ge=0, le=2)
    sync_stretch_min: float = Field(default=0.85, gt=0, le=1)
    sync_stretch_max: float = Field(default=1.35, ge=1, le=3)

    @model_validator(mode="after")
    def _faixa_de_stretch(self) -> "RenderSettings":
        if self.sync_stretch_min >= self.sync_stretch_max:
            raise ValueError("SYNC_STRETCH_MIN deve ser menor que SYNC_STRETCH_MAX")
        return self
