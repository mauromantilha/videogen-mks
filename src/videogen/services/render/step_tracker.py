"""Estado de cada etapa (áudio, vídeo, clipe) de cada cena: uma gravação + um evento por mudança.

`started` aplica o orçamento (RNF-10): depois de estourar, nenhuma tentativa paga nova começa.
`remote_id_saved` grava o id da predição antes do primeiro poll (retomada sem cobrança dupla).
"""

from dataclasses import dataclass

from videogen.core.errors import BudgetExceeded
from videogen.domain.cost import CostKind
from videogen.domain.events import JobCostChanged, SceneStepChanged
from videogen.domain.job import JobState
from videogen.domain.progress import ErrorInfo, StepName, StepState
from videogen.ports.events import EventBus
from videogen.ports.repository import JobRepository
from videogen.services.cost.budget import allows_new_attempt


@dataclass(frozen=True)
class StepRef:
    job_id: str
    scene_index: int
    step: StepName


class StepTracker:
    def __init__(self, repo: JobRepository, bus: EventBus) -> None:
        self._repo = repo
        self._bus = bus

    async def remote_id(self, ref: StepRef) -> str | None:
        return _step(await self._repo.get(ref.job_id), ref).remote_id

    async def remote_id_saved(self, ref: StepRef, remote_id: str | None) -> None:
        def mutate(state: JobState) -> None:
            _step(state, ref).remote_id = remote_id

        await self._repo.update(ref.job_id, mutate)

    async def started(self, ref: StepRef, *, paid: bool) -> None:
        def mutate(state: JobState) -> None:
            budget = state.approval.max_budget_usd if state.approval else None
            if paid and budget is not None and not allows_new_attempt(state.ledger.total, budget):
                raise BudgetExceeded("orçamento do job esgotado", budget_usd=budget)
            _step(state, ref).start()

        state = await self._repo.update(ref.job_id, mutate)
        self._publish(state, ref)

    async def cached(self, ref: StepRef, artifact_hash: str) -> None:
        state = await self._repo.update(
            ref.job_id, lambda s: _step(s, ref).mark_cached(artifact_hash)
        )
        self._publish(state, ref)

    async def done(
        self, ref: StepRef, artifact_hash: str, *, cost_usd: float, kind: CostKind | None
    ) -> None:
        def mutate(state: JobState) -> None:
            _step(state, ref).finish(artifact_hash, cost_usd)
            if kind is not None:
                state.ledger.add(kind, cost_usd)

        state = await self._repo.update(ref.job_id, mutate)
        self._publish(state, ref)
        if kind is not None:
            budget = state.approval.max_budget_usd if state.approval else None
            self._bus.publish(ref.job_id, JobCostChanged(spent_usd=state.ledger.total,
                                                         budget_usd=budget))  # fmt: skip

    async def failed(self, ref: StepRef, error: ErrorInfo) -> None:
        state = await self._repo.update(ref.job_id, lambda s: _step(s, ref).fail(error))
        self._publish(state, ref)

    def _publish(self, state: JobState, ref: StepRef) -> None:
        step = _step(state, ref)
        event = SceneStepChanged(scene_index=ref.scene_index, step=ref.step, status=step.status,
                                 cached=step.cached, cost_usd=step.cost_usd)  # fmt: skip
        self._bus.publish(ref.job_id, event)


def _step(state: JobState, ref: StepRef) -> StepState:
    return state.scenes[ref.scene_index].step(ref.step)
