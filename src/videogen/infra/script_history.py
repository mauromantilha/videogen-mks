"""Histórico do roteiro em `jobs/{job_id}/script/vNNNN.json` (escrita atômica)."""

import asyncio

from videogen.core.errors import NotFound
from videogen.domain.script import VideoScriptSchema
from videogen.infra.atomic_file import write_atomic
from videogen.infra.workspace import Workspace


class FileScriptHistory:
    def __init__(self, workspace: Workspace) -> None:
        self._workspace = workspace

    async def save(self, job_id: str, version: int, script: VideoScriptSchema) -> None:
        path = self._workspace.script_snapshot_path(job_id, version)
        await asyncio.to_thread(write_atomic, path, script.model_dump_json(indent=2).encode())

    async def get(self, job_id: str, version: int) -> VideoScriptSchema:
        path = self._workspace.script_snapshot_path(job_id, version)
        if not path.is_file():
            raise NotFound(f"versão {version} do roteiro não existe", job_id=job_id)
        return VideoScriptSchema.model_validate_json(await asyncio.to_thread(path.read_bytes))

    async def versions(self, job_id: str) -> list[int]:
        directory = self._workspace.job_dir(job_id) / "script"
        return sorted(int(p.stem.removeprefix("v")) for p in directory.glob("v*.json"))
