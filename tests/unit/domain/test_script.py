"""T-010: contrato do roteiro e regras de negócio."""

import pytest
from pydantic import ValidationError

from tests.fakes.builders import PROMPT, make_scene, make_script
from videogen.domain.script import VideoScriptSchema
from videogen.domain.script_rules import (
    ScriptLimits,
    ScriptValidationError,
    count_words,
    ensure_valid,
    validate_rules,
)

LIMITS = ScriptLimits()


def _codes(script: VideoScriptSchema, limits: ScriptLimits = LIMITS) -> set[tuple[int | None, str]]:
    return {(v.scene_index, v.code) for v in validate_rules(script, limits)}


def test_roteiro_valido_nao_tem_violacoes() -> None:
    assert validate_rules(make_script(3), LIMITS) == []


def test_indices_devem_ser_contiguos_e_em_ordem() -> None:
    cenas = [make_scene(0).model_dump(), make_scene(2).model_dump()]
    with pytest.raises(ValidationError, match="scene_index"):
        make_script(cenas=cenas)


def test_campos_inventados_pelo_llm_sao_rejeitados() -> None:
    with pytest.raises(ValidationError, match="extra"):
        make_script(musica="lofi")


@pytest.mark.parametrize("n", [1, 11])
def test_numero_de_cenas_fora_da_faixa(n: int) -> None:
    with pytest.raises(ValidationError):
        make_script(n)


def test_espacos_sao_removidos() -> None:
    assert make_scene(texto_narrado="  Olá mundo.  ").texto_narrado == "Olá mundo."


def test_with_scenes_reordena_e_renumera() -> None:
    script = make_script(3)
    a, _, c = script.cenas
    reordered = script.with_scenes([c, a])
    assert [s.scene_index for s in reordered.cenas] == [0, 1]
    assert reordered.cenas[0].texto_narrado == c.texto_narrado
    with pytest.raises(ValidationError):
        script.with_scenes([a])  # abaixo do mínimo


@pytest.mark.parametrize(
    ("text", "words"),
    [("Olá, mundo!", 2), ("Seguro — simples e rápido.", 4), ("...", 0), ("R$ 9,90 por mês", 4)],
)
def test_contagem_de_palavras(text: str, words: int) -> None:
    assert count_words(text) == words


def _second_scene(**overrides: str) -> VideoScriptSchema:
    """Roteiro de 2 cenas em que só a cena 1 recebe os campos alterados."""
    return make_script(cenas=[make_scene(0).model_dump(), make_scene(1, **overrides).model_dump()])


def _with_prompt(prompt: str) -> VideoScriptSchema:
    return _second_scene(prompt_video=prompt)


def test_12_palavras_cabem_em_4_segundos_13_nao() -> None:
    twelve = "um dois três quatro cinco seis sete oito nove dez onze doze"
    assert _codes(_second_scene(texto_narrado=twelve)) == set()
    assert _codes(_second_scene(texto_narrado=f"{twelve} treze")) == {(1, "TOO_MANY_WORDS")}


def test_limite_de_palavras_acompanha_a_duracao_da_cena() -> None:
    assert ScriptLimits(scene_seconds=2.5).max_words == 7
    assert ScriptLimits(scene_seconds=4.0).max_words == 12


def test_narracao_so_com_pontuacao() -> None:
    assert _codes(_second_scene(texto_narrado="...")) == {(1, "EMPTY_NARRATION")}


def test_prompt_em_portugues_e_violacao() -> None:
    prompt = "Uma mulher sorri para o celular em um apartamento com luz da manhã"
    assert (1, "PROMPT_NOT_ENGLISH") in _codes(_with_prompt(prompt))


@pytest.mark.parametrize(
    "prompt",
    [
        "A man talking directly to the camera in an office",
        "Woman speaks to the viewer with a smile, studio light",
        "Presenter with lip-synced dialogue, medium shot",
        "Close-up of a face, mouth moving, warm light",
    ],
)
def test_prompt_com_fala_para_camera(prompt: str) -> None:
    assert (1, "PROMPT_HAS_SPEECH") in _codes(_with_prompt(prompt))


@pytest.mark.parametrize(
    "prompt",
    [
        "Product shot with text overlay announcing the sale",
        "A bottle with the brand logo, soft light, macro lens",
        "A neon sign that says OPEN above a door at night",
        "Street scene with subtitles at the bottom, handheld camera",
    ],
)
def test_prompt_pedindo_texto_na_imagem(prompt: str) -> None:
    assert (1, "PROMPT_HAS_TEXT") in _codes(_with_prompt(prompt))


@pytest.mark.parametrize(
    "prompt",
    [
        PROMPT,
        "A man talking on the phone while walking in a park, golden hour, tracking shot",
        "A wooden sign on the wall of a cozy cafe, shallow depth of field",
        "The camera slowly pans across a city skyline at dusk, drone shot",
    ],
)
def test_prompts_legitimos_nao_sao_sinalizados(prompt: str) -> None:
    assert _codes(_with_prompt(prompt)) == set()


def test_contagem_de_cenas_so_quando_exigida() -> None:
    script = make_script(3)
    assert _codes(script) == set()
    assert _codes(script, ScriptLimits(expected_scenes=5)) == {(None, "SCENE_COUNT")}


def test_ensure_valid_agrega_todas_as_violacoes() -> None:
    script = _second_scene(
        texto_narrado="...", prompt_video="A woman talking to the camera with a logo behind"
    )
    with pytest.raises(ScriptValidationError) as info:
        ensure_valid(script, LIMITS)
    codes = {v.code for v in info.value.violations}
    assert codes == {"EMPTY_NARRATION", "PROMPT_HAS_SPEECH", "PROMPT_HAS_TEXT"}
    assert info.value.code == "SCRIPT_INVALID"
