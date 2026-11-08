"""Pedidos enviados aos provedores pagos. Eles SÃO a fonte do hash (domain/hashing.py):
todo parâmetro que muda o resultado mora aqui, então não há como esquecê-lo no cache.
"""

import unicodedata
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, field_validator

from videogen.domain.script import MAX_SEED

JsonScalar = str | int | float | bool | None
SubmittedCallback = Callable[[str], Awaitable[None]]
_SHA256_HEX = r"^[0-9a-f]{64}$"
_FROZEN = ConfigDict(extra="forbid", frozen=True, protected_namespaces=())


def normalize_text(value: str) -> str:
    """NFC + espaços colapsados: textos visualmente iguais geram o mesmo hash.

    Roda antes da validação, para `min_length` valer sobre o texto já normalizado.
    """
    return " ".join(unicodedata.normalize("NFC", value).split())


class TTSRequest(BaseModel):
    model_config = _FROZEN

    model_key: str = Field(min_length=1)
    model_version: str = Field(min_length=1)
    text: str = Field(min_length=1)
    language: str = "pt-BR"
    ref_text: str = Field(min_length=1)
    ref_audio_sha256: str = Field(pattern=_SHA256_HEX)  # conteúdo da voz, não o caminho
    speed: float = Field(default=1.0, ge=0.5, le=2.0)
    ref_audio_path: Path = Field(exclude=True)  # necessário ao provedor, fora do hash

    @field_validator("text", "ref_text", mode="before")
    @classmethod
    def _normalize(cls, value: object) -> object:
        return normalize_text(value) if isinstance(value, str) else value


class VideoRequest(BaseModel):
    model_config = _FROZEN

    model_key: str = Field(min_length=1)
    model_version: str = Field(min_length=1)
    prompt: str = Field(min_length=1)  # prompt_video + estilo_visual já combinados
    negative_prompt: str = ""
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    num_frames: int = Field(gt=0)
    fps: int = Field(gt=0)
    seed: int = Field(ge=0, le=MAX_SEED)
    extra: dict[str, JsonScalar] = Field(default_factory=dict)

    @field_validator("prompt", "negative_prompt", mode="before")
    @classmethod
    def _normalize(cls, value: object) -> object:
        return normalize_text(value) if isinstance(value, str) else value


@dataclass(frozen=True)
class RunContext:
    """Entregue pelo CachedStep ao provedor: permite retomar sem reenviar (RNF-09)."""

    timeout_s: float
    on_submitted: SubmittedCallback  # chamado logo após criar a predição remota
    resume_remote_id: str | None = None


class GenerationResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    remote_id: str = Field(min_length=1)
    output_url: str = Field(min_length=1)
    cost_usd: float | None = Field(default=None, ge=0)
    provider_seconds: float | None = Field(default=None, ge=0)
