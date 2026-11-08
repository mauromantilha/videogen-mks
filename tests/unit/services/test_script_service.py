"""T-052: rascunho e regeneração do roteiro em segundo plano."""

from pathlib import Path

import pytest

from tests.fakes.builders import JOB_ID, make_job, make_request
from tests.fakes.fake_clock import DEFAULT_START
from tests.fakes.stage1 import Stage1, build_stage1
from videogen.core.errors import InvalidTransition, ProviderError
from videogen.domain.job import JobState
from videogen.domain.status import JobStatus
from videogen.providers.fake.llm import FakeLLM


async def _new_job(kit: Stage1) -> None:
    await kit.repo.create(JobState.new(JOB_ID, make_request(), DEFAULT_START))


async def _regenerating(kit: Stage1) -> JobState:
    job = make_job(JobStatus.AWAITING_APPROVAL)
    job.transition_to(JobStatus.SCRIPTING)
    return await kit.repo.create(job)


async def test_rascunho_vai_para_revisao(tmp_path: Path) -> None:
    kit = build_stage1(tmp_path)
    await _new_job(kit)
    state = await kit.script.draft(JOB_ID)
    assert (state.status, state.script_version, state.error) == (
        JobStatus.AWAITING_APPROVAL,
        1,
        None,
    )
    assert len(state.require_script().cenas) == 3
    assert await kit.history.versions(JOB_ID) == [1]
    assert kit.bus.types(JOB_ID) == ["script.updated", "job.status"]
    assert "Gere exatamente 3 cenas" in kit.llm.calls[0][1].content


async def test_rascunho_invalido_falha_em_scripting(tmp_path: Path) -> None:
    kit = build_stage1(tmp_path, FakeLLM(["lixo"] * 3))
    await _new_job(kit)
    state = await kit.script.draft(JOB_ID)
    assert (state.status, state.failed_stage) == (JobStatus.FAILED, "scripting")
    assert state.error is not None and state.error.code == "SCRIPT_INVALID"
    assert kit.bus.types(JOB_ID) == ["job.failed", "job.status"]


class BrokenLLM(FakeLLM):
    async def complete(self, *args: object, **kwargs: object) -> object:  # type: ignore[override]
        raise ProviderError("deepseek: 503", retryable=True)


async def test_erro_do_provedor_falha_o_job_com_o_codigo(tmp_path: Path) -> None:
    kit = build_stage1(tmp_path, BrokenLLM())
    await _new_job(kit)
    state = await kit.script.draft(JOB_ID)
    assert state.error is not None and state.error.code == "PROVIDER_ERROR"


async def test_regenerar_tudo_com_feedback(tmp_path: Path) -> None:
    kit = build_stage1(tmp_path)
    await _regenerating(kit)
    state = await kit.script.regenerate(JOB_ID, feedback="tom mais jovem")
    assert (state.status, state.script_version) == (JobStatus.AWAITING_APPROVAL, 2)
    assert "tom mais jovem" in kit.llm.calls[0][1].content


async def test_regenerar_uma_cena_preserva_as_outras(tmp_path: Path) -> None:
    kit = build_stage1(tmp_path)
    before = (await _regenerating(kit)).require_script()
    after = (await kit.script.regenerate(JOB_ID, scene_index=1)).require_script()
    assert after.cenas[0] == before.cenas[0] and after.cenas[2] == before.cenas[2]
    assert after.cenas[1].texto_narrado != before.cenas[1].texto_narrado
    assert after.estilo_visual == before.estilo_visual


async def test_regeneracao_que_falha_mantem_o_roteiro_anterior(tmp_path: Path) -> None:
    kit = build_stage1(tmp_path, FakeLLM(["lixo"] * 3))
    before = await _regenerating(kit)
    state = await kit.script.regenerate(JOB_ID)
    assert (state.status, state.script, state.script_version) == (
        JobStatus.AWAITING_APPROVAL,
        before.script,
        1,
    )
    assert state.error is not None and state.error.code == "SCRIPT_INVALID"


async def test_regeneracao_exige_estado_e_cena_validos(tmp_path: Path) -> None:
    kit = build_stage1(tmp_path)
    await kit.repo.create(make_job(JobStatus.AWAITING_APPROVAL))
    with pytest.raises(InvalidTransition):
        await kit.script.regenerate(JOB_ID)
    await kit.repo.update(JOB_ID, lambda s: s.transition_to(JobStatus.SCRIPTING))
    with pytest.raises(InvalidTransition, match="cena 7"):
        await kit.script.regenerate(JOB_ID, scene_index=7)
