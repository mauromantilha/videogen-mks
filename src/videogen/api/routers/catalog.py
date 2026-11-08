"""Modelos utilizáveis agora (RF-14): no modo real, só os verificados e com credencial."""

from typing import get_args

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from videogen.api.auth import require_auth
from videogen.api.deps import Services
from videogen.api.dto.jobs import API
from videogen.domain.catalog import ModelKind, ModelSpec

router = APIRouter(prefix=API, tags=["catálogo"], dependencies=[Depends(require_auth)])


class ModelView(BaseModel):
    key: str
    kind: ModelKind
    provider: str
    estimated_usd: float
    aspect_ratios: list[str]
    video_seconds: float | None

    @classmethod
    def of(cls, spec: ModelSpec) -> "ModelView":
        limits = spec.limits
        return cls(key=spec.key, kind=spec.kind, provider=spec.provider,
                   estimated_usd=spec.price.estimate(),
                   aspect_ratios=sorted(limits.sizes) if limits else [],
                   video_seconds=round(limits.duration_s, 2) if limits else None)  # fmt: skip


@router.get("/catalog/models")
async def list_models(services: Services, kind: ModelKind | None = None) -> list[ModelView]:
    kinds: tuple[ModelKind, ...] = (kind,) if kind else get_args(ModelKind)
    return [ModelView.of(spec) for k in kinds for spec in services.models.available(k)]
