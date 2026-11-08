"""Escolhe e monta o adapter de cada modelo do catálogo (RNF-03).

Modo `fake`: todo modelo usa o adapter simulado (custo zero). Modo `real`: exige credencial
e `verified: true` — um modelo cujos campos não foram conferidos com o schema oficial
falharia só depois de cobrar; melhor falhar antes.
"""

from collections.abc import Mapping
from typing import Literal

from videogen.core.config import ConfigError
from videogen.domain.catalog import FAKE_PROVIDER, ModelCatalog, ModelKind, ModelSpec
from videogen.ports.llm import LLMProvider
from videogen.ports.tts import TTSProvider
from videogen.ports.video import VideoProvider
from videogen.providers.catalog.builders import DEFAULT_BUILDERS, Builder
from videogen.providers.catalog.context import ProviderContext

Mode = Literal["real", "fake"]


class ProviderRegistry:
    def __init__(
        self,
        catalog: ModelCatalog,
        context: ProviderContext,
        *,
        mode: Mode,
        builders: Mapping[tuple[ModelKind, str], Builder] = DEFAULT_BUILDERS,
    ) -> None:
        self.catalog = catalog
        self._context = context
        self._mode = mode
        self._builders = builders
        self._instances: dict[str, object] = {}

    def llm(self, key: str) -> LLMProvider:
        instance = self._build(key, "llm")
        if not isinstance(instance, LLMProvider):
            raise TypeError(f"{key}: adapter não implementa LLMProvider")
        return instance

    def tts(self, key: str) -> TTSProvider:
        instance = self._build(key, "tts")
        if not isinstance(instance, TTSProvider):
            raise TypeError(f"{key}: adapter não implementa TTSProvider")
        return instance

    def video(self, key: str) -> VideoProvider:
        instance = self._build(key, "t2v")
        if not isinstance(instance, VideoProvider):
            raise TypeError(f"{key}: adapter não implementa VideoProvider")
        return instance

    def available(self, kind: ModelKind) -> list[ModelSpec]:
        """Modelos utilizáveis agora (RF-14): no modo real, só com credencial e verificados."""
        return [spec for spec in self.catalog.of_kind(kind) if self._usable(spec)]

    def _usable(self, spec: ModelSpec) -> bool:
        if self._mode == "fake":
            return True
        return spec.verified and self._context.has_credential(spec.provider)

    def _build(self, key: str, kind: ModelKind) -> object:
        spec = self.catalog.get(key, kind)
        if key not in self._instances:
            provider = FAKE_PROVIDER if self._mode == "fake" else spec.provider
            if self._mode == "real" and not spec.verified:
                raise ConfigError(
                    f"{key} não está verificado: confira os campos com "
                    "`python scripts/replicate_schema.py` e marque `verified: true`"
                )
            builder = self._builders.get((kind, provider))
            if builder is None:
                raise ConfigError(f"sem adapter para {kind}/{provider} ({key})")
            self._instances[key] = builder(spec, self._context)
        return self._instances[key]
