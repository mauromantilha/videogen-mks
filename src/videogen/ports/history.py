"""Port do histórico de versões do roteiro (`script/vNNNN.json`), para auditoria e desfazer."""

from typing import Protocol, runtime_checkable

from videogen.domain.script import VideoScriptSchema


@runtime_checkable
class ScriptHistory(Protocol):
    async def save(self, job_id: str, version: int, script: VideoScriptSchema) -> None: ...

    async def get(self, job_id: str, version: int) -> VideoScriptSchema: ...

    async def versions(self, job_id: str) -> list[int]: ...
