"""Tipos de artefato, informações de mídia e voz de referência."""

from datetime import datetime
from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from videogen.core.ids import VOICE_ID_RE

SHA256_HEX = r"^[0-9a-f]{64}$"


class ArtifactKind(StrEnum):
    AUDIO_RAW = "audio_raw"  # saída paga do TTS
    AUDIO_NORM = "audio_norm"  # derivado local: -14 LUFS
    VIDEO_RAW = "video_raw"  # saída paga do T2V
    CLIP = "clip"  # cena composta (sync + legenda + encode)
    FINAL = "final"  # concatenação de todos os clipes


class MediaInfo(BaseModel):
    """Resultado do ffprobe: a duração real é a fonte de verdade (nunca "81 frames")."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    duration_s: float = Field(ge=0)
    has_video: bool
    has_audio: bool
    fps: float | None = None
    width: int | None = None
    height: int | None = None
    video_codec: str | None = None
    audio_codec: str | None = None
    sample_rate: int | None = None


class VoiceRef(BaseModel):
    """Voz cadastrada para clonagem (RF-12). O hash do conteúdo entra no hash do áudio."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    voice_id: str = Field(pattern=VOICE_ID_RE.pattern)
    name: str = Field(min_length=1, max_length=80)
    ref_text: str = Field(min_length=1, max_length=1000)
    sha256: str = Field(pattern=SHA256_HEX)
    duration_s: float = Field(gt=0)
    path: Path
    created_at: datetime
    owner_id: str | None = None
