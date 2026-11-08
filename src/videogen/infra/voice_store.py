"""Vozes de referência em `_voices/{voice_id}/` (RF-12).

Recebe o áudio já validado e normalizado pelo VoiceService; aqui só persiste e consulta.
O `sha256` do conteúdo compõe o hash do áudio gerado (`TTSRequest.ref_audio_sha256`).
"""

import asyncio
import hashlib
import shutil
from pathlib import Path

from videogen.core.clock import Clock
from videogen.core.errors import NotFound
from videogen.core.ids import new_voice_id
from videogen.domain.media import VoiceRef
from videogen.infra.atomic_file import write_atomic
from videogen.infra.workspace import Workspace

AUDIO_FILE = "ref.wav"
META_FILE = "voice.json"


class FileVoiceStore:
    def __init__(self, workspace: Workspace, clock: Clock) -> None:
        self._workspace = workspace
        self._clock = clock

    async def save(
        self, audio_wav: bytes, *, name: str, ref_text: str, duration_s: float
    ) -> VoiceRef:
        voice_id = new_voice_id()
        directory = self._workspace.voice_dir(voice_id)
        voice = VoiceRef(
            voice_id=voice_id,
            name=name,
            ref_text=ref_text,
            sha256=hashlib.sha256(audio_wav).hexdigest(),
            duration_s=duration_s,
            path=directory / AUDIO_FILE,
            created_at=self._clock.now(),
        )
        await asyncio.to_thread(write_atomic, voice.path, audio_wav)
        meta = voice.model_dump_json(indent=2).encode("utf-8")
        await asyncio.to_thread(write_atomic, directory / META_FILE, meta)
        return voice

    async def get(self, voice_id: str) -> VoiceRef:
        meta = self._workspace.voice_dir(voice_id) / META_FILE
        if not meta.is_file():
            raise NotFound("voz não encontrada", voice_id=voice_id)
        return await asyncio.to_thread(_read, meta)

    async def list_all(self) -> list[VoiceRef]:
        metas = sorted(self._workspace.voices_dir.glob(f"voz_*/{META_FILE}"))
        voices = [await asyncio.to_thread(_read, meta) for meta in metas]
        return sorted(voices, key=lambda voice: voice.created_at, reverse=True)

    async def delete(self, voice_id: str) -> None:
        directory = self._workspace.voice_dir(voice_id)
        if not directory.is_dir():
            raise NotFound("voz não encontrada", voice_id=voice_id)
        await asyncio.to_thread(shutil.rmtree, directory)


def _read(meta: Path) -> VoiceRef:
    return VoiceRef.model_validate_json(meta.read_bytes())
