"""T-012: máquina de estados, invariantes do job e congelamento na aprovação."""

import itertools

import pytest
from pydantic import ValidationError

from tests.fakes.builders import JOB_ID, make_job, make_scene, make_script
from tests.fakes.fake_clock import DEFAULT_START
from videogen.core.errors import InvalidTransition, VersionConflict
from videogen.domain.freeze import derive_seed, effective_seed, freeze_for_render
from videogen.domain.job import JobState
from videogen.domain.progress import ErrorInfo
from videogen.domain.status import JobStatus, can_transition

S = JobStatus
# Cópia independente do design (design.md §4): o teste falha se o código divergir.
EXPECTED = {
    (S.SCRIPTING, S.AWAITING_APPROVAL),
    (S.SCRIPTING, S.FAILED),
    (S.SCRIPTING, S.CANCELED),
    (S.AWAITING_APPROVAL, S.SCRIPTING),
    (S.AWAITING_APPROVAL, S.APPROVED),
    (S.AWAITING_APPROVAL, S.CANCELED),
    (S.APPROVED, S.RENDERING),
    (S.APPROVED, S.CANCELED),
    (S.RENDERING, S.FINALIZING),
    (S.RENDERING, S.FAILED),
    (S.RENDERING, S.CANCELED),
    (S.FINALIZING, S.COMPLETED),
    (S.FINALIZING, S.FAILED),
    (S.FINALIZING, S.CANCELED),
    (S.FAILED, S.AWAITING_APPROVAL),
    (S.FAILED, S.CANCELED),
    (S.COMPLETED, S.AWAITING_APPROVAL),
}
RETRY = {
    "scripting": {S.SCRIPTING},
    "rendering": {S.RENDERING},
    "finalizing": {S.RENDERING},
}
ERROR = ErrorInfo(code="PROVIDER_ERROR", message="falhou")


@pytest.mark.parametrize(("source", "target"), list(itertools.product(S, S)))
def test_tabela_de_transicoes_completa(source: JobStatus, target: JobStatus) -> None:
    if source is S.FAILED:
        for stage, retry_targets in RETRY.items():
            expected = (source, target) in EXPECTED or target in retry_targets
            assert can_transition(source, target, stage) is expected, stage  # type: ignore[arg-type]
    else:
        assert can_transition(source, target) is ((source, target) in EXPECTED)


def test_cancelado_e_terminal() -> None:
    assert not any(can_transition(S.CANCELED, target) for target in S)


@pytest.mark.parametrize("status", list(S))
def test_builder_produz_estados_validos(status: JobStatus) -> None:
    assert make_job(status).status is status


def test_failed_exige_etapa_e_vice_versa() -> None:
    data = make_job(S.SCRIPTING).model_dump()
    with pytest.raises(ValidationError, match="failed_stage"):
        JobState.model_validate(data | {"status": S.FAILED})
    with pytest.raises(ValidationError, match="failed_stage"):
        JobState.model_validate(data | {"failed_stage": "rendering"})


def test_aguardando_aprovacao_exige_roteiro() -> None:
    data = make_job(S.SCRIPTING).model_dump() | {"status": S.AWAITING_APPROVAL}
    with pytest.raises(ValidationError, match="awaiting_approval"):
        JobState.model_validate(data)


def test_render_exige_roteiro_aprovado_e_progresso_por_cena() -> None:
    data = make_job(S.RENDERING).model_dump()
    with pytest.raises(ValidationError, match="aprovado"):
        JobState.model_validate(data | {"approval": None})
    with pytest.raises(ValidationError, match="uma entrada por cena"):
        JobState.model_validate(data | {"scenes": data["scenes"][:-1]})
    with pytest.raises(ValidationError, match="versão aprovada"):
        JobState.model_validate(data | {"script_version": 2})


def test_fail_e_retry_limpam_o_erro() -> None:
    job = make_job(S.RENDERING)
    job.fail("rendering", ERROR)
    assert (job.status, job.failed_stage, job.error) == (S.FAILED, "rendering", ERROR)
    with pytest.raises(InvalidTransition):
        job.transition_to(S.SCRIPTING)
    job.transition_to(S.RENDERING)
    assert (job.failed_stage, job.error) == (None, None)


def test_ensure_status() -> None:
    job = make_job(S.RENDERING)
    job.ensure_status(S.RENDERING, S.FINALIZING)
    with pytest.raises(InvalidTransition, match="awaiting_approval"):
        job.ensure_status(S.AWAITING_APPROVAL)


def test_seed_derivada_e_deterministica_e_respeita_a_existente() -> None:
    assert derive_seed(JOB_ID, 0) == derive_seed(JOB_ID, 0)
    assert derive_seed(JOB_ID, 0) != derive_seed(JOB_ID, 1)
    assert effective_seed(JOB_ID, make_scene(0, seed=7)) == 7


def test_aprovacao_congela_roteiro() -> None:
    job = make_job(S.AWAITING_APPROVAL)
    job.script = make_script(3).with_scenes([make_scene(0, seed=7), make_scene(1), make_scene(2)])

    freeze_for_render(job, script_version=1, max_budget_usd=1.5, now=DEFAULT_START)

    script = job.require_script()
    assert [scene.seed for scene in script.cenas] == [
        7,
        derive_seed(JOB_ID, 1),
        derive_seed(JOB_ID, 2),
    ]
    assert [progress.scene_index for progress in job.scenes] == [0, 1, 2]
    assert job.approval is not None and job.approval.max_budget_usd == 1.5
    assert job.status is S.APPROVED and job.is_frozen
    JobState.model_validate(job.model_dump())


def test_aprovacao_com_versao_desatualizada() -> None:
    job = make_job(S.AWAITING_APPROVAL)
    with pytest.raises(VersionConflict) as info:
        freeze_for_render(job, script_version=0, max_budget_usd=1.0, now=DEFAULT_START)
    assert info.value.context["current_version"] == 1
    assert job.status is S.AWAITING_APPROVAL and job.approval is None


def test_aprovacao_fora_de_awaiting_approval() -> None:
    with pytest.raises(InvalidTransition):
        freeze_for_render(
            make_job(S.RENDERING), script_version=1, max_budget_usd=1.0, now=DEFAULT_START
        )
