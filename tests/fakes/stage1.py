"""Monta os serviços da Etapa 1 com dublês (sem rede, sem disco além de `tmp_path`)."""

from dataclasses import dataclass
from pathlib import Path

from tests.fakes.fake_clock import FakeClock
from tests.fakes.memory_cache import InMemoryArtifactCache
from tests.fakes.memory_history import InMemoryScriptHistory
from tests.fakes.memory_repository import InMemoryJobRepository
from tests.fakes.memory_voices import InMemoryVoiceStore
from tests.fakes.recording_bus import RecordingEventBus
from videogen.domain.catalog import ModelCatalog
from videogen.ports.llm import LLMProvider
from videogen.ports.tts import TTSProvider
from videogen.ports.video import VideoProvider
from videogen.providers.catalog.loader import load_catalog
from videogen.providers.fake.llm import FakeLLM
from videogen.services.cost.estimator import CostEstimator
from videogen.services.jobs.approval import ApprovalService, RenderEntry
from videogen.services.jobs.creation import CreationDeps, JobCreationService
from videogen.services.jobs.lifecycle import JobControlService
from videogen.services.jobs.recovery import RecoveryService
from videogen.services.jobs.runner import JobRunner
from videogen.services.script.edit_service import ScriptEditService
from videogen.services.script.script_service import ScriptService

CATALOG = load_catalog(Path(__file__).resolve().parents[2] / "config/models.yaml")


class StubResolver:
    def __init__(self, llm: LLMProvider) -> None:
        self.llm_provider = llm

    def llm(self, key: str) -> LLMProvider:
        return self.llm_provider

    def tts(self, key: str) -> TTSProvider:
        raise AssertionError("a Etapa 1 nunca chama TTS")

    def video(self, key: str) -> VideoProvider:
        raise AssertionError("a Etapa 1 nunca chama vídeo")


@dataclass
class Stage1:
    clock: FakeClock
    repo: InMemoryJobRepository
    bus: RecordingEventBus
    history: InMemoryScriptHistory
    cache: InMemoryArtifactCache
    voices: InMemoryVoiceStore
    llm: FakeLLM
    runner: JobRunner
    script: ScriptService
    edits: ScriptEditService
    creation: JobCreationService
    control: JobControlService
    approval: ApprovalService
    recovery: RecoveryService
    catalog: ModelCatalog = CATALOG


def build_stage1(
    tmp_path: Path, llm: FakeLLM | None = None, render: RenderEntry | None = None
) -> Stage1:
    clock, llm = FakeClock(), llm or FakeLLM()
    repo, bus, history = (
        InMemoryJobRepository(clock),
        RecordingEventBus(clock),
        InMemoryScriptHistory(),
    )
    cache, voices = InMemoryArtifactCache(tmp_path / "cache"), InMemoryVoiceStore()
    script = ScriptService(repo, bus, StubResolver(llm), history)
    holder: list[JobControlService] = []

    async def on_crash(job_id: str, stage: str, exc: BaseException) -> None:
        await holder[0].mark_crashed(job_id, stage, exc)  # type: ignore[arg-type]

    runner = JobRunner(max_parallel=4, on_crash=on_crash)
    control = JobControlService(repo, bus, runner, script, render=render)
    holder.append(control)
    estimator = CostEstimator(CATALOG, cache, voices)
    return Stage1(
        clock=clock, repo=repo, bus=bus, history=history, cache=cache, voices=voices, llm=llm,
        runner=runner, script=script, edits=ScriptEditService(repo, bus, history),
        creation=JobCreationService(CreationDeps(repo, bus, runner, script, history), CATALOG,
                                    voices, clock),
        control=control,
        approval=ApprovalService(repo, bus, estimator, runner, clock, render=render),
        recovery=RecoveryService(repo, bus, runner, script, render=render),
    )  # fmt: skip
