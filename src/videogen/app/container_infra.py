"""Wiring da infraestrutura: disco, repositório, cache, eventos, vozes, mídia e download."""

from dataclasses import dataclass

import httpx

from videogen.composer.concat import Concatenator
from videogen.composer.ffmpeg_runner import FfmpegRunner
from videogen.composer.healthcheck import ToolchainCheck
from videogen.composer.loudnorm import LoudnessNormalizer
from videogen.composer.media_composer import FfmpegMediaComposer
from videogen.composer.probe import FfprobeProbe
from videogen.composer.scene_composer import SceneComposer
from videogen.core.clock import Clock
from videogen.core.config import Settings
from videogen.core.retry import RetryPolicy
from videogen.infra.artifact_cache import FileArtifactCache
from videogen.infra.downloader import HttpDownloader
from videogen.infra.event_audit import EventAuditLog
from videogen.infra.event_bus import InMemoryEventBus
from videogen.infra.job_repository import JsonJobRepository
from videogen.infra.script_history import FileScriptHistory
from videogen.infra.voice_store import FileVoiceStore
from videogen.infra.workspace import Workspace


@dataclass(frozen=True)
class Infra:
    workspace: Workspace
    repo: JsonJobRepository
    cache: FileArtifactCache
    bus: InMemoryEventBus
    history: FileScriptHistory
    voice_store: FileVoiceStore
    probe: FfprobeProbe
    composer: FfmpegMediaComposer
    toolchain: ToolchainCheck
    downloader: HttpDownloader
    download_client: httpx.AsyncClient


def build_infra(settings: Settings, clock: Clock, policy: RetryPolicy) -> Infra:
    workspace = Workspace(settings.app.workspace_dir)
    bus = InMemoryEventBus(clock)
    bus.add_sink(EventAuditLog(workspace))
    runner = FfmpegRunner(max_parallel=settings.render.max_parallel_ffmpeg)
    probe = FfprobeProbe(runner)
    composer = FfmpegMediaComposer(
        LoudnessNormalizer(runner), SceneComposer(runner, probe), Concatenator(runner, probe)
    )
    download_client = httpx.AsyncClient(timeout=httpx.Timeout(60.0, connect=10.0))
    return Infra(
        workspace=workspace,
        repo=JsonJobRepository(workspace, clock),
        cache=FileArtifactCache(workspace.cache_dir),
        bus=bus,
        history=FileScriptHistory(workspace),
        voice_store=FileVoiceStore(workspace, clock),
        probe=probe,
        composer=composer,
        toolchain=ToolchainCheck(runner),
        downloader=HttpDownloader(download_client, policy),
        download_client=download_client,
    )
