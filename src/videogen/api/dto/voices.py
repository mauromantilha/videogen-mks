"""Visão pública de uma voz (sem caminho em disco)."""

from datetime import datetime

from pydantic import BaseModel

from videogen.domain.media import VoiceRef


class VoiceView(BaseModel):
    voice_id: str
    name: str
    ref_text: str
    duration_s: float
    created_at: datetime

    @classmethod
    def of(cls, voice: VoiceRef) -> "VoiceView":
        return cls(voice_id=voice.voice_id, name=voice.name, ref_text=voice.ref_text,
                   duration_s=voice.duration_s, created_at=voice.created_at)  # fmt: skip
