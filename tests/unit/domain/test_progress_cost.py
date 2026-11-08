"""T-013: progresso por etapa, custo e serialização estável do JobState."""

import pytest

from tests.fakes.builders import make_job
from videogen.core.errors import ProviderTimeout
from videogen.domain.cost import CostEstimate, CostLedger, SceneEstimate
from videogen.domain.job import JobState
from videogen.domain.progress import ErrorInfo, SceneProgress, StepState, StepStatus
from videogen.domain.status import JobStatus

ERROR = ErrorInfo(code="PROVIDER_ERROR", message="502")


def test_ciclo_de_vida_de_uma_etapa() -> None:
    step = StepState()
    step.start()
    step.remote_id = "pred-1"
    step.fail(ERROR)
    assert (step.status, step.attempts, step.error) == (StepStatus.FAILED, 1, ERROR)

    step.reset_failed()
    assert (step.status, step.error, step.remote_id) == (StepStatus.PENDING, None, "pred-1")

    step.start()
    step.finish("h" * 64, cost_usd=0.09)
    assert (step.status, step.attempts, step.cost_usd, step.cached) == (
        StepStatus.DONE,
        2,
        0.09,
        False,
    )


def test_reset_nao_mexe_em_etapa_concluida() -> None:
    step = StepState()
    step.mark_cached("h" * 64)
    step.reset_failed()
    assert step.status is StepStatus.DONE and step.cached


def test_progresso_da_cena() -> None:
    scene = SceneProgress(scene_index=0)
    assert not scene.done and not scene.failed
    for name in ("audio", "video", "clip"):
        scene.step(name).mark_cached(name)
    assert scene.done
    scene.clip.fail(ERROR)
    assert scene.failed and not scene.done


def test_ledger() -> None:
    ledger = CostLedger()
    ledger.add("llm", 0.002)
    ledger.add("video", 0.09)
    ledger.add("tts", 0.003)
    assert ledger.total == pytest.approx(0.095)
    with pytest.raises(ValueError, match="negativo"):
        ledger.add("tts", -1)


def test_estimativa_soma_so_o_que_falta_gerar() -> None:
    scenes = [
        SceneEstimate(scene_index=0, tts_usd=0.0, video_usd=0.0, cached=True),
        SceneEstimate(scene_index=1, tts_usd=0.003, video_usd=0.09, cached=False),
        SceneEstimate(scene_index=2, tts_usd=0.003, video_usd=0.09, cached=False),
    ]
    estimate = CostEstimate.from_scenes(scenes, spent_usd=0.002)
    assert estimate.total_usd == pytest.approx(0.186)
    assert estimate.spent_usd == 0.002


def test_error_info_de_erro_de_dominio_e_de_erro_inesperado() -> None:
    assert ErrorInfo.from_exception(ProviderTimeout("lento")) == ErrorInfo(
        code="PROVIDER_TIMEOUT", message="lento", retryable=True
    )
    unexpected = ErrorInfo.from_exception(KeyError("segredo-interno"))
    assert unexpected.code == "INTERNAL_ERROR"
    assert "segredo" not in unexpected.message


@pytest.mark.parametrize("status", list(JobStatus))
def test_job_sobrevive_ida_e_volta_em_json(status: JobStatus) -> None:
    job = make_job(status)
    job.ledger.add("llm", 0.002)
    if job.scenes:
        job.scenes[0].video.remote_id = "pred-1"
    restored = JobState.model_validate_json(job.model_dump_json())
    assert restored == job
