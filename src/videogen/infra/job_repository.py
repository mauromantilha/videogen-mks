"""JobRepository sobre `jobs/{job_id}/job_state.json` (ADR-03, RNF-09, RNF-11).

Um lock asyncio por job serializa os updates dentro do processo (o deploy é 1 worker).
I/O de disco roda em thread para não travar o event loop.
"""

import asyncio
import logging
from pathlib import Path

from videogen.core.clock import Clock
from videogen.core.errors import AlreadyExists, NotFound, VersionConflict
from videogen.domain.job import JobState
from videogen.infra.atomic_file import write_atomic
from videogen.infra.workspace import Workspace
from videogen.ports.repository import JobMutator

logger = logging.getLogger(__name__)
STATE_FILE = "job_state.json"


class JsonJobRepository:
    def __init__(self, workspace: Workspace, clock: Clock) -> None:
        self._workspace = workspace
        self._clock = clock
        self._locks: dict[str, asyncio.Lock] = {}

    def _lock(self, job_id: str) -> asyncio.Lock:
        return self._locks.setdefault(job_id, asyncio.Lock())

    async def create(self, state: JobState) -> JobState:
        path = self._workspace.job_state_path(state.job_id)
        async with self._lock(state.job_id):
            if path.exists():
                raise AlreadyExists("job já existe", job_id=state.job_id)
            await self._write(path, state)
        return state.model_copy(deep=True)

    async def get(self, job_id: str) -> JobState:
        path = self._workspace.job_state_path(job_id)
        if not path.is_file():
            raise NotFound("job não encontrado", job_id=job_id)
        return await asyncio.to_thread(_read, path)

    async def list_all(self) -> list[JobState]:
        states = await asyncio.to_thread(_read_all, self._workspace.jobs_dir)
        return sorted(states, key=lambda state: state.created_at, reverse=True)

    async def update(
        self, job_id: str, mutator: JobMutator, *, expected_revision: int | None = None
    ) -> JobState:
        async with self._lock(job_id):
            state = await self.get(job_id)
            if expected_revision is not None and expected_revision != state.revision:
                raise VersionConflict(
                    "o job mudou desde a leitura", current_revision=state.revision
                )
            mutator(state)
            state.revision += 1
            state.updated_at = self._clock.now()
            validated = JobState.model_validate(state.model_dump())  # invariantes antes de gravar
            await self._write(self._workspace.job_state_path(job_id), validated)
            return validated

    @staticmethod
    async def _write(path: Path, state: JobState) -> None:
        payload = state.model_dump_json(indent=2).encode("utf-8")
        await asyncio.to_thread(write_atomic, path, payload)


def _read(path: Path) -> JobState:
    return JobState.model_validate_json(path.read_bytes())


def _read_all(jobs_dir: Path) -> list[JobState]:
    states: list[JobState] = []
    for path in sorted(jobs_dir.glob(f"job_*/{STATE_FILE}")):
        try:
            states.append(_read(path))
        except ValueError:
            logger.warning("manifesto ilegível ignorado", extra={"path": str(path)})
    return states
