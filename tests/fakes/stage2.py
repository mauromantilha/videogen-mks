"""Monta a Etapa 2 real (render + FFmpeg) com provedores fake e disco temporário."""

from dataclasses import dataclass
from pathlib import Path

from tests.fakes.builders import JOB_ID, make_job
from tests.fakes.fake_clock import FakeClock
from tests.fakes.media_factory import FAST, PROBE, RUNNER
from tests.fakes.memory_history import InMemoryScriptHistory
from tests.fakes.memory_repository import InMemoryJobRepository
from tests.fakes.memory_voices import InMemoryVoiceStore
from tests.fakes.recording_bus import RecordingEventBus
from tests.fakes.stage1 import CATALOG, StubResolver
from videogen.composer.concat import Concatenator
from videogen.composer.loudnorm import LoudnessNormalizer
from videogen.composer.media_composer import FfmpegMediaComposer
from videogen.composer.scene_composer import SceneComposer
from videogen.domain.catalog import ModelCatalog
from videogen.domain.job import JobState
from videogen.domain.status import JobStatus
from videogen.infra.artifact_cache import FileArtifactCache
from videogen.ports.tts import TTSProvider
from videogen.ports.video import VideoProvider
from videogen.providers.fake.behavior import FakeBehavior
from videogen.providers.fake.llm import FakeLLM
from videogen.providers.fake.origin import FakeMediaOrigin
from videogen.providers.fake.tts import FakeTTS
from videogen.providers.fake.video import FakeVideo
from videogen.services.jobs.lifecycle import JobControlService
from videogen.services.jobs.runner import JobRunner
from videogen.services.render.coordinator import RenderCoordinator
from videogen.services.render.factory import RenderPorts, RenderTuning, build_render
from videogen.services.script.script_service import ScriptService


def small_catalog() -> ModelCatalog:
    """Vídeo fake pequeno (3 s ≈ a fala fake) para os testes rodarem rápido, sem zoompan."""
    models = dict(CATALOG.models)
    wan = models["wan-2.1-t2v-480p"]
    limits = wan.limits.model_copy(update={"num_frames": 48, "sizes": {  # type: ignore[union-attr]
        "9:16": (160, 288), "16:9": (288, 160)}})  # fmt: skip
    models["wan-2.1-t2v-480p"] = wan.model_copy(update={"limits": limits})
    return ModelCatalog(models=models)


class FakeGenerators(StubResolver):
    def __init__(self, tts: FakeTTS, video: FakeVideo) -> None:
        super().__init__(FakeLLM())
        self._tts, self._video = tts, video

    def tts(self, key: str) -> TTSProvider:
        return self._tts

    def video(self, key: str) -> VideoProvider:
        return self._video


@dataclass
class Stage2:
    repo: InMemoryJobRepository
    bus: RecordingEventBus
    cache: FileArtifactCache
    behavior: FakeBehavior
    origin: FakeMediaOrigin
    coordinator: RenderCoordinator
    runner: JobRunner
    control: JobControlService

    async def approved_job(self, n: int = 3, **scene_prompts: str) -> JobState:
        job = make_job(JobStatus.APPROVED, n=n)
        script = job.require_script()
        scenes = [s.model_copy(update={"prompt_video": scene_prompts.get(f"p{s.scene_index}",
                                                                         s.prompt_video)})
                  for s in script.cenas]  # fmt: skip
        job.script = script.model_copy(update={"cenas": scenes})
        return await self.repo.create(JobState.model_validate(job.model_dump()))

    async def render(self) -> JobState:
        return await self.coordinator.run(JOB_ID)


def build_stage2(tmp_path: Path, *, max_parallel_video: int = 8) -> Stage2:
    clock, behavior = FakeClock(), FakeBehavior()
    repo, bus = InMemoryJobRepository(clock), RecordingEventBus(clock)
    origin, cache = FakeMediaOrigin(tmp_path / "origin"), FileArtifactCache(tmp_path / "cache")
    composer = FfmpegMediaComposer(LoudnessNormalizer(RUNNER),
                                   SceneComposer(RUNNER, PROBE, encoding=FAST),
                                   Concatenator(RUNNER, PROBE, FAST))  # fmt: skip
    ports = RenderPorts(repo=repo, bus=bus, catalog=small_catalog(),
                        providers=FakeGenerators(FakeTTS(origin, behavior),
                                                 FakeVideo(origin, behavior)),
                        voices=InMemoryVoiceStore(), cache=cache, downloader=origin, probe=PROBE,
                        composer=composer)  # fmt: skip
    coordinator = build_render(ports, RenderTuning(max_parallel_video=max_parallel_video))
    script = ScriptService(repo, bus, StubResolver(FakeLLM()), InMemoryScriptHistory())

    async def no_crash(*_: object) -> None:
        return None

    runner = JobRunner(max_parallel=2, on_crash=no_crash)
    control = JobControlService(repo, bus, runner, script, render=coordinator.run)
    return Stage2(repo=repo, bus=bus, cache=cache, behavior=behavior, origin=origin,
                  coordinator=coordinator, runner=runner, control=control)  # fmt: skip
