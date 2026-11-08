"""T-092 (AC-04): processo cai no meio do render; o novo processo retoma sem reenviar nada.

Dois containers reais sobre o mesmo workspace em disco: o primeiro é derrubado com todas as
predições em voo (remote_id já gravado); o segundo sobe, recupera e termina o vídeo.
"""

import asyncio
from pathlib import Path

import pytest

from tests.fakes.api_app import fake_settings
from tests.fakes.builders import make_request
from videogen.app.container import Container, build_container
from videogen.domain.status import JobStatus
from videogen.providers.fake.media import sine_wav

pytestmark = [pytest.mark.ffmpeg, pytest.mark.e2e]


async def _started(workspace: Path) -> Container:
    container = build_container(fake_settings(workspace))
    await container.startup()
    return container


async def test_ac04_restart_retoma_predicoes_sem_novo_envio(tmp_path: Path) -> None:
    first = await _started(tmp_path)
    voice = await first.infra.voice_store.save(sine_wav(6), name="v", ref_text="Olá.", duration_s=6)
    state = await first.services.creation.create(make_request(voice_id=voice.voice_id))
    await first.services.runner.join(state.job_id)

    behavior = first.providers.context.fake_behavior
    behavior.latency_s = 60  # as predições "ficam na GPU"
    await first.services.approval.approve(state.job_id, script_version=1)
    for _ in range(200):
        if behavior.active >= 6:  # 3 TTS + 3 vídeos em voo
            break
        await asyncio.sleep(0.01)
    await first.shutdown(grace_s=0.05)  # "queda" do processo

    crashed = await first.infra.repo.get(state.job_id)
    assert crashed.status is JobStatus.RENDERING
    assert all(s.audio.remote_id and s.video.remote_id for s in crashed.scenes)

    second = await _started(tmp_path)  # novo processo: o startup roda a recuperação
    try:
        await second.services.runner.join(state.job_id)
        job = await second.infra.repo.get(state.job_id)
        assert job.status is JobStatus.COMPLETED and job.final_hash
        assert second.providers.context.fake_behavior.submits == []  # nada reenviado
    finally:
        await second.shutdown(grace_s=1)
