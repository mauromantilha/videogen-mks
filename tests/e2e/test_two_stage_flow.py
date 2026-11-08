"""T-090/T-091 (AC-01, AC-02, AC-03): os dois estágios pela API, com o app real em modo fake."""

from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest

from tests.fakes.api_app import ApiHarness, running_api
from tests.fakes.media_factory import PROBE, RUNNER
from videogen.composer.loudnorm import LoudnessNormalizer
from videogen.domain.render_specs import LoudnessParams
from videogen.providers.fake.behavior import FakeBehavior

pytestmark = [pytest.mark.ffmpeg, pytest.mark.e2e]


@pytest.fixture
async def api(tmp_path: Path) -> AsyncIterator[ApiHarness]:
    async with running_api(tmp_path) as harness:
        yield harness


def _behavior(api: ApiHarness) -> FakeBehavior:
    return api.container.providers.context.fake_behavior


async def _call(api: ApiHarness, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
    response = await api.client.request(method, f"/api/v1/jobs{path}", **kwargs)
    assert response.status_code < 300, response.text
    data: dict[str, Any] = response.json()
    return data


async def _draft(api: ApiHarness) -> str:
    job_id: str = (await _call(api, "POST", "", json=api.job_body()))["job_id"]
    assert (await api.settle(job_id))["status"] == "awaiting_approval"
    return job_id


async def _approve(api: ApiHarness, job_id: str, version: int) -> dict[str, Any]:
    await _call(api, "POST", f"/{job_id}/approve", json={"script_version": version})
    return await api.settle(job_id)


async def test_ac01_tema_ate_o_mp4_e_ac02_reedicao_paga_so_o_delta(
    api: ApiHarness, tmp_path: Path
) -> None:
    job_id = await _draft(api)
    done = await _approve(api, job_id, 1)
    assert done["status"] == "completed" and done["links"]["final"].endswith("/artifacts/final")

    final = tmp_path / "final.mp4"
    final.write_bytes((await api.client.get(done["links"]["final"])).content)
    info = await PROBE.probe(final)
    assert (info.width, info.height, info.video_codec, info.audio_codec) == (
        480,
        854,
        "h264",
        "aac",
    )
    loudness = await LoudnessNormalizer(RUNNER).measure(final, LoudnessParams())
    assert loudness.integrated == pytest.approx(-14, abs=1)  # AC-01: -14 ± 1 LUFS no MP4 final

    behavior = _behavior(api)
    tts_before, video_before = behavior.submit_count("fake-tts"), behavior.submit_count("fake-t2v")
    await _call(api, "POST", f"/{job_id}/reopen")
    edited = await _call(
        api,
        "PATCH",
        f"/{job_id}/script/scenes/1",
        json={"expected_version": 1, "texto_narrado": "Uma fala nova e curta."},
    )
    estimate = await _call(api, "GET", f"/{job_id}/estimate")
    assert [s["cached"] for s in estimate["scenes"]] == [True, False, True]
    assert estimate["total_usd"] == pytest.approx(0.01)  # só o TTS da cena 1

    again = await _approve(api, job_id, edited["script_version"])
    assert again["status"] == "completed" and again["links"]["final"]
    assert behavior.submit_count("fake-tts") == tts_before + 1
    assert behavior.submit_count("fake-t2v") == video_before  # o vídeo não mudou: cache
    assert [s["clip"]["cached"] for s in again["scenes"]] == [True, False, True]


async def test_ac03_falha_parcial_e_retry_pela_api(api: ApiHarness) -> None:
    job_id = await _draft(api)
    broken = "A storm over the city at night, lightning, wide shot FALHA-INJETADA"
    await _call(
        api,
        "PATCH",
        f"/{job_id}/script/scenes/2",
        json={"expected_version": 1, "prompt_video": broken},
    )
    behavior = _behavior(api)
    behavior.fail_when("FALHA-INJETADA", times=99, retryable=False)

    failed = await _approve(api, job_id, 2)
    assert (failed["status"], failed["failed_stage"]) == ("failed", "rendering")
    statuses = [(s["audio"]["status"], s["video"]["status"]) for s in failed["scenes"]]
    assert statuses == [("done", "done"), ("done", "done"), ("done", "failed")]
    assert failed["error"]["code"] == "PROVIDER_ERROR"

    behavior.rules.clear()
    videos_before = behavior.submit_count("fake-t2v")
    await _call(api, "POST", f"/{job_id}/retry")
    recovered = await api.settle(job_id)
    assert recovered["status"] == "completed"
    assert behavior.submit_count("fake-t2v") == videos_before + 1  # só a cena 2
