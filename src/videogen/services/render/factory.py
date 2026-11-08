"""Monta a Etapa 2 a partir dos ports (usado pelo composition root e pelos testes)."""

from dataclasses import dataclass, field

from videogen.domain.catalog import ModelCatalog
from videogen.domain.render_specs import LoudnessParams
from videogen.domain.sync import SyncConfig
from videogen.ports.cache import ArtifactCache
from videogen.ports.composer import MediaComposer
from videogen.ports.downloader import Downloader
from videogen.ports.events import EventBus
from videogen.ports.probe import MediaProbe
from videogen.ports.repository import JobRepository
from videogen.ports.resolver import ProviderResolver
from videogen.ports.voices import VoiceStore
from videogen.services.render.cached_step import CachedStep
from videogen.services.render.context import RenderContext
from videogen.services.render.coordinator import RenderCoordinator
from videogen.services.render.finalizer import Finalizer
from videogen.services.render.job_tracker import JobTracker
from videogen.services.render.limiter import ProviderLimiter
from videogen.services.render.scene_pipeline import ScenePipeline
from videogen.services.render.single_flight import SingleFlight
from videogen.services.render.step_tracker import StepTracker


@dataclass(frozen=True)
class RenderPorts:
    repo: JobRepository
    bus: EventBus
    catalog: ModelCatalog
    providers: ProviderResolver
    voices: VoiceStore
    cache: ArtifactCache
    downloader: Downloader
    probe: MediaProbe
    composer: MediaComposer


@dataclass(frozen=True)
class RenderTuning:
    loudness: LoudnessParams = field(default_factory=LoudnessParams)
    sync: SyncConfig = field(default_factory=SyncConfig)
    max_parallel_tts: int = 6
    max_parallel_video: int = 4


def build_render(ports: RenderPorts, tuning: RenderTuning | None = None) -> RenderCoordinator:
    tuning = tuning or RenderTuning()
    steps, flight = StepTracker(ports.repo, ports.bus), SingleFlight()
    cached = CachedStep(ports.cache, ports.downloader, ports.probe, steps, flight)
    limiter = ProviderLimiter({"tts": tuning.max_parallel_tts, "t2v": tuning.max_parallel_video})
    ctx = RenderContext(catalog=ports.catalog, providers=ports.providers, voices=ports.voices,
                        cache=ports.cache, composer=ports.composer, cached_step=cached,
                        tracker=steps, limiter=limiter, flight=flight,
                        loudness=tuning.loudness, sync=tuning.sync)  # fmt: skip
    jobs = JobTracker(ports.repo, ports.bus)
    return RenderCoordinator(ScenePipeline(ctx), Finalizer(ports.cache, ports.composer, jobs), jobs)
