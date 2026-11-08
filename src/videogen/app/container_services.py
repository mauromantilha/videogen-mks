"""Wiring dos casos de uso, incluindo a Etapa 2 (render) como entrada da aprovação/retry."""

from dataclasses import dataclass

from videogen.app.container_infra import Infra
from videogen.app.container_providers import Providers
from videogen.core.clock import Clock
from videogen.core.config import Settings
from videogen.domain.render_specs import LoudnessParams
from videogen.domain.sync import SyncConfig
from videogen.ports.downloader import Downloader
from videogen.services.cost.estimator import CostEstimator
from videogen.services.jobs.approval import ApprovalService
from videogen.services.jobs.creation import CreationDeps, JobCreationService
from videogen.services.jobs.lifecycle import JobControlService
from videogen.services.jobs.recovery import RecoveryService
from videogen.services.jobs.runner import JobRunner, Stage
from videogen.services.render.coordinator import RenderCoordinator
from videogen.services.render.factory import RenderPorts, RenderTuning, build_render
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
    render: RenderCoordinator


def build_services(
    settings: Settings, infra: Infra, providers: Providers, clock: Clock
) -> Services:
    controls: list[JobControlService] = []

    async def on_crash(job_id: str, stage: Stage, exc: BaseException) -> None:
        await controls[0].mark_crashed(job_id, stage, exc)

    runner = JobRunner(max_parallel=settings.render.max_parallel_jobs, on_crash=on_crash)
    coordinator = _render(settings, infra, providers)
    render = coordinator.run
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
        render=coordinator,
    )


def _render(settings: Settings, infra: Infra, providers: Providers) -> RenderCoordinator:
    fake = settings.providers.provider_mode == "fake"
    downloader: Downloader = providers.context.fake_origin if fake else infra.downloader
    ports = RenderPorts(
        repo=infra.repo,
        bus=infra.bus,
        catalog=providers.catalog,
        providers=providers.registry,
        voices=infra.voice_store,
        cache=infra.cache,
        downloader=downloader,
        probe=infra.probe,
        composer=infra.composer,
    )
    r = settings.render
    tuning = RenderTuning(
        loudness=LoudnessParams(integrated_lufs=r.loudness_lufs),
        sync=SyncConfig(
            tolerance_s=r.sync_tolerance_s,
            stretch_min=r.sync_stretch_min,
            stretch_max=r.sync_stretch_max,
        ),
        max_parallel_tts=r.max_parallel_tts,
        max_parallel_video=r.max_parallel_video,
    )
    return build_render(ports, tuning)
