"""Cadastro de vozes de referência (RF-12).

O F5-TTS aceita no máximo ~30 s de referência + fala gerada, e o Replicate recebe a referência
inline (data URI ≤ 1 MB): por isso a referência fica curta (padrão 3 a 12 s) e é gravada como WAV
mono 24 kHz normalizado em loudness (12 s ≈ 576 KB).
"""

import asyncio
import uuid
from dataclasses import dataclass
from pathlib import Path

from videogen.core.errors import MediaError, ValidationFailed
from videogen.domain.media import ArtifactKind, VoiceRef
from videogen.domain.render_specs import LoudnessParams
from videogen.ports.composer import MediaComposer
from videogen.ports.probe import MediaProbe
from videogen.ports.voices import VoiceStore

ALLOWED_EXTENSIONS = frozenset({".wav", ".mp3", ".m4a", ".flac", ".ogg"})
REFERENCE_FORMAT = LoudnessParams(sample_rate=24_000)
MAX_REFERENCE_BYTES = 1_000_000


class InvalidVoice(ValidationFailed):
    code = "INVALID_VOICE"


@dataclass(frozen=True)
class VoiceLimits:
    max_upload_bytes: int = 10 * 1024 * 1024
    min_seconds: float = 3.0
    max_seconds: float = 12.0


class VoiceService:
    def __init__(
        self, store: VoiceStore, probe: MediaProbe, composer: MediaComposer, scratch: Path,
        limits: VoiceLimits | None = None,
    ) -> None:  # fmt: skip
        self._store, self._probe, self._composer = store, probe, composer
        self._scratch, self._limits = scratch, limits or VoiceLimits()

    async def register(self, audio: bytes, *, filename: str, name: str, ref_text: str) -> VoiceRef:
        self._check_input(audio, filename, name, ref_text)
        token = uuid.uuid4().hex
        # Nomes distintos: um upload .wav não pode coincidir com a saída convertida.
        upload = self._scratch / f"voz-{token}-upload{Path(filename).suffix.lower()}"
        reference = self._scratch / f"voz-{token}-ref.wav"
        try:
            await asyncio.to_thread(_write, upload, audio)
            duration = await self._duration(upload)
            await self._composer.normalize_audio(upload, reference, REFERENCE_FORMAT)
            wav = await asyncio.to_thread(reference.read_bytes)
        finally:
            for path in (upload, reference):
                await asyncio.to_thread(path.unlink, True)
        if len(wav) > MAX_REFERENCE_BYTES:
            raise InvalidVoice("referência grande demais após a conversão; use um trecho menor")
        return await self._store.save(
            wav, name=name.strip(), ref_text=" ".join(ref_text.split()), duration_s=duration
        )

    def _check_input(self, audio: bytes, filename: str, name: str, ref_text: str) -> None:
        if Path(filename).suffix.lower() not in ALLOWED_EXTENSIONS:
            raise InvalidVoice(f"formato não suportado; use {sorted(ALLOWED_EXTENSIONS)}")
        if not audio or len(audio) > self._limits.max_upload_bytes:
            raise InvalidVoice(f"arquivo vazio ou maior que {self._limits.max_upload_bytes} bytes")
        if not ref_text.strip():
            raise InvalidVoice("informe a transcrição exata do áudio (ref_text)")
        if not name.strip():
            raise InvalidVoice("informe um nome para a voz")

    async def _duration(self, upload: Path) -> float:
        try:
            info = await self._probe.validate(upload, ArtifactKind.AUDIO_RAW)
        except MediaError as exc:
            raise InvalidVoice("o arquivo não é um áudio válido") from exc
        low, high = self._limits.min_seconds, self._limits.max_seconds
        if not low <= info.duration_s <= high:
            raise InvalidVoice(
                f"a referência deve ter entre {low:g} e {high:g} segundos "
                f"(tem {info.duration_s:.1f} s)"
            )
        return info.duration_s


def _write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
