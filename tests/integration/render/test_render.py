"""T-071…T-078 com FFmpeg real e provedores fake: render completo, idempotência, falha
parcial + retry (AC-03), retomada por remote_id (AC-04), cancelamento e paralelismo."""

import asyncio
from pathlib import Path

import pytest

from tests.fakes.builders import JOB_ID, PROMPT
from tests.fakes.media_factory import PROBE
from tests.fakes.stage2 import Stage2, build_stage2
from videogen.domain.media import ArtifactKind
from videogen.domain.status import JobStatus

pytestmark = pytest.mark.ffmpeg
BROKEN = f"{PROMPT} CENA-QUEBRADA"


def _steps(job: object) -> list[tuple[str, str, str]]:
    return [(s.audio.status, s.video.status, s.clip.status) for s in job.scenes]  # type: ignore[attr-defined]


@pytest.fixture
def kit(tmp_path: Path) -> Stage2:
    return build_stage2(tmp_path)


async def test_render_completo_gera_o_mp4_final(kit: Stage2) -> None:
    await kit.approved_job(n=3)
    job = await kit.render()
    assert job.status is JobStatus.COMPLETED and job.final_hash is not None
    assert _steps(job) == [("done", "done", "done")] * 3
    final = kit.cache.get(ArtifactKind.FINAL, job.final_hash)
    assert final is not None
    info = await PROBE.validate(final, ArtifactKind.FINAL)
    clips = [kit.cache.get(ArtifactKind.CLIP, s.clip.artifact_hash or "") for s in job.scenes]
    expected = sum([(await PROBE.probe(c)).duration_s for c in clips if c])
    assert info.duration_s == pytest.approx(expected, abs=0.2)
    assert (info.width, info.height) == (480, 854)  # 480p vertical
    types = kit.bus.types(JOB_ID)
    assert types[0] == "job.status" and types[-2:] == ["job.status", "job.completed"]
    assert types.count("scene.step") >= 9


async def test_mesma_narracao_paga_um_tts_e_seeds_distintas_geram_videos(kit: Stage2) -> None:
    await kit.approved_job(n=3)  # as 3 cenas têm a mesma narração (builders)
    await kit.render()
    assert kit.behavior.submit_count("fake-tts") == 1  # single-flight + cache
    assert kit.behavior.submit_count("fake-t2v") == 3  # seed diferente por cena


async def test_renderizar_de_novo_nao_paga_nada(kit: Stage2) -> None:
    await kit.approved_job(n=2)
    await kit.render()
    before = len(kit.behavior.submits)
    await kit.repo.update(JOB_ID, _back_to_approved)
    job = await kit.render()
    assert job.status is JobStatus.COMPLETED and len(kit.behavior.submits) == before
    assert all(s.video.cached and s.clip.cached for s in job.scenes)


def _back_to_approved(state: object) -> None:
    """Simula reabrir e reaprovar o mesmo roteiro (mesmos hashes)."""
    from videogen.domain.progress import SceneProgress

    state.status = JobStatus.APPROVED  # type: ignore[attr-defined]
    state.final_hash = None  # type: ignore[attr-defined]
    state.scenes = [SceneProgress(scene_index=s.scene_index) for s in state.scenes]  # type: ignore[attr-defined]


async def test_falha_parcial_preserva_o_pago_e_retry_refaz_so_a_cena(kit: Stage2) -> None:
    await kit.approved_job(n=3, p1=BROKEN)
    kit.behavior.fail_when("CENA-QUEBRADA", times=99, retryable=False)
    job = await kit.render()
    assert (job.status, job.failed_stage) == (JobStatus.FAILED, "rendering")
    assert _steps(job) == [
        ("done", "done", "done"),
        ("done", "failed", "pending"),
        ("done", "done", "done"),
    ]
    assert job.error is not None and "falha injetada" in job.error.message
    videos_before = kit.behavior.submit_count("fake-t2v")

    kit.behavior.rules.clear()
    await kit.control.retry(JOB_ID)
    await kit.runner.join(JOB_ID)
    job = await kit.repo.get(JOB_ID)
    assert job.status is JobStatus.COMPLETED
    assert kit.behavior.submit_count("fake-t2v") == videos_before + 1  # só a cena 1


async def test_retomada_por_remote_id_nao_reenvia(kit: Stage2) -> None:
    await kit.approved_job(n=2)

    def crashed_after_submit(state: object) -> None:
        state.scenes[0].video.remote_id = "fake-t2v-anterior"  # type: ignore[attr-defined]

    await kit.repo.update(JOB_ID, crashed_after_submit)
    job = await kit.render()
    assert job.status is JobStatus.COMPLETED
    assert kit.behavior.submit_count("fake-t2v") == 1  # só a cena 1; a 0 foi retomada
    assert "fake-t2v-anterior" not in kit.behavior.submits


async def test_cancelar_durante_o_render_cancela_predicoes(kit: Stage2) -> None:
    await kit.approved_job(n=2)
    kit.behavior.latency_s = 30
    kit.runner.submit(JOB_ID, "render", lambda: kit.coordinator.run(JOB_ID))
    for _ in range(100):
        if kit.behavior.active:
            break
        await asyncio.sleep(0.01)
    assert (await kit.control.cancel(JOB_ID)).status is JobStatus.CANCELED
    assert not kit.runner.is_running(JOB_ID)
    assert kit.behavior.cancels and set(kit.behavior.cancels) <= set(kit.behavior.submits)


async def test_cenas_rodam_em_paralelo_respeitando_o_limite(tmp_path: Path) -> None:
    prompts = {f"p{i}": f"{PROMPT}, variation {i}" for i in range(3)}
    free = build_stage2(tmp_path / "livre")
    await free.approved_job(n=3, **prompts)
    free.behavior.latency_s = 0.2
    await free.render()
    assert free.behavior.peak >= 4  # 1 TTS (dedup) + 3 vídeos ao mesmo tempo

    capped = build_stage2(tmp_path / "limitado", max_parallel_video=2)
    await capped.approved_job(n=3, **prompts)
    capped.behavior.latency_s = 0.2
    await capped.render()
    assert capped.behavior.peak <= 3  # 2 vídeos + 1 TTS
