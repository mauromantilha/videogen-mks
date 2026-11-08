"""Execução em segundo plano dentro do processo (ADR-04): um `asyncio.Task` por job.

O runner não conhece regras de negócio: recebe o trabalho pronto (`work`) e um callback para
falhas inesperadas. Só um trabalho por job de cada vez.
"""

import asyncio
import contextlib
import logging
from collections.abc import Awaitable, Callable
from typing import Literal

from videogen.core.errors import InvalidTransition
from videogen.core.logging import log_context

logger = logging.getLogger(__name__)
Stage = Literal["script", "render"]
Work = Callable[[], Awaitable[object]]
CrashHandler = Callable[[str, Stage, BaseException], Awaitable[None]]


class JobRunner:
    def __init__(self, *, max_parallel: int, on_crash: CrashHandler) -> None:
        self._slots = asyncio.Semaphore(max_parallel)
        self._on_crash = on_crash
        self._tasks: dict[str, asyncio.Task[None]] = {}

    def submit(self, job_id: str, stage: Stage, work: Work) -> asyncio.Task[None]:
        if self.is_running(job_id):
            raise InvalidTransition("o job já tem um trabalho em execução", job_id=job_id)
        task = asyncio.create_task(self._run(job_id, stage, work), name=f"{stage}:{job_id}")
        self._tasks[job_id] = task
        task.add_done_callback(lambda done: self._forget(job_id, done))
        return task

    def is_running(self, job_id: str) -> bool:
        task = self._tasks.get(job_id)
        return task is not None and not task.done()

    async def join(self, job_id: str) -> None:
        """Espera o trabalho atual do job terminar (sem propagar a falha dele)."""
        task = self._tasks.get(job_id)
        if task is not None:
            await asyncio.gather(task, return_exceptions=True)

    async def cancel(self, job_id: str) -> bool:
        task = self._tasks.get(job_id)
        if task is None or task.done():
            return False
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
        return True

    async def shutdown(self, grace_s: float = 10.0) -> None:
        """Espera os trabalhos terminarem por `grace_s`; cancela o que sobrar."""
        pending = [task for task in self._tasks.values() if not task.done()]
        if not pending:
            return
        _, still_running = await asyncio.wait(pending, timeout=grace_s)
        for task in still_running:
            task.cancel()
        await asyncio.gather(*still_running, return_exceptions=True)

    async def _run(self, job_id: str, stage: Stage, work: Work) -> None:
        async with self._slots:
            with log_context(job_id=job_id, step=stage):
                try:
                    await work()
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    logger.exception("falha inesperada no trabalho do job")
                    await self._on_crash(job_id, stage, exc)

    def _forget(self, job_id: str, task: asyncio.Task[None]) -> None:
        if self._tasks.get(job_id) is task:
            del self._tasks[job_id]
