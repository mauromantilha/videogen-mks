"""T-055/T-057: runner, criação/clonagem, controle (cancelar, retomar, reabrir) e recuperação."""

import asyncio
from collections.abc import Sequence
from pathlib import Path

import pytest

from tests.fakes.builders import JOB_ID, make_job, make_request
from tests.fakes.stage1 import Stage1, build_stage1
from videogen.core.config import ConfigError
from videogen.core.errors import InvalidTransition, NotFound, ValidationFailed
from videogen.domain.progress import ErrorInfo
from videogen.domain.status import JobStatus
from videogen.ports.llm import ChatMessage, LLMResult
from videogen.providers.fake.llm import FakeLLM
from videogen.services.jobs.runner import JobRunner

S = JobStatus


class HangingLLM(FakeLLM):
    async def complete(
        self, messages: Sequence[ChatMessage], *, json_mode: bool, temperature: float | None
    ) -> LLMResult:
        await asyncio.Event().wait()
        raise AssertionError("inalcançável")


class ExplodingLLM(FakeLLM):
    async def complete(self, *args: object, **kwargs: object) -> LLMResult:  # type: ignore[override]
        raise RuntimeError("bug inesperado")


def _kit_with_render(tmp_path: Path, llm: FakeLLM | None = None) -> tuple[Stage1, list[str]]:
    rendered: list[str] = []

    async def render(job_id: str) -> None:
        rendered.append(job_id)

    return build_stage1(tmp_path, llm, render=render), rendered


async def test_runner_um_trabalho_por_job_e_falha_vai_ao_callback() -> None:
    crashes: list[tuple[str, str]] = []

    async def on_crash(job_id: str, stage: str, exc: BaseException) -> None:
        crashes.append((job_id, str(exc)))

    async def boom() -> None:
        raise RuntimeError("x")

    runner = JobRunner(max_parallel=1, on_crash=on_crash)  # type: ignore[arg-type]
    gate = asyncio.Event()
    runner.submit("a", "script", gate.wait)
    with pytest.raises(InvalidTransition):
        runner.submit("a", "script", gate.wait)
    gate.set()
    await runner.join("a")
    runner.submit("a", "render", boom)
    await runner.join("a")
    assert crashes == [("a", "x")] and not runner.is_running("a")
    runner.submit("b", "script", asyncio.Event().wait)
    await runner.shutdown(grace_s=0.01)
    assert not runner.is_running("b")


async def test_criar_valida_e_gera_rascunho(tmp_path: Path) -> None:
    kit = build_stage1(tmp_path)
    state = await kit.creation.create(make_request(n_cenas=4))
    await kit.runner.join(state.job_id)
    job = await kit.repo.get(state.job_id)
    assert (job.status, len(job.require_script().cenas)) == (S.AWAITING_APPROVAL, 4)


@pytest.mark.parametrize(
    ("overrides", "error"),
    [
        ({"models": {"llm": "x", "tts": "f5-tts", "video": "wan-2.1-t2v-480p"}}, NotFound),
        (
            {"models": {"llm": "f5-tts", "tts": "f5-tts", "video": "wan-2.1-t2v-480p"}},
            ValidationFailed,
        ),
        (
            {"models": {"llm": "deepseek-flash", "tts": "f5-tts", "video": "cogvideox-5b"}},
            ValidationFailed,
        ),  # CogVideoX não faz 9:16
        ({"voice_id": "voz_ffffffffffff"}, NotFound),
    ],
)
async def test_pedido_invalido_nao_cria_job(
    tmp_path: Path, overrides: dict[str, object], error: type[Exception]
) -> None:
    kit = build_stage1(tmp_path)
    with pytest.raises(error):
        await kit.creation.create(make_request(**overrides))
    assert await kit.repo.list_all() == []


async def test_clonar(tmp_path: Path) -> None:
    kit = build_stage1(tmp_path)
    await kit.repo.create(make_job(S.COMPLETED))
    clone = await kit.creation.clone(JOB_ID)
    assert clone.job_id != JOB_ID and (clone.status, clone.script_version) == (
        S.AWAITING_APPROVAL,
        1,
    )
    assert clone.approval is None and await kit.history.versions(clone.job_id) == [1]


async def test_regenerar_pelo_runner(tmp_path: Path) -> None:
    kit = build_stage1(tmp_path)
    await kit.repo.create(make_job(S.AWAITING_APPROVAL))
    assert (
        await kit.control.request_regeneration(JOB_ID, feedback=None, scene_index=0)
    ).status is S.SCRIPTING
    await kit.runner.join(JOB_ID)
    assert (await kit.repo.get(JOB_ID)).script_version == 2


async def test_cancelar_interrompe_o_trabalho(tmp_path: Path) -> None:
    kit = build_stage1(tmp_path, HangingLLM())
    state = await kit.creation.create(make_request())
    await asyncio.sleep(0)
    assert (await kit.control.cancel(state.job_id)).status is S.CANCELED
    assert not kit.runner.is_running(state.job_id)
    with pytest.raises(InvalidTransition):
        await kit.control.cancel(state.job_id)


async def test_falha_inesperada_marca_o_job(tmp_path: Path) -> None:
    kit = build_stage1(tmp_path, ExplodingLLM())
    state = await kit.creation.create(make_request())
    await kit.runner.join(state.job_id)
    job = await kit.repo.get(state.job_id)
    assert (job.status, job.failed_stage) == (S.FAILED, "scripting")
    assert job.error is not None and job.error.code == "INTERNAL_ERROR"


async def test_retry_de_roteiro(tmp_path: Path) -> None:
    kit = build_stage1(tmp_path)
    await kit.repo.create(make_job(S.FAILED))  # falhou no rascunho, sem roteiro
    assert (await kit.control.retry(JOB_ID)).status is S.SCRIPTING
    await kit.runner.join(JOB_ID)
    assert (await kit.repo.get(JOB_ID)).status is S.AWAITING_APPROVAL


async def test_retry_de_render_reseta_so_o_que_falhou(tmp_path: Path) -> None:
    kit, rendered = _kit_with_render(tmp_path)
    job = make_job(S.RENDERING)
    job.scenes[0].video.mark_cached("a" * 64)
    job.scenes[1].video.fail(ErrorInfo(code="PROVIDER_ERROR", message="502"))
    job.fail("rendering", ErrorInfo(code="PROVIDER_ERROR", message="502"))
    await kit.repo.create(job)
    state = await kit.control.retry(JOB_ID)
    await kit.runner.join(JOB_ID)
    assert state.status is S.RENDERING and rendered == [JOB_ID]
    assert (state.scenes[0].video.status, state.scenes[1].video.status) == ("done", "pending")
    without_render = build_stage1(tmp_path)
    await without_render.repo.create(job)
    with pytest.raises(ConfigError, match="render"):
        await without_render.control.retry(JOB_ID)


async def test_reabrir(tmp_path: Path) -> None:
    kit = build_stage1(tmp_path)
    await kit.repo.create(make_job(S.COMPLETED))
    state = await kit.control.reopen(JOB_ID)
    assert (state.status, state.approval, state.scenes) == (S.AWAITING_APPROVAL, None, [])
    with pytest.raises(InvalidTransition):
        await kit.control.reopen(JOB_ID)


async def test_recuperacao_apos_restart(tmp_path: Path) -> None:
    kit, rendered = _kit_with_render(tmp_path)
    drafting = make_job(S.SCRIPTING).model_copy(update={"job_id": "job_000000000001"})
    regenerating = make_job(S.AWAITING_APPROVAL).model_copy(update={"job_id": "job_000000000002"})
    regenerating.transition_to(S.SCRIPTING)
    rendering = make_job(S.RENDERING).model_copy(update={"job_id": "job_000000000003"})
    idle = make_job(S.AWAITING_APPROVAL).model_copy(update={"job_id": "job_000000000004"})
    for job in (drafting, regenerating, rendering, idle):
        await kit.repo.create(job)
    report = await kit.recovery.resume_all()
    for job_id in ("job_000000000001", "job_000000000003"):
        await kit.runner.join(job_id)
    assert (report.drafted, report.restored, report.rendering) == (
        ["job_000000000001"],
        ["job_000000000002"],
        ["job_000000000003"],
    )
    assert rendered == ["job_000000000003"]
    assert (await kit.repo.get("job_000000000001")).status is S.AWAITING_APPROVAL
    assert (await kit.repo.get("job_000000000004")).revision == 0  # intocado
