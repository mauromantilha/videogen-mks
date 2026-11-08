"""VoiceStore em memória, já com a voz padrão dos builders."""

import hashlib
from pathlib import Path
from typing import TYPE_CHECKING

from tests.fakes.builders import VOICE_ID
from tests.fakes.fake_clock import DEFAULT_START
from videogen.core.errors import NotFound
from videogen.domain.media import VoiceRef

DEFAULT_VOICE = VoiceRef(
    voice_id=VOICE_ID, name="Padrão", ref_text="Olá, esta é a minha voz.",
    sha256=hashlib.sha256(b"voz").hexdigest(), duration_s=6.0,
    path=Path("vozes/ref.wav"), created_at=DEFAULT_START,
)  # fmt: skip


class InMemoryVoiceStore:
    def __init__(self, *voices: VoiceRef) -> None:
        self.voices = {voice.voice_id: voice for voice in (voices or (DEFAULT_VOICE,))}
        self.saved: list[bytes] = []

    async def save(
        self, audio_wav: bytes, *, name: str, ref_text: str, duration_s: float
    ) -> VoiceRef:
        voice_id = f"voz_{len(self.voices):012x}"
        voice = DEFAULT_VOICE.model_copy(update={
            "voice_id": voice_id, "name": name, "ref_text": ref_text, "duration_s": duration_s,
            "sha256": hashlib.sha256(audio_wav).hexdigest()})  # fmt: skip
        self.voices[voice_id] = voice
        self.saved.append(audio_wav)
        return voice

    async def get(self, voice_id: str) -> VoiceRef:
        if voice_id not in self.voices:
            raise NotFound("voz não encontrada")
        return self.voices[voice_id]

    async def list_all(self) -> list[VoiceRef]:
        return list(self.voices.values())

    async def delete(self, voice_id: str) -> None:
        await self.get(voice_id)
        del self.voices[voice_id]


if TYPE_CHECKING:
    from videogen.ports.voices import VoiceStore

    _conforms: VoiceStore = InMemoryVoiceStore()
