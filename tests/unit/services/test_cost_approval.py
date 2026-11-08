"""T-054/T-056: estimativa com desconto de cache, orçamento e portão de aprovação."""

import asyncio
from pathlib import Path

import pytest

from tests.fakes.builders import JOB_ID, make_job
from tests.fakes.memory_voices import DEFAULT_VOICE
from tests.fakes.stage1 import CATALOG, Stage1, build_stage1
from videogen.core.errors import BudgetExceeded, InvalidTransition, VersionConflict
from videogen.domain.freeze import derive_seed
from videogen.domain.hashing import audio_hash, video_hash
from videogen.domain.media import ArtifactKind
from videogen.domain.render_plan import tts_request, video_request
from videogen.domain.script_rules import ScriptValidationError
from videogen.domain.status import JobStatus
from videogen.services.cost.budget import allows_new_attempt, ensure_within


@pytest.fixture
async def kit(tmp_path: Path) -> Stage1:
    rendered: list[str] = []

    async def render(job_id: str) -> None:
        rendered.append(job_id)

    built = build_stage1(tmp_path, render=render)
    built.rendered = rendered  # type: ignore[attr-defined]
    await built.repo.create(make_job(JobStatus.AWAITING_APPROVAL))
    return built


async def test_estimativa_sem_cache(kit: Stage1) -> None:
    await kit.repo.update(JOB_ID, lambda s: s.ledger.add("llm", 0.003))
    estimate = await kit.approval.estimate(JOB_ID)
    assert [(s.tts_usd, s.video_usd, s.cached) for s in estimate.scenes] == [
        (0.01, 0.09, False)
    ] * 3
    assert (estimate.total_usd, estimate.spent_usd) == (pytest.approx(0.3), 0.003)


async def test_cena_em_cache_custa_zero(kit: Stage1) -> None:
    job = await kit.repo.get(JOB_ID)
    script, scene = job.require_script(), job.require_script().cenas[0]
    request = video_request(JOB_ID, scene, script, CATALOG.get("wan-2.1-t2v-480p", "t2v"), "9:16")
    kit.cache.put(ArtifactKind.VIDEO_RAW, video_hash(request))
    tts = tts_request(scene, CATALOG.get("f5-tts", "tts"), DEFAULT_VOICE)
    kit.cache.put(ArtifactKind.AUDIO_RAW, audio_hash(tts))
    estimate = await kit.approval.estimate(JOB_ID)
    assert [s.cached for s in estimate.scenes] == [True, False, False]
    # As 3 cenas têm a mesma narração: o áudio em cache serve para todas (mesmo hash);
    # só os vídeos das cenas 1 e 2 são cobrados.
    assert [s.tts_usd for s in estimate.scenes] == [0.0, 0.0, 0.0]
    assert estimate.total_usd == pytest.approx(0.18)


def test_regras_de_orcamento() -> None:
    ensure_within(0.3, 0.3)
    with pytest.raises(BudgetExceeded):
        ensure_within(0.31, 0.3)
    assert allows_new_attempt(0.29, 0.3) and not allows_new_attempt(0.3, 0.3)


async def test_aprovar_congela_e_dispara_o_render_uma_vez(kit: Stage1) -> None:
    state = await kit.approval.approve(JOB_ID, script_version=1, max_budget_usd=1.0)
    await kit.runner.join(JOB_ID)
    assert state.status is JobStatus.APPROVED and state.approval is not None
    assert state.approval.max_budget_usd == 1.0
    assert state.require_script().cenas[2].seed == derive_seed(JOB_ID, 2)
    assert kit.rendered == [JOB_ID]  # type: ignore[attr-defined]
    assert kit.bus.types(JOB_ID) == ["job.status"]


async def test_versao_errada_nao_muda_nada(kit: Stage1) -> None:
    with pytest.raises(VersionConflict):
        await kit.approval.approve(JOB_ID, script_version=0)
    job = await kit.repo.get(JOB_ID)
    assert (job.status, job.revision, kit.rendered) == (JobStatus.AWAITING_APPROVAL, 0, [])  # type: ignore[attr-defined]


async def test_orcamento_insuficiente(kit: Stage1) -> None:
    with pytest.raises(BudgetExceeded) as info:
        await kit.approval.approve(JOB_ID, script_version=1, max_budget_usd=0.2)
    assert info.value.context["estimated_usd"] == pytest.approx(0.3)
    assert (await kit.repo.get(JOB_ID)).status is JobStatus.AWAITING_APPROVAL


async def test_roteiro_com_violacao_nao_e_aprovado(kit: Stage1) -> None:
    await kit.edits.patch_scene(JOB_ID, 0, {"texto_narrado": " ".join(["x"] * 13)}, 1)
    with pytest.raises(ScriptValidationError):
        await kit.approval.approve(JOB_ID, script_version=2)


async def test_aprovacoes_concorrentes_so_uma_vence(kit: Stage1) -> None:
    results = await asyncio.gather(
        *(kit.approval.approve(JOB_ID, script_version=1) for _ in range(3)), return_exceptions=True
    )
    await kit.runner.join(JOB_ID)
    failures = [r for r in results if isinstance(r, Exception)]
    assert len(failures) == 2
    assert all(isinstance(f, VersionConflict | InvalidTransition) for f in failures)
    assert kit.rendered == [JOB_ID]  # type: ignore[attr-defined]
