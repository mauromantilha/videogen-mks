"""Contrato do roteiro da Etapa 1 — validado antes de qualquer gasto de GPU (RF-01)."""

from collections.abc import Sequence
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

AspectRatio = Literal["9:16", "16:9"]
MAX_SEED = 2**31 - 1
MIN_SCENES = 2
MAX_SCENES = 10


class SceneSpec(BaseModel):
    """Uma cena: narração em PT-BR + prompt visual em inglês."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    scene_index: int = Field(ge=0)
    texto_narrado: str = Field(min_length=1, max_length=120)  # teto; a regra real é por palavras
    prompt_video: str = Field(min_length=20, max_length=1200)
    seed: int | None = Field(default=None, ge=0, le=MAX_SEED)  # fixada na aprovação


class VideoScriptSchema(BaseModel):
    """Roteiro completo. `extra="forbid"` rejeita campos inventados pelo LLM."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    produto_tema: str = Field(min_length=3, max_length=200)
    aspect_ratio: AspectRatio = "9:16"
    estilo_visual: str = Field(default="", max_length=400)  # âncora de coerência entre cenas
    cenas: list[SceneSpec] = Field(min_length=MIN_SCENES, max_length=MAX_SCENES)

    @model_validator(mode="after")
    def _indices_contiguos(self) -> Self:
        if [scene.scene_index for scene in self.cenas] != list(range(len(self.cenas))):
            raise ValueError("scene_index deve ser 0..N-1, sem lacunas e em ordem")
        return self

    def with_scenes(self, cenas: Sequence[SceneSpec]) -> Self:
        """Novo roteiro com as cenas na ordem dada, renumeradas e revalidadas."""
        renumbered = [scene.model_dump() | {"scene_index": i} for i, scene in enumerate(cenas)]
        return self.model_validate(self.model_dump() | {"cenas": renumbered})
