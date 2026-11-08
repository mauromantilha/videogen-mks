"""Wiring dos casos de uso. `render` (Etapa 2) entra no M7; até lá, aprovados aguardam."""

from dataclasses import dataclass

from videogen.app.container_infra import Infra
from videogen.app.container_providers import Providers
from videogen.core.clock import Clock
from videogen.core.config import Settings
from videogen.services.cost.estimator import CostEstimator
from videogen.services.jobs.approval import ApprovalService, RenderEntry
from videogen.services.jobs.creation import CreationDeps, JobCreationService
from videogen.services.jobs.lifecycle import JobControlService
from videogen.services.jobs.recovery import RecoveryService
from videogen.services.jobs.runner import JobRunner, Stage
from videogen.services.script.edit_service import ScriptEditService
from videogen.services.script.script_service import ScriptService
from videogen.services.voices import VoiceService


@dataclass(frozen=True)
class Services:
    runner: JobRunner
    script: ScriptService
    edits: ScriptEditService
    creation: JobCreationService
    control: JobControlService
    approval: ApprovalService
    recovery: RecoveryService
    voices: VoiceService


def build_services(
    settings: Settings, infra: Infra, providers: Providers, clock: Clock,
    render: RenderEntry | None = None,
) -> Services:  # fmt: skip
    controls: list[JobControlService] = []

    async def on_crash(job_id: str, stage: Stage, exc: BaseException) -> None:
        await controls[0].mark_crashed(job_id, stage, exc)

    runner = JobRunner(max_parallel=settings.render.max_parallel_jobs, on_crash=on_crash)
    script = ScriptService(infra.repo, infra.bus, providers.registry, infra.history)
    control = JobControlService(infra.repo, infra.bus, runner, script, render=render)
    controls.append(control)
    estimator = CostEstimator(providers.catalog, infra.cache, infra.voice_store)
    creation_deps = CreationDeps(infra.repo, infra.bus, runner, script, infra.history)
    scratch = infra.workspace.root / "_scratch"
    return Services(
        runner=runner,
        script=script,
        edits=ScriptEditService(infra.repo, infra.bus, infra.history),
        creation=JobCreationService(creation_deps, providers.catalog, infra.voice_store, clock),
        control=control,
        approval=ApprovalService(infra.repo, infra.bus, estimator, runner, clock, render=render),
        recovery=RecoveryService(infra.repo, infra.bus, runner, script, render=render),
        voices=VoiceService(infra.voice_store, infra.probe, infra.composer, scratch),
    )
