"""T-058 com FFmpeg real: validação, conversão para referência compacta e limpeza."""

from pathlib import Path

import pytest

from tests.fakes.media_factory import PROBE, RUNNER, make_audio
from tests.fakes.memory_voices import InMemoryVoiceStore
from videogen.composer.concat import Concatenator
from videogen.composer.loudnorm import LoudnessNormalizer
from videogen.composer.media_composer import FfmpegMediaComposer
from videogen.composer.scene_composer import SceneComposer
from videogen.services.voices import InvalidVoice, VoiceService

pytestmark = pytest.mark.ffmpeg
REF_TEXT = "Olá, esta é a minha voz de referência."


def _service(tmp_path: Path) -> tuple[VoiceService, InMemoryVoiceStore]:
    store = InMemoryVoiceStore()
    composer = FfmpegMediaComposer(
        LoudnessNormalizer(RUNNER), SceneComposer(RUNNER, PROBE), Concatenator(RUNNER, PROBE)
    )
    return VoiceService(store, PROBE, composer, tmp_path / "scratch"), store


async def _upload(tmp_path: Path, seconds: float, name: str = "minha.wav") -> bytes:
    return (await make_audio(tmp_path / name, seconds)).read_bytes()


async def test_registra_referencia_compacta(tmp_path: Path) -> None:
    service, store = _service(tmp_path)
    voice = await service.register(
        await _upload(tmp_path, 8),
        filename="Minha Voz.WAV",
        name=" Mauro ",
        ref_text=f"  {REF_TEXT}\n",
    )
    assert (voice.name, voice.ref_text) == ("Mauro", REF_TEXT)
    assert voice.duration_s == pytest.approx(8, abs=0.05)
    wav = store.saved[-1]
    assert len(wav) < 1_000_000 and wav[:4] == b"RIFF"
    reference = tmp_path / "ref.wav"
    reference.write_bytes(wav)
    info = await PROBE.probe(reference)
    assert (info.sample_rate, info.audio_codec) == (24000, "pcm_s16le")
    assert list((tmp_path / "scratch").iterdir()) == []  # temporários removidos


@pytest.mark.parametrize(
    ("seconds", "filename", "ref_text", "match"),
    [
        (1.0, "a.wav", REF_TEXT, "entre 3 e 12"),
        (14.0, "a.wav", REF_TEXT, "entre 3 e 12"),
        (5.0, "a.exe", REF_TEXT, "formato"),
        (5.0, "a.wav", "   ", "transcrição"),
    ],
)
async def test_recusa_referencias_invalidas(
    tmp_path: Path, seconds: float, filename: str, ref_text: str, match: str
) -> None:
    service, store = _service(tmp_path)
    with pytest.raises(InvalidVoice, match=match):
        await service.register(
            await _upload(tmp_path, seconds), filename=filename, name="x", ref_text=ref_text
        )
    assert store.saved == []


async def test_arquivo_que_nao_e_audio(tmp_path: Path) -> None:
    service, _ = _service(tmp_path)
    with pytest.raises(InvalidVoice, match="não é um áudio"):
        await service.register(
            b"isto nao e audio" * 100, filename="a.wav", name="x", ref_text=REF_TEXT
        )
