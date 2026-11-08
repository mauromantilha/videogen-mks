"""T-034: mapeamento de campos via YAML e extração de URL de saída."""

from pathlib import Path

import pytest

from tests.unit.domain.test_request_generation import make_tts, make_video
from videogen.core.errors import ProviderError
from videogen.domain.catalog import ModelSpec
from videogen.providers.replicate.mapping import (
    MAX_DATA_URI_BYTES,
    audio_data_uri,
    build_input,
    tts_values,
    video_values,
)
from videogen.providers.replicate.runner import extract_url

ROOT = Path(__file__).resolve().parents[3]


def _spec(**fields: str) -> ModelSpec:
    return ModelSpec(
        key="m",
        kind="t2v",
        provider="replicate",
        remote_ref="o/n",
        fields=dict(fields),
        price={"unit": "per_run"},  # type: ignore[arg-type]
        allowed_hosts=("replicate.delivery",),
        defaults={"fast_mode": "Balanced"},
        limits={"fps": 16, "num_frames": 81, "sizes": {"9:16": [480, 832]}},
    )  # type: ignore[arg-type]


def test_video_usa_so_os_campos_declarados_mais_defaults() -> None:
    spec = _spec(prompt="prompt", seed="seed", aspect_ratio="aspect_ratio")
    payload = build_input(spec, dict(video_values(make_video(extra={"sample_steps": 30}))))
    assert payload == {
        "fast_mode": "Balanced",
        "prompt": "A woman smiles at her phone",
        "seed": 42,
        "aspect_ratio": "9:16",
    }


def test_valores_de_video_derivados() -> None:
    values = video_values(make_video(width=832, height=480, extra={"guidance": 5.0}))
    assert (values["aspect_ratio"], values["duration_s"], values["guidance"]) == ("16:9", 5, 5.0)
    assert values["negative_prompt"] is None  # vazio não é enviado


def test_tts_envia_referencia_como_data_uri() -> None:
    spec = ModelSpec(
        key="t",
        kind="tts",
        provider="replicate",
        remote_ref="o/n",
        fields={"text": "gen_text", "ref_audio": "ref_audio", "ref_text": "ref_text"},
        price={"unit": "per_run"},
        allowed_hosts=("replicate.delivery",),
    )  # type: ignore[arg-type]
    payload = build_input(spec, tts_values(make_tts(), b"RIFF"))
    assert payload == {
        "gen_text": "Proteja seu futuro.",
        "ref_text": "Texto da referência.",
        "ref_audio": "data:audio/wav;base64,UklGRg==",
    }


def test_referencia_grande_demais_e_recusada() -> None:
    with pytest.raises(ProviderError, match="excede"):
        audio_data_uri(b"x" * (MAX_DATA_URI_BYTES + 1))


@pytest.mark.parametrize(
    "output",
    [
        "https://replicate.delivery/a.mp4",
        ["https://replicate.delivery/a.mp4", "https://replicate.delivery/b.mp4"],
        {"video": "https://replicate.delivery/a.mp4"},
        {"audio": {"url": "https://replicate.delivery/a.mp4"}},
    ],
)
def test_extrai_url_de_formatos_variados(output: object) -> None:
    assert extract_url(output) == "https://replicate.delivery/a.mp4"


@pytest.mark.parametrize("output", [None, "texto", [], {"seed": 1}, "http://inseguro/a.mp4"])
def test_saida_sem_url(output: object) -> None:
    with pytest.raises(ProviderError):
        extract_url(output)
