"""JobRepository em memória com a mesma semântica do adapter JSON (revisão otimista)."""

from typing import TYPE_CHECKING

from videogen.core.clock import Clock
from videogen.core.errors import AlreadyExists, NotFound, VersionConflict
from videogen.domain.job import JobState
from videogen.ports.repository import JobMutator


class InMemoryJobRepository:
    def __init__(self, clock: Clock) -> None:
        self._clock = clock
        self._data: dict[str, str] = {}  # JSON: cópias independentes, como no disco
        self.update_count = 0

    async def create(self, state: JobState) -> JobState:
        if state.job_id in self._data:
            raise AlreadyExists("job já existe", job_id=state.job_id)
        self._data[state.job_id] = state.model_dump_json()
        return await self.get(state.job_id)

    async def get(self, job_id: str) -> JobState:
        if job_id not in self._data:
            raise NotFound("job não encontrado", job_id=job_id)
        return JobState.model_validate_json(self._data[job_id])

    async def list_all(self) -> list[JobState]:
        return [JobState.model_validate_json(raw) for raw in self._data.values()]

    async def update(
        self, job_id: str, mutator: JobMutator, *, expected_revision: int | None = None
    ) -> JobState:
        state = await self.get(job_id)
        if expected_revision is not None and expected_revision != state.revision:
            raise VersionConflict("revisão desatualizada", current_revision=state.revision)
        mutator(state)
        state.revision += 1
        state.updated_at = self._clock.now()
        validated = JobState.model_validate(state.model_dump())  # invariantes antes de gravar
        self._data[job_id] = validated.model_dump_json()
        self.update_count += 1
        return validated


if TYPE_CHECKING:
    from tests.fakes.fake_clock import FakeClock
    from videogen.ports.repository import JobRepository

    _conforms: JobRepository = InMemoryJobRepository(FakeClock())
