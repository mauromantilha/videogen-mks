"""Parâmetros dos derivados locais (loudnorm, clipe, concat). Os `*Params` entram no hash;
os caminhos ficam nos `*Spec`, fora dele.
"""

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from videogen.domain.script import AspectRatio
from videogen.domain.sync import SyncConfig

_FROZEN = ConfigDict(extra="forbid", frozen=True)


class LoudnessParams(BaseModel):
    model_config = _FROZEN

    integrated_lufs: float = Field(default=-14.0, ge=-30, le=-5)
    true_peak_db: float = Field(default=-1.5, le=0)
    lra: float = Field(default=11.0, gt=0)
    sample_rate: int = Field(default=48_000, gt=0)


class ClipParams(BaseModel):
    model_config = _FROZEN

    texto: str = Field(min_length=1)  # legenda
    aspect_ratio: AspectRatio
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    fps: Literal[24, 30]
    subtitles: bool = True
    subtitle_style: str = "default"
    sync: SyncConfig = Field(default_factory=SyncConfig)


class ClipSpec(BaseModel):
    """Entrada de `MediaComposer.compose_clip`."""

    model_config = _FROZEN

    params: ClipParams
    video_path: Path
    audio_path: Path
    out_path: Path


class ConcatParams(BaseModel):
    model_config = _FROZEN

    audio_codec: str = "aac"
    audio_bitrate_k: int = Field(default=192, gt=0)
    sample_rate: int = Field(default=48_000, gt=0)
    faststart: bool = True
