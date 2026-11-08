"""Pedido do usuário que origina um job (entrada da Etapa 1)."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from videogen.core.ids import VOICE_ID_RE
from videogen.domain.script import MAX_SCENES, MIN_SCENES, AspectRatio
from videogen.domain.script_rules import ScriptLimits

MAX_BUDGET_CEILING_USD = 100.0


class ModelChoice(BaseModel):
    """Chaves do `config/models.yaml` escolhidas para este job."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    llm: str = Field(min_length=1)
    tts: str = Field(min_length=1)
    video: str = Field(min_length=1)


class RenderOptions(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    resolution: Literal["480p", "720p"] = "480p"
    fps: Literal[24, 30] = 30
    duracao_cena_s: float = Field(default=4.0, ge=2, le=8)
    legendas: bool = True


class JobRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    tema: str = Field(min_length=3, max_length=500)
    aspect_ratio: AspectRatio = "9:16"
    n_cenas: int = Field(default=5, ge=MIN_SCENES, le=MAX_SCENES)
    models: ModelChoice
    voice_id: str = Field(pattern=VOICE_ID_RE.pattern)
    options: RenderOptions = Field(default_factory=RenderOptions)
    max_budget_usd: float = Field(default=2.0, gt=0, le=MAX_BUDGET_CEILING_USD)

    def script_limits(self, *, enforce_scene_count: bool = False) -> ScriptLimits:
        """Limites do roteiro; a contagem de cenas só é exigida da saída do LLM."""
        expected = self.n_cenas if enforce_scene_count else None
        return ScriptLimits(scene_seconds=self.options.duracao_cena_s, expected_scenes=expected)
