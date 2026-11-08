"""Dependências das rotas. A API enxerga só `ApiServices`; o container (app/) o preenche.

Assim nenhuma rota importa adapters — o import-linter garante.
"""

from dataclasses import dataclass
from typing import Annotated, Protocol, cast

from fastapi import Depends, Path, Request

from videogen.core.ids import JOB_ID_RE, VOICE_ID_RE
from videogen.domain.catalog import ModelCatalog, ModelKind, ModelSpec
from videogen.ports.cache import ArtifactCache
from videogen.ports.events import EventBus
from videogen.ports.health import HealthCheck
from videogen.ports.repository import JobRepository
from videogen.ports.voices import VoiceStore
from videogen.services.jobs.approval import ApprovalService
from videogen.services.jobs.creation import JobCreationService
from videogen.services.jobs.lifecycle import JobControlService
from videogen.services.script.edit_service import ScriptEditService
from videogen.services.voices import VoiceService


class ModelDirectory(Protocol):
    def available(self, kind: ModelKind) -> list[ModelSpec]: ...


@dataclass(frozen=True)
class ApiServices:
    """Tudo que as rotas usam, tipado por ports e serviços (nunca por adapters)."""

    repo: JobRepository
    bus: EventBus
    cache: ArtifactCache
    voice_store: VoiceStore
    catalog: ModelCatalog
    models: ModelDirectory
    creation: JobCreationService
    control: JobControlService
    edits: ScriptEditService
    approval: ApprovalService
    voices: VoiceService
    health: HealthCheck
    api_key: str | None


def get_services(request: Request) -> ApiServices:
    return cast(ApiServices, request.app.state.services)


Services = Annotated[ApiServices, Depends(get_services)]
JobId = Annotated[str, Path(pattern=JOB_ID_RE.pattern, description="job_<12 hex>")]
VoiceId = Annotated[str, Path(pattern=VOICE_ID_RE.pattern)]
SceneIndex = Annotated[int, Path(ge=0, lt=100)]
