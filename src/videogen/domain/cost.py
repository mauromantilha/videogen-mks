"""Custo real acumulado (ledger) e estimativa antes da aprovação (RF-08, RNF-10)."""

from collections.abc import Sequence
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field

CostKind = Literal["llm", "tts", "video"]


class CostLedger(BaseModel):
    model_config = ConfigDict(extra="forbid")

    llm_usd: float = Field(default=0.0, ge=0)
    tts_usd: float = Field(default=0.0, ge=0)
    video_usd: float = Field(default=0.0, ge=0)

    @property
    def total(self) -> float:
        return self.llm_usd + self.tts_usd + self.video_usd

    def add(self, kind: CostKind, usd: float) -> None:
        if usd < 0:
            raise ValueError("custo não pode ser negativo")
        match kind:
            case "llm":
                self.llm_usd += usd
            case "tts":
                self.tts_usd += usd
            case "video":
                self.video_usd += usd


class SceneEstimate(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    scene_index: int = Field(ge=0)
    tts_usd: float = Field(ge=0)
    video_usd: float = Field(ge=0)
    cached: bool  # True ⇒ áudio e vídeo já existem no cache (custo 0)

    @property
    def total(self) -> float:
        return self.tts_usd + self.video_usd


class CostEstimate(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    scenes: list[SceneEstimate]
    total_usd: float = Field(ge=0)  # o que ainda será gasto se aprovar agora
    spent_usd: float = Field(ge=0)  # já gasto (LLM e eventuais renders anteriores)

    @classmethod
    def from_scenes(cls, scenes: Sequence[SceneEstimate], spent_usd: float) -> Self:
        total = round(sum(scene.total for scene in scenes), 6)
        return cls(scenes=list(scenes), total_usd=total, spent_usd=spent_usd)
