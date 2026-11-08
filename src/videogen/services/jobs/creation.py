"""Criação e clonagem de jobs (RF-01, RF-11). Valida o pedido contra o catálogo e as vozes
antes de gravar qualquer coisa; o rascunho do roteiro vai para o JobRunner.
"""

from dataclasses import dataclass

from videogen.core.clock import Clock
from videogen.core.ids import new_job_id
from videogen.domain.catalog import ModelCatalog
from videogen.domain.events import ScriptUpdated
from videogen.domain.job import JobState
from videogen.domain.request import JobRequest
from videogen.domain.status import JobStatus
from videogen.ports.events import EventBus
from videogen.ports.history import ScriptHistory
from videogen.ports.repository import JobRepository
from videogen.ports.voices import VoiceStore
from videogen.services.jobs.notify import publish_status
from videogen.services.jobs.runner import JobRunner
from videogen.services.script.script_service import ScriptService


@dataclass(frozen=True)
class CreationDeps:
    repo: JobRepository
    bus: EventBus
    runner: JobRunner
    script: ScriptService
    history: ScriptHistory


class JobCreationService:
    def __init__(
        self, deps: CreationDeps, catalog: ModelCatalog, voices: VoiceStore, clock: Clock
    ) -> None:
        self._deps = deps
        self._catalog = catalog
        self._voices = voices
        self._clock = clock

    async def create(self, request: JobRequest) -> JobState:
        await self._validate(request)
        state = await self._deps.repo.create(JobState.new(new_job_id(), request, self._clock.now()))
        publish_status(self._deps.bus, state)
        self._submit_draft(state.job_id)
        return state

    async def clone(self, job_id: str) -> JobState:
        source = await self._deps.repo.get(job_id)
        clone = JobState.new(new_job_id(), source.request, self._clock.now())
        if source.script is None:
            state = await self._deps.repo.create(clone)
            self._submit_draft(state.job_id)
        else:
            clone.script, clone.script_version = source.script, 1
            clone.transition_to(JobStatus.AWAITING_APPROVAL)
            state = await self._deps.repo.create(clone)
            await self._deps.history.save(state.job_id, 1, source.script)
            self._deps.bus.publish(state.job_id, ScriptUpdated(script_version=1))
        publish_status(self._deps.bus, state)
        return state

    async def _validate(self, request: JobRequest) -> None:
        self._catalog.get(request.models.llm, "llm")
        self._catalog.get(request.models.tts, "tts")
        limits = self._catalog.get(request.models.video, "t2v").limits
        if limits is not None:
            limits.size_for(request.aspect_ratio)  # o modelo suporta a proporção?
        await self._voices.get(request.voice_id)

    def _submit_draft(self, job_id: str) -> None:
        script = self._deps.script
        self._deps.runner.submit(job_id, "script", lambda: script.draft(job_id))
