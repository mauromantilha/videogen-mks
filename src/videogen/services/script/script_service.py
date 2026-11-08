"""Gera e regenera o roteiro via LLM (RF-01, RF-07). Roda sempre em segundo plano (JobRunner).

Rascunho que falha leva o job a `failed(scripting)`. Regeneração que falha NÃO derruba o job:
o roteiro anterior continua válido, então ele volta a `awaiting_approval` com `error` preenchido.
"""

from videogen.core.errors import DomainError, InvalidTransition
from videogen.domain.events import JobFailed, JobStatusChanged, ScriptUpdated
from videogen.domain.job import JobState
from videogen.domain.progress import ErrorInfo
from videogen.domain.script import VideoScriptSchema
from videogen.domain.script_rules import ScriptLimits, ScriptValidationError, validate_rules
from videogen.domain.status import JobStatus
from videogen.ports.events import EventBus
from videogen.ports.history import ScriptHistory
from videogen.ports.llm import ChatMessage
from videogen.ports.repository import JobRepository
from videogen.ports.resolver import ProviderResolver
from videogen.services.script.prompts import draft_messages, regenerate_messages
from videogen.services.script.repair import RepairOutcome, ScriptRepairLoop


class ScriptService:
    def __init__(
        self,
        repo: JobRepository,
        bus: EventBus,
        providers: ProviderResolver,
        history: ScriptHistory,
        loop: ScriptRepairLoop | None = None,
    ) -> None:
        self._repo = repo
        self._bus = bus
        self._providers = providers
        self._history = history
        self._loop = loop or ScriptRepairLoop()

    async def draft(self, job_id: str) -> JobState:
        job = await self._repo.get(job_id)
        job.ensure_status(JobStatus.SCRIPTING)
        limits = job.request.script_limits(enforce_scene_count=True)
        try:
            outcome = await self._run(job, draft_messages(job.request, limits), limits)
        except DomainError as exc:
            return await self._fail(job_id, ErrorInfo.from_exception(exc), cost_usd=0.0)
        if outcome.script is None:
            error = ErrorInfo.from_exception(ScriptValidationError(outcome.violations))
            return await self._fail(job_id, error, outcome.cost_usd)
        return await self._accept(job_id, outcome.script, outcome.cost_usd)

    async def regenerate(
        self, job_id: str, *, feedback: str | None = None, scene_index: int | None = None
    ) -> JobState:
        job = await self._repo.get(job_id)
        job.ensure_status(JobStatus.SCRIPTING)
        current = job.require_script()
        if scene_index is not None and not 0 <= scene_index < len(current.cenas):
            raise InvalidTransition(f"cena {scene_index} não existe")
        limits = job.request.script_limits(enforce_scene_count=scene_index is None)
        messages = regenerate_messages(
            job.request, current, limits, feedback=feedback, scene_index=scene_index
        )
        try:
            outcome = await self._run(job, messages, limits)
            script = _graft(current, outcome, scene_index)
        except DomainError as exc:
            return await self._keep_previous(job_id, ErrorInfo.from_exception(exc), 0.0)
        if script is None or validate_rules(script, job.request.script_limits()):
            error = ErrorInfo.from_exception(ScriptValidationError(outcome.violations))
            return await self._keep_previous(job_id, error, outcome.cost_usd)
        return await self._accept(job_id, script, outcome.cost_usd)

    async def _run(
        self, job: JobState, messages: list[ChatMessage], limits: ScriptLimits
    ) -> RepairOutcome:
        llm = self._providers.llm(job.request.models.llm)
        return await self._loop.run(llm, messages, limits, job.request.aspect_ratio)

    async def _accept(self, job_id: str, script: VideoScriptSchema, cost_usd: float) -> JobState:
        def mutate(state: JobState) -> None:
            state.ledger.add("llm", cost_usd)
            state.script, state.script_version, state.error = script, state.script_version + 1, None
            state.transition_to(JobStatus.AWAITING_APPROVAL)

        state = await self._repo.update(job_id, mutate)
        await self._history.save(job_id, state.script_version, script)
        self._bus.publish(job_id, ScriptUpdated(script_version=state.script_version))
        self._bus.publish(job_id, JobStatusChanged(status=state.status))
        return state

    async def _fail(self, job_id: str, error: ErrorInfo, cost_usd: float) -> JobState:
        def mutate(state: JobState) -> None:
            state.ledger.add("llm", cost_usd)
            state.fail("scripting", error)

        state = await self._repo.update(job_id, mutate)
        self._bus.publish(job_id, JobFailed(error=error))
        self._bus.publish(job_id, JobStatusChanged(status=state.status, failed_stage="scripting"))
        return state

    async def _keep_previous(self, job_id: str, error: ErrorInfo, cost_usd: float) -> JobState:
        def mutate(state: JobState) -> None:
            state.ledger.add("llm", cost_usd)
            state.error = error
            state.transition_to(JobStatus.AWAITING_APPROVAL)

        state = await self._repo.update(job_id, mutate)
        self._bus.publish(job_id, JobStatusChanged(status=state.status))
        return state


def _graft(
    current: VideoScriptSchema, outcome: RepairOutcome, scene_index: int | None
) -> VideoScriptSchema | None:
    """Regeneração de uma cena: só ela muda; as outras ficam exatamente como estavam."""
    if outcome.script is None or scene_index is None:
        return outcome.script
    if scene_index >= len(outcome.script.cenas):
        return None
    scenes = list(current.cenas)
    scenes[scene_index] = outcome.script.cenas[scene_index].model_copy(update={"seed": None})
    return current.with_scenes(scenes)
