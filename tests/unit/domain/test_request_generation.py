"""T-011: pedido do job e requests de geração."""

import unicodedata
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from tests.fakes.builders import make_request
from videogen.domain.generation import GenerationResult, TTSRequest, VideoRequest

SHA = "a" * 64


def make_tts(**overrides: Any) -> TTSRequest:
    data: dict[str, Any] = {
        "model_key": "f5-tts",
        "model_version": "v1",
        "text": "Proteja seu futuro.",
        "ref_text": "Texto da referência.",
        "ref_audio_sha256": SHA,
        "ref_audio_path": Path("vozes/ref.wav"),
    }
    return TTSRequest.model_validate(data | overrides)


def make_video(**overrides: Any) -> VideoRequest:
    data: dict[str, Any] = {
        "model_key": "wan-2.1-t2v-480p",
        "model_version": "v1",
        "prompt": "A woman smiles at her phone",
        "width": 480,
        "height": 832,
        "num_frames": 81,
        "fps": 16,
        "seed": 42,
    }
    return VideoRequest.model_validate(data | overrides)


def test_pedido_com_padroes() -> None:
    request = make_request()
    assert (request.aspect_ratio, request.options.fps, request.max_budget_usd) == ("9:16", 30, 2.0)


@pytest.mark.parametrize(
    "overrides",
    [
        {"n_cenas": 1},
        {"n_cenas": 11},
        {"voice_id": "../voz"},
        {"max_budget_usd": 0},
        {"max_budget_usd": 101},
        {"tema": "ab"},
        {"aspect_ratio": "4:3"},
        {"options": {"fps": 25}},
    ],
)
def test_pedido_invalido(overrides: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        make_request(**overrides)


def test_limites_do_roteiro_derivados_do_pedido() -> None:
    request = make_request(n_cenas=4, options={"duracao_cena_s": 5})
    assert request.script_limits().expected_scenes is None
    limits = request.script_limits(enforce_scene_count=True)
    assert (limits.expected_scenes, limits.max_words) == (4, 15)


def test_caminho_da_voz_fica_fora_do_dump() -> None:
    dumped = make_tts().model_dump()
    assert "ref_audio_path" not in dumped
    assert dumped["ref_audio_sha256"] == SHA


def test_texto_e_normalizado_nfc_e_espacos() -> None:
    decomposed = unicodedata.normalize("NFD", "proteção   total ")
    assert make_tts(text=decomposed).text == unicodedata.normalize("NFC", "proteção total")


@pytest.mark.parametrize("overrides", [{"ref_audio_sha256": "xyz"}, {"speed": 3.0}, {"text": "  "}])
def test_tts_invalido(overrides: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        make_tts(**overrides)


@pytest.mark.parametrize("overrides", [{"seed": -1}, {"seed": 2**31}, {"width": 0}])
def test_video_invalido(overrides: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        make_video(**overrides)


def test_requests_sao_imutaveis() -> None:
    with pytest.raises(ValidationError):
        make_video().seed = 1  # type: ignore[misc]


def test_resultado_de_geracao() -> None:
    result = GenerationResult(remote_id="p1", output_url="https://replicate.delivery/x.mp4")
    assert result.cost_usd is None
    with pytest.raises(ValidationError):
        GenerationResult(remote_id="p1", output_url="u", cost_usd=-1)
