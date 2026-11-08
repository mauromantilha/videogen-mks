"""Dependências compartilhadas pelas etapas de uma cena (evita construtores com 9 argumentos)."""

from dataclasses import dataclass
from pathlib import Path

from videogen.domain.catalog import ModelCatalog
from videogen.domain.render_specs import LoudnessParams
from videogen.domain.sync import SyncConfig
from videogen.ports.cache import ArtifactCache
from videogen.ports.composer import MediaComposer
from videogen.ports.resolver import ProviderResolver
from videogen.ports.voices import VoiceStore
from videogen.services.render.cached_step import CachedStep
from videogen.services.render.limiter import ProviderLimiter
from videogen.services.render.single_flight import SingleFlight
from videogen.services.render.step_tracker import StepTracker


@dataclass(frozen=True)
class RenderContext:
    catalog: ModelCatalog
    providers: ProviderResolver
    voices: VoiceStore
    cache: ArtifactCache
    composer: MediaComposer
    cached_step: CachedStep
    tracker: StepTracker
    limiter: ProviderLimiter
    flight: SingleFlight
    loudness: LoudnessParams
    sync: SyncConfig


@dataclass(frozen=True)
class StepOutput:
    path: Path
    key: str
