"""Plano de sincronização áudio vs. vídeo (RF-04). Função pura; o FFmpeg só executa o plano."""

from dataclasses import dataclass
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from videogen.core.errors import MediaError

_EPSILON = 1e-9  # ruído de ponto flutuante nos limites das faixas (ex.: 5.06 * 0.85 / 5.06)


class SyncStrategy(StrEnum):
    NONE = "none"  # diferença ≤ tolerância: completa/apara sem efeito perceptível
    STRETCH = "stretch"  # setpts=S*PTS
    FREEZE_ZOOM = "freeze_zoom"  # estica ao máximo e congela o último frame com zoom suave
    TRIM = "trim"  # acelera ao máximo, corta na duração do áudio e faz fade-out


class SyncConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    tolerance_s: float = Field(default=0.2, ge=0)
    stretch_min: float = Field(default=0.85, gt=0, le=1)
    stretch_max: float = Field(default=1.35, ge=1)
    fade_out_s: float = Field(default=0.3, ge=0)


@dataclass(frozen=True)
class SyncPlan:
    strategy: SyncStrategy
    setpts_factor: float  # > 1 desacelera (slow-motion), < 1 acelera
    freeze_extra_s: float  # tempo de congelamento ao final do vídeo
    target_duration_s: float  # sempre a duração do áudio


def plan_sync(t_audio: float, t_video: float, cfg: SyncConfig) -> SyncPlan:
    if t_audio <= 0 or t_video <= 0:
        raise MediaError(f"durações inválidas: áudio={t_audio}s, vídeo={t_video}s")
    if abs(t_audio - t_video) <= cfg.tolerance_s:
        return SyncPlan(SyncStrategy.NONE, 1.0, max(0.0, t_audio - t_video), t_audio)
    factor = t_audio / t_video
    if cfg.stretch_min - _EPSILON <= factor <= cfg.stretch_max + _EPSILON:
        clamped = min(max(factor, cfg.stretch_min), cfg.stretch_max)
        return SyncPlan(SyncStrategy.STRETCH, clamped, 0.0, t_audio)
    if factor > cfg.stretch_max:
        stretched = t_video * cfg.stretch_max
        return SyncPlan(SyncStrategy.FREEZE_ZOOM, cfg.stretch_max, t_audio - stretched, t_audio)
    return SyncPlan(SyncStrategy.TRIM, cfg.stretch_min, 0.0, t_audio)
