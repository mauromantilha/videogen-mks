"""Catálogo de modelos (conteúdo de `config/models.yaml`). Fica no domínio porque o
estimador de custo (services) precisa de preços e limites sem conhecer os adapters.
"""

from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from videogen.core.errors import NotFound, ValidationFailed
from videogen.domain.generation import JsonScalar
from videogen.domain.script import AspectRatio

ModelKind = Literal["llm", "tts", "t2v"]
PriceUnit = Literal["per_call", "per_run", "per_second", "per_mtok"]
FAKE_PROVIDER = "fake"
# Campos lógicos que um adapter real precisa saber mapear para o nome do provedor.
REQUIRED_FIELDS: dict[str, frozenset[str]] = {
    "tts": frozenset({"text", "ref_audio"}),
    "t2v": frozenset({"prompt"}),
}
_FROZEN = ConfigDict(extra="forbid", frozen=True)
_TOKENS_PER_MILLION = 1_000_000


class Price(BaseModel):
    model_config = _FROZEN

    unit: PriceUnit
    usd: float = Field(default=0.0, ge=0)  # por chamada/execução/segundo (ou típico por chamada)
    input_usd: float = Field(default=0.0, ge=0)  # per_mtok
    output_usd: float = Field(default=0.0, ge=0)  # per_mtok
    estimated_seconds: float = Field(default=0.0, ge=0)  # per_second: duração típica

    def estimate(self) -> float:
        """Custo esperado de uma execução, antes de rodar (RF-08)."""
        return self.usd * self.estimated_seconds if self.unit == "per_second" else self.usd

    def actual(
        self, *, seconds: float | None = None, prompt_tokens: int = 0, completion_tokens: int = 0
    ) -> float:
        """Custo real a partir das métricas do provedor (cai na estimativa se faltarem)."""
        if self.unit == "per_second" and seconds is not None:
            return self.usd * seconds
        if self.unit == "per_mtok" and (prompt_tokens or completion_tokens):
            tokens_cost = prompt_tokens * self.input_usd + completion_tokens * self.output_usd
            return tokens_cost / _TOKENS_PER_MILLION
        return self.estimate()


class Timeouts(BaseModel):
    model_config = _FROZEN

    submit_s: float = Field(default=30, gt=0)
    total_s: float = Field(default=120, gt=0, le=3600)


class VideoLimits(BaseModel):
    model_config = _FROZEN

    fps: int = Field(gt=0)
    num_frames: int = Field(gt=0)
    sizes: dict[AspectRatio, tuple[int, int]]

    def size_for(self, aspect_ratio: AspectRatio) -> tuple[int, int]:
        if aspect_ratio not in self.sizes:
            raise ValidationFailed(f"modelo não suporta a proporção {aspect_ratio}")
        return self.sizes[aspect_ratio]

    @property
    def duration_s(self) -> float:
        return self.num_frames / self.fps


class ModelSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, protected_namespaces=())

    key: str = Field(min_length=1)
    kind: ModelKind
    provider: str = Field(min_length=1)
    remote_ref: str = Field(min_length=1)
    version: str | None = None  # fixar para reprodutibilidade (entra no hash)
    verified: bool = False  # campos conferidos com o schema oficial do provedor
    capabilities: dict[str, JsonScalar] = Field(default_factory=dict)
    defaults: dict[str, JsonScalar] = Field(default_factory=dict)
    fields: dict[str, str] = Field(default_factory=dict)  # campo lógico -> nome no provedor
    price: Price
    concurrency: int = Field(default=4, ge=1, le=64)
    timeouts: Timeouts = Field(default_factory=Timeouts)
    allowed_hosts: tuple[str, ...] = ()
    limits: VideoLimits | None = None

    @model_validator(mode="after")
    def _coerencia(self) -> Self:
        if self.kind == "t2v" and self.limits is None:
            raise ValueError(f"{self.key}: modelo t2v exige `limits`")
        if self.provider == FAKE_PROVIDER or self.kind == "llm":
            return self
        missing = REQUIRED_FIELDS[self.kind] - self.fields.keys()
        if missing:
            raise ValueError(f"{self.key}: faltam em `fields`: {sorted(missing)}")
        if not self.allowed_hosts:
            raise ValueError(f"{self.key}: `allowed_hosts` é obrigatório (download seguro)")
        return self

    @property
    def model_version(self) -> str:
        return self.version or "unpinned"


class ModelCatalog(BaseModel):
    model_config = _FROZEN

    models: dict[str, ModelSpec]

    def get(self, key: str, kind: ModelKind) -> ModelSpec:
        spec = self.models.get(key)
        if spec is None:
            raise NotFound(f"modelo desconhecido: {key}", model=key)
        if spec.kind != kind:
            raise ValidationFailed(f"{key} é um modelo {spec.kind}, não {kind}", model=key)
        return spec

    def of_kind(self, kind: ModelKind) -> list[ModelSpec]:
        return [spec for spec in self.models.values() if spec.kind == kind]
