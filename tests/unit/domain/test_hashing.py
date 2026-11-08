"""T-014: hash de conteúdo — estável, sensível a todo parâmetro e cego a índice/caminho."""

from pathlib import Path
from typing import Any

import pytest

from tests.unit.domain.test_request_generation import make_tts, make_video
from videogen.domain.hashing import (
    HASH_SCHEMA_VERSION,
    audio_hash,
    audio_norm_hash,
    clip_hash,
    content_hash,
    final_hash,
    video_hash,
)
from videogen.domain.media import ArtifactKind
from videogen.domain.render_specs import ClipParams, ConcatParams, LoudnessParams
from videogen.domain.sync import SyncConfig

# Golden vectors (HASH_SCHEMA_VERSION = 1). Se mudarem, todo o cache existente é invalidado:
# só atualize junto com HASH_SCHEMA_VERSION e de propósito.
GOLDEN = {
    "audio": "360e1853431faf2b9c046875cca2a1bf70bec8ae0fac6f0db3fa62ca3d5dbc71",
    "video": "f17ab55930d3186f2bb68425ca8a4d746a6b7280157651cf92bdf2da0d44fb14",
    "audio_norm": "272a69fc2bdcf4f7b23c47d6c6d4ed8b8c4c8d13fb6c5fa784d6bec20e28f498",
    "clip": "d0417593ed3fe0e8e4dade6d1ad2ad701d95a5cfdd71ead6a69fc5ae4525b478",
    "final": "1d3c573ae9f8654295d01c6b59ddab8c65ad000ee4ef5a2b5f2a03ca6a0e02a2",
}


def _clip_params(**overrides: Any) -> ClipParams:
    data: dict[str, Any] = {
        "texto": "Proteja seu futuro.",
        "aspect_ratio": "9:16",
        "width": 720,
        "height": 1280,
        "fps": 30,
    }
    return ClipParams.model_validate(data | overrides)


def test_golden_vectors() -> None:
    assert HASH_SCHEMA_VERSION == 1
    audio, video = audio_hash(make_tts()), video_hash(make_video())
    norm = audio_norm_hash(audio, LoudnessParams())
    clip = clip_hash(norm, video, _clip_params())
    computed = {
        "audio": audio,
        "video": video,
        "audio_norm": norm,
        "clip": clip,
        "final": final_hash([clip, clip], ConcatParams()),
    }
    assert computed == GOLDEN


TTS_CHANGES = [
    ("model_key", "fish-speech-1.5"),
    ("model_version", "v2"),
    ("text", "Outro texto."),
    ("language", "en-US"),
    ("ref_text", "Outra referência."),
    ("ref_audio_sha256", "b" * 64),
    ("speed", 1.1),
]
VIDEO_CHANGES = [
    ("model_key", "cogvideox-5b"),
    ("model_version", "v2"),
    ("prompt", "A man runs"),
    ("negative_prompt", "blurry"),
    ("width", 720),
    ("height", 1280),
    ("num_frames", 49),
    ("fps", 8),
    ("seed", 43),
    ("extra", {"guidance": 6.0}),
]


@pytest.mark.parametrize(("field", "value"), TTS_CHANGES)
def test_todo_parametro_do_tts_muda_o_hash(field: str, value: object) -> None:
    assert audio_hash(make_tts(**{field: value})) != audio_hash(make_tts())


@pytest.mark.parametrize(("field", "value"), VIDEO_CHANGES)
def test_todo_parametro_do_video_muda_o_hash(field: str, value: object) -> None:
    assert video_hash(make_video(**{field: value})) != video_hash(make_video())


def test_listas_de_mudanca_cobrem_todos_os_campos() -> None:
    from videogen.domain.generation import TTSRequest, VideoRequest

    tts_fields = set(TTSRequest.model_fields) - {"ref_audio_path"}
    assert {field for field, _ in TTS_CHANGES} == tts_fields
    assert {field for field, _ in VIDEO_CHANGES} == set(VideoRequest.model_fields)


def test_caminho_da_voz_nao_muda_o_hash() -> None:
    assert audio_hash(make_tts(ref_audio_path=Path("/outro/lugar.wav"))) == audio_hash(make_tts())


def test_texto_visualmente_igual_gera_mesmo_hash() -> None:
    assert audio_hash(make_tts(text="Proteja   seu futuro. ")) == audio_hash(make_tts())


def test_ordem_das_chaves_e_irrelevante() -> None:
    kind = ArtifactKind.CLIP
    assert content_hash(kind, {"a": 1, "b": 2}) == content_hash(kind, {"b": 2, "a": 1})
    assert content_hash(kind, {"a": 1}) != content_hash(ArtifactKind.FINAL, {"a": 1})


def test_derivados_encadeiam_a_origem() -> None:
    norm = audio_norm_hash("a" * 64, LoudnessParams())
    assert norm != audio_norm_hash("b" * 64, LoudnessParams())
    assert norm != audio_norm_hash("a" * 64, LoudnessParams(integrated_lufs=-16))
    base = clip_hash(norm, "v" * 64, _clip_params())
    assert base != clip_hash(norm, "v" * 64, _clip_params(subtitles=False))
    assert base != clip_hash(norm, "v" * 64, _clip_params(sync=SyncConfig(stretch_max=1.5)))


def test_ordem_dos_clipes_importa_no_final() -> None:
    first, second = "1" * 64, "2" * 64
    assert final_hash([first, second], ConcatParams()) != final_hash(
        [second, first], ConcatParams()
    )
