"""Port para obter o adapter de um modelo pela chave do catálogo (implementado pelo registry)."""

from typing import Protocol, runtime_checkable

from videogen.ports.llm import LLMProvider
from videogen.ports.tts import TTSProvider
from videogen.ports.video import VideoProvider


@runtime_checkable
class ProviderResolver(Protocol):
    def llm(self, key: str) -> LLMProvider: ...

    def tts(self, key: str) -> TTSProvider: ...

    def video(self, key: str) -> VideoProvider: ...
