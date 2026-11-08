"""Port de persistência do estado do job (manifesto)."""

from collections.abc import Callable
from typing import Protocol, runtime_checkable

from videogen.domain.job import JobState

JobMutator = Callable[[JobState], None]


@runtime_checkable
class JobRepository(Protocol):
    async def create(self, state: JobState) -> JobState:
        """Persiste um job novo; `AlreadyExists` se o id já existir."""
        ...

    async def get(self, job_id: str) -> JobState:
        """`NotFound` se não existir."""
        ...

    async def list_all(self) -> list[JobState]: ...

    async def update(
        self, job_id: str, mutator: JobMutator, *, expected_revision: int | None = None
    ) -> JobState:
        """Lê → aplica `mutator` (síncrono, curto) → valida → `revision += 1` → grava, atômico.

        `VersionConflict` se `expected_revision` não bater; estado inválido nunca é gravado.
        """
        ...
