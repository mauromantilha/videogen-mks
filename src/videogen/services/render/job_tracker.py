"""Estado do job durante a Etapa 2: rendering → finalizing → completed | failed."""

from collections.abc import Sequence

from videogen.domain.events import JobCompleted, JobFailed
from videogen.domain.job import JobState
from videogen.domain.progress import ErrorInfo
from videogen.domain.status import FailedStage, JobStatus
from videogen.ports.events import EventBus
from videogen.ports.repository import JobMutator, JobRepository
from videogen.services.jobs.notify import publish_status

ENTRY_STATES = (JobStatus.APPROVED, JobStatus.RENDERING, JobStatus.FINALIZING)


class JobTracker:
    def __init__(self, repo: JobRepository, bus: EventBus) -> None:
        self._repo = repo
        self._bus = bus

    async def begin_render(self, job_id: str) -> JobState:
        """Aprovado → rendering. Já em rendering/finalizing (retry, restart): segue de onde está."""

        def mutate(state: JobState) -> None:
            state.ensure_status(*ENTRY_STATES)
            if state.status is JobStatus.APPROVED:
                state.transition_to(JobStatus.RENDERING)

        return await self._changed(job_id, mutate)

    async def begin_finalizing(self, job_id: str) -> JobState:
        def mutate(state: JobState) -> None:
            if state.status is not JobStatus.FINALIZING:
                state.transition_to(JobStatus.FINALIZING)

        return await self._changed(job_id, mutate)

    async def complete(self, job_id: str, final_hash: str) -> JobState:
        def mutate(state: JobState) -> None:
            state.final_hash = final_hash
            state.transition_to(JobStatus.COMPLETED)

        state = await self._changed(job_id, mutate)
        self._bus.publish(job_id, JobCompleted(final_hash=final_hash))
        return state

    async def fail(self, job_id: str, stage: FailedStage, errors: Sequence[ErrorInfo]) -> JobState:
        """Falha do job com o primeiro erro como causa e a contagem das demais."""
        first = errors[0]
        extra = f" (+{len(errors) - 1} cena(s) com falha)" if len(errors) > 1 else ""
        error = first.model_copy(update={"message": f"{first.message}{extra}"})
        state = await self._repo.update(job_id, lambda s: s.fail(stage, error))
        self._bus.publish(job_id, JobFailed(error=error))
        publish_status(self._bus, state)
        return state

    async def _changed(self, job_id: str, mutate: JobMutator) -> JobState:
        state = await self._repo.update(job_id, mutate)
        publish_status(self._bus, state)
        return state
