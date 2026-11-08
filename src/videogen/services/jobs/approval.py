"""Portão de aprovação (RF-09): nenhuma chamada paga acontece antes daqui.

Recusa versão desatualizada (409) e orçamento insuficiente (422) sem mudar nada. A leitura e a
gravação são ligadas por `expected_revision`: uma edição que chegue no meio invalida a aprovação.
"""

from collections.abc import Awaitable, Callable

from videogen.core.clock import Clock
from videogen.core.errors import VersionConflict
from videogen.domain.cost import CostEstimate
from videogen.domain.events import JobStatusChanged
from videogen.domain.freeze import freeze_for_render
from videogen.domain.job import JobState
from videogen.domain.script_rules import ensure_valid
from videogen.domain.status import JobStatus
from videogen.ports.events import EventBus
from videogen.ports.repository import JobRepository
from videogen.services.cost.budget import ensure_within
from videogen.services.cost.estimator import CostEstimator
from videogen.services.jobs.runner import JobRunner

RenderEntry = Callable[[str], Awaitable[object]]


class ApprovalService:
    def __init__(
        self, repo: JobRepository, bus: EventBus, estimator: CostEstimator, runner: JobRunner,
        clock: Clock, *, render: RenderEntry | None = None,
    ) -> None:  # fmt: skip
        self._repo, self._bus, self._estimator = repo, bus, estimator
        self._runner, self._clock, self._render = runner, clock, render

    async def estimate(self, job_id: str) -> CostEstimate:
        return await self._estimator.estimate(await self._repo.get(job_id))

    async def approve(
        self, job_id: str, *, script_version: int, max_budget_usd: float | None = None
    ) -> JobState:
        job = await self._repo.get(job_id)
        job.ensure_status(JobStatus.AWAITING_APPROVAL)
        if job.script_version != script_version:
            raise VersionConflict(
                "o roteiro mudou desde que foi exibido",
                current_version=job.script_version,
                requested_version=script_version,
            )
        ensure_valid(job.require_script(), job.request.script_limits())
        budget = max_budget_usd if max_budget_usd is not None else job.request.max_budget_usd
        ensure_within((await self._estimator.estimate(job)).total_usd, budget)

        def freeze(state: JobState) -> None:
            freeze_for_render(
                state, script_version=script_version, max_budget_usd=budget, now=self._clock.now()
            )

        state = await self._repo.update(job_id, freeze, expected_revision=job.revision)
        self._bus.publish(job_id, JobStatusChanged(status=state.status))
        if self._render is not None:
            render = self._render
            self._runner.submit(job_id, "render", lambda: render(job_id))
        return state
