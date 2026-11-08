"""ScriptHistory em memória."""

from typing import TYPE_CHECKING

from videogen.core.errors import NotFound
from videogen.domain.script import VideoScriptSchema


class InMemoryScriptHistory:
    def __init__(self) -> None:
        self.snapshots: dict[tuple[str, int], VideoScriptSchema] = {}

    async def save(self, job_id: str, version: int, script: VideoScriptSchema) -> None:
        self.snapshots[(job_id, version)] = script

    async def get(self, job_id: str, version: int) -> VideoScriptSchema:
        if (job_id, version) not in self.snapshots:
            raise NotFound("versão inexistente")
        return self.snapshots[(job_id, version)]

    async def versions(self, job_id: str) -> list[int]:
        return sorted(version for (job, version) in self.snapshots if job == job_id)


if TYPE_CHECKING:
    from videogen.ports.history import ScriptHistory

    _conforms: ScriptHistory = InMemoryScriptHistory()
