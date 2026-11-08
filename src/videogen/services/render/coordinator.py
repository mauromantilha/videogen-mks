"""Coordenador da Etapa 2 (design/05 §5.2): fan-out por cena + política de falha.

`gather(return_exceptions=True)`: a falha de uma cena NÃO cancela as predições já pagas das
outras — elas terminam e ficam em cache; o retry refaz só o que falhou (AC-03).
"""

import asyncio

from videogen.domain.job import JobState
from videogen.domain.progress import ErrorInfo
from videogen.domain.status import JobStatus
from videogen.services.render.finalizer import Finalizer
from videogen.services.render.job_tracker import JobTracker
from videogen.services.render.scene_pipeline import ScenePipeline


class RenderCoordinator:
    def __init__(self, pipeline: ScenePipeline, finalizer: Finalizer, jobs: JobTracker) -> None:
        self._pipeline = pipeline
        self._finalizer = finalizer
        self._jobs = jobs

    async def run(self, job_id: str) -> JobState:
        state = await self._jobs.begin_render(job_id)
        if state.status is JobStatus.FINALIZING:  # restart durante a concatenação
            return await self._finalizer.run(job_id)
        scenes = state.require_script().cenas
        results = await asyncio.gather(
            *(self._pipeline.run(state, scene) for scene in scenes), return_exceptions=True
        )
        if any(isinstance(result, asyncio.CancelledError) for result in results):
            raise asyncio.CancelledError
        errors = [ErrorInfo.from_exception(r) for r in results if isinstance(r, BaseException)]
        if errors:
            return await self._jobs.fail(job_id, "rendering", errors)
        return await self._finalizer.run(job_id)
