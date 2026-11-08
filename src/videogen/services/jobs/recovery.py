"""Retoma jobs interrompidos por um restart (RNF-09). Roda uma vez, no startup.

- `scripting` sem roteiro: refaz o rascunho (custo desprezível).
- `scripting` com roteiro (regeneração perdida): volta à revisão com o roteiro anterior.
- `approved`/`rendering`/`finalizing`: reentra no render, que retoma predições pelo `remote_id`.
"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from videogen.domain.events import JobStatusChanged
from videogen.domain.job import JobState
from videogen.domain.status import JobStatus
from videogen.ports.events import EventBus
from videogen.ports.repository import JobRepository
from videogen.services.jobs.runner import JobRunner
from videogen.services.script.script_service import ScriptService

RenderEntry = Callable[[str], Awaitable[object]]
RENDER_STATES = frozenset({JobStatus.APPROVED, JobStatus.RENDERING, JobStatus.FINALIZING})


@dataclass
class RecoveryReport:
    drafted: list[str] = field(default_factory=list)
    restored: list[str] = field(default_factory=list)
    rendering: list[str] = field(default_factory=list)


class RecoveryService:
    def __init__(
        self, repo: JobRepository, bus: EventBus, runner: JobRunner, script: ScriptService,
        *, render: RenderEntry | None = None,
    ) -> None:  # fmt: skip
        self._repo, self._bus, self._runner = repo, bus, runner
        self._script, self._render = script, render

    async def resume_all(self) -> RecoveryReport:
        report = RecoveryReport()
        for job in await self._repo.list_all():
            if self._runner.is_running(job.job_id):
                continue
            await self._resume(job, report)
        return report

    async def _resume(self, job: JobState, report: RecoveryReport) -> None:
        job_id = job.job_id
        if job.status is JobStatus.SCRIPTING and job.script is None:
            self._runner.submit(job_id, "script", lambda: self._script.draft(job_id))
            report.drafted.append(job_id)
        elif job.status is JobStatus.SCRIPTING:
            state = await self._repo.update(
                job_id, lambda s: s.transition_to(JobStatus.AWAITING_APPROVAL)
            )
            self._bus.publish(job_id, JobStatusChanged(status=state.status))
            report.restored.append(job_id)
        elif job.status in RENDER_STATES and self._render is not None:
            render = self._render
            self._runner.submit(job_id, "render", lambda: render(job_id))
            report.rendering.append(job_id)
