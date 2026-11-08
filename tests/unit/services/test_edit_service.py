"""T-053: edição manual — versão otimista, transformações e nenhum custo."""

from pathlib import Path

import pytest

from tests.fakes.builders import JOB_ID, PROMPT, make_job, make_script
from tests.fakes.stage1 import Stage1, build_stage1
from videogen.core.errors import InvalidTransition, ValidationFailed, VersionConflict
from videogen.domain.status import JobStatus


@pytest.fixture
async def kit(tmp_path: Path) -> Stage1:
    built = build_stage1(tmp_path)
    await built.repo.create(make_job(JobStatus.AWAITING_APPROVAL))
    return built


async def _texts(kit: Stage1) -> list[str]:
    return [s.texto_narrado for s in (await kit.repo.get(JOB_ID)).require_script().cenas]


async def test_editar_narracao_incrementa_versao_e_registra(kit: Stage1) -> None:
    result = await kit.edits.patch_scene(JOB_ID, 1, {"texto_narrado": "Nova fala curta."}, 1)
    assert (result.state.script_version, result.violations) == (2, [])
    assert (await _texts(kit))[1] == "Nova fala curta."
    assert await kit.history.versions(JOB_ID) == [2]
    assert kit.bus.types(JOB_ID) == ["script.updated"]
    assert kit.llm.calls == []  # edição manual nunca chama o LLM


async def test_violacao_de_regra_e_salva_e_devolvida(kit: Stage1) -> None:
    long_text = " ".join(["palavra"] * 13)
    result = await kit.edits.patch_scene(JOB_ID, 0, {"texto_narrado": long_text}, 1)
    assert [(v.scene_index, v.code) for v in result.violations] == [(0, "TOO_MANY_WORDS")]
    assert (await _texts(kit))[0] == long_text


async def test_versao_desatualizada(kit: Stage1) -> None:
    await kit.edits.patch_scene(JOB_ID, 0, {"texto_narrado": "Primeira edição."}, 1)
    with pytest.raises(VersionConflict) as info:
        await kit.edits.patch_scene(JOB_ID, 0, {"texto_narrado": "Atrasada."}, 1)
    assert info.value.context["current_version"] == 2
    assert (await _texts(kit))[0] == "Primeira edição."


@pytest.mark.parametrize(
    "fields", [{"scene_index": 9}, {"prompt_video": "curto"}, {"texto_narrado": ""}]
)
async def test_erros_de_estrutura_nao_sao_salvos(kit: Stage1, fields: dict[str, object]) -> None:
    with pytest.raises(ValidationFailed):
        await kit.edits.patch_scene(JOB_ID, 0, fields, 1)
    assert (await kit.repo.get(JOB_ID)).script_version == 1


async def test_adicionar_remover_mover(kit: Stage1) -> None:
    scene = {"texto_narrado": "Cena extra.", "prompt_video": PROMPT}
    await kit.edits.add_scene(JOB_ID, 0, scene, 1)
    assert (await _texts(kit))[1] == "Cena extra."
    await kit.edits.move_scene(JOB_ID, 1, 3, 2)
    assert (await _texts(kit))[3] == "Cena extra."
    await kit.edits.remove_scene(JOB_ID, 3, 3)
    script = (await kit.repo.get(JOB_ID)).require_script()
    assert [s.scene_index for s in script.cenas] == [0, 1, 2]
    await kit.edits.remove_scene(JOB_ID, 0, 4)
    with pytest.raises(ValidationFailed):  # abaixo do mínimo de 2 cenas
        await kit.edits.remove_scene(JOB_ID, 0, 5)
    with pytest.raises(ValidationFailed, match="não existe"):
        await kit.edits.move_scene(JOB_ID, 0, 9, 5)


async def test_outra_versao_muda_so_a_seed_da_cena(kit: Stage1) -> None:
    first = (await kit.edits.bump_seed(JOB_ID, 1, 1)).state.require_script()
    second = (await kit.edits.bump_seed(JOB_ID, 1, 2)).state.require_script()
    assert first.cenas[1].seed is not None and first.cenas[1].seed != second.cenas[1].seed
    assert (
        first.cenas[0].seed is None
        and first.cenas[1].texto_narrado == second.cenas[1].texto_narrado
    )


async def test_substituir_roteiro_exige_mesma_proporcao(kit: Stage1) -> None:
    await kit.edits.replace_script(JOB_ID, make_script(4), 1)
    assert len(await _texts(kit)) == 4
    with pytest.raises(ValidationFailed, match="proporção"):
        await kit.edits.replace_script(JOB_ID, make_script(3, aspect_ratio="16:9"), 2)


async def test_campos_nao_editaveis_e_estado_errado(kit: Stage1) -> None:
    with pytest.raises(ValidationFailed, match="não editáveis"):
        await kit.edits.patch_scene(JOB_ID, 0, {"scene_index": 2, "musica": "x"}, 1)
    await kit.repo.update(JOB_ID, lambda s: s.transition_to(JobStatus.SCRIPTING))
    with pytest.raises(InvalidTransition):
        await kit.edits.patch_scene(JOB_ID, 0, {"texto_narrado": "x y"}, 1)
