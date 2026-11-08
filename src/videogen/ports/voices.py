"""Port do armazenamento de vozes de referência (RF-12)."""

from typing import Protocol, runtime_checkable

from videogen.domain.media import VoiceRef


@runtime_checkable
class VoiceStore(Protocol):
    async def save(self, audio_wav: bytes, *, name: str, ref_text: str) -> VoiceRef:
        """Recebe áudio já validado e normalizado pelo VoiceService."""
        ...

    async def get(self, voice_id: str) -> VoiceRef: ...

    async def list_all(self) -> list[VoiceRef]: ...

    async def delete(self, voice_id: str) -> None: ...
