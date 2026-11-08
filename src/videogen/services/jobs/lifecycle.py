"""Controle de jobs existentes (RF-07, RF-11): regenerar, cancelar, retomar, reabrir e o
tratamento de falha inesperada. `render` é a entrada da Etapa 2 (ligada no M7).
"""

import logging
from collections.abc import Awaitable, Callable

from videogen.core.config import ConfigError
from videogen.core.errors import DomainError, InvalidTransition
from videogen.domain.job import JobState
from videogen.domain.progress import ErrorInfo
from videogen.domain.status import FailedStage, JobStatus, can_transition
from videogen.ports.events import EventBus
from videogen.ports.repository import JobRepository
from videogen.services.jobs.notify import publish_status
from videogen.services.jobs.runner import JobRunner, Stage
from videogen.services.script.script_service import ScriptService

logger = logging.getLogger(__name__)
RenderEntry = Callable[[str], Awaitable[object]]
S = JobStatus


class JobControlService:
    def __init__(
        self,
        repo: JobRepository,
        bus: EventBus,
        runner: JobRunner,
        script: ScriptService,
        *,
        render: RenderEntry | None = None,
    ) -> None:
        self._repo, self._bus, self._runner = repo, bus, runner
        self._script, self._render = script, render

    async def request_regeneration(
        self, job_id: str, *, feedback: str | None, scene_index: int | None
    ) -> JobState:
        state = await self._transition(job_id, S.SCRIPTING, require=S.AWAITING_APPROVAL)
        script = self._script
        self._runner.submit(job_id, "script", lambda: script.regenerate(
            job_id, feedback=feedback, scene_index=scene_index))  # fmt: skip
        return state

    async def cancel(self, job_id: str) -> JobState:
        if not can_transition((await self._repo.get(job_id)).status, S.CANCELED):
            raise InvalidTransition("este job não pode mais ser cancelado")
        await self._runner.cancel(job_id)
        return await self._transition(job_id, S.CANCELED)

    async def retry(self, job_id: str) -> JobState:
        job = await self._repo.get(job_id)
        job.ensure_status(S.FAILED)
        if job.failed_stage == "scripting":
            if job.script is not None:  # roteiro anterior ainda válido: volta à revisão
                return await self._transition(job_id, S.AWAITING_APPROVAL)
            state = await self._transition(job_id, S.SCRIPTING)
            script = self._script
            self._runner.submit(job_id, "script", lambda: script.draft(job_id))
            return state
        render = self._require_render()
        state = await self._repo.update(job_id, _resume_render)
        publish_status(self._bus, state)
        self._runner.submit(job_id, "render", lambda: render(job_id))
        return state

    async def reopen(self, job_id: str) -> JobState:
        def mutate(state: JobState) -> None:
            state.ensure_status(S.COMPLETED, S.FAILED)
            state.require_script()
            state.approval, state.scenes, state.final_hash, state.error = None, [], None, None
            state.transition_to(S.AWAITING_APPROVAL)

        state = await self._repo.update(job_id, mutate)
        publish_status(self._bus, state)
        return state

    async def mark_crashed(self, job_id: str, stage: Stage, exc: BaseException) -> None:
        """Callback do JobRunner: um job nunca fica preso "em execução" após um bug."""
        error = ErrorInfo.from_exception(exc)

        def mutate(state: JobState) -> None:
            if state.status is S.APPROVED:
                state.transition_to(S.RENDERING)
            if can_transition(state.status, S.FAILED):
                state.fail(_failed_stage(stage, state.status), error)

        try:
            publish_status(self._bus, await self._repo.update(job_id, mutate))
        except DomainError:
            logger.exception("não foi possível marcar o job como falho", extra={"job_id": job_id})

    async def _transition(
        self, job_id: str, target: JobStatus, *, require: JobStatus | None = None
    ) -> JobState:
        def mutate(state: JobState) -> None:
            if require is not None:
                state.ensure_status(require)
            state.transition_to(target)

        state = await self._repo.update(job_id, mutate)
        publish_status(self._bus, state)
        return state

    def _require_render(self) -> RenderEntry:
        if self._render is None:
            raise ConfigError("a Etapa 2 (render) ainda não está configurada")
        return self._render


def _resume_render(state: JobState) -> None:
    """Retry do render: etapas falhas voltam a pendentes; o que já foi pago fica."""
    for scene in state.scenes:
        for step in (scene.audio, scene.video, scene.clip):
            step.reset_failed()
    state.transition_to(S.RENDERING)


def _failed_stage(stage: Stage, status: JobStatus) -> FailedStage:
    if stage == "script":
        return "scripting"
    return "finalizing" if status is S.FINALIZING else "rendering"
