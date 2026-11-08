"""T-093: smoke com provedores REAIS (gera custo). Desligado por padrão.

    RUN_LIVE=1 LIVE_VOICE_FILE=minha-voz.wav LIVE_VOICE_TEXT="transcrição exata" \
        .venv/bin/pytest tests/live -s

Usa o `.env` (chaves e PROVIDER_MODE=real). Teto: US$ 0,50 (2 cenas, 480p). O MP4 final é
copiado para `workspace/live-smoke/`.
"""

import os
import shutil
from pathlib import Path

import pytest

from videogen.app.container import build_container
from videogen.core.config import Settings, load_settings
from videogen.domain.media import ArtifactKind
from videogen.domain.request import JobRequest, ModelChoice
from videogen.domain.status import JobStatus

pytestmark = [pytest.mark.live, pytest.mark.ffmpeg]
MAX_BUDGET_USD = 0.50
OUTPUT_DIR = Path("workspace/live-smoke")


def _settings(workspace: Path) -> Settings:
    settings = load_settings()
    if settings.providers.provider_mode != "real":
        pytest.skip("o smoke live exige PROVIDER_MODE=real no .env")
    app = settings.app.model_copy(update={"workspace_dir": workspace})
    return Settings(app=app, providers=settings.providers, render=settings.render)


async def test_smoke_real_tema_ate_mp4(tmp_path: Path) -> None:
    voice_file, voice_text = os.environ.get("LIVE_VOICE_FILE"), os.environ.get("LIVE_VOICE_TEXT")
    if not voice_file or not voice_text:
        pytest.skip("defina LIVE_VOICE_FILE e LIVE_VOICE_TEXT (voz real de 3 a 12 s)")
    container = build_container(_settings(tmp_path))
    await container.startup()
    services, repo = container.services, container.infra.repo
    try:
        voice = await services.voices.register(Path(voice_file).read_bytes(), filename=voice_file,
                                               name="smoke", ref_text=voice_text)  # fmt: skip
        request = JobRequest(
            tema="Seguro de vida para jovens profissionais", n_cenas=2, voice_id=voice.voice_id,
            models=ModelChoice(llm="deepseek-flash", tts="f5-tts", video="wan-2.1-t2v-480p"),
            max_budget_usd=MAX_BUDGET_USD,
        )  # fmt: skip
        job = await services.creation.create(request)
        await services.runner.join(job.job_id)
        drafted = await repo.get(job.job_id)
        assert drafted.status is JobStatus.AWAITING_APPROVAL, drafted.error
        estimate = await services.approval.estimate(job.job_id)
        print(f"\nroteiro: {drafted.require_script().model_dump_json(indent=1)}")
        print(f"estimativa: US$ {estimate.total_usd:.3f} (+ LLM US$ {drafted.ledger.llm_usd:.4f})")
        assert estimate.total_usd <= MAX_BUDGET_USD

        await services.approval.approve(job.job_id, script_version=drafted.script_version,
                                        max_budget_usd=MAX_BUDGET_USD)  # fmt: skip
        await services.runner.join(job.job_id)
        done = await repo.get(job.job_id)
        print(
            f"status: {done.status} | custo real: US$ {done.ledger.total:.3f} | erro: {done.error}"
        )
        assert done.status is JobStatus.COMPLETED and done.final_hash
        assert done.ledger.total <= MAX_BUDGET_USD
        final = container.infra.cache.get(ArtifactKind.FINAL, done.final_hash)
        assert final is not None
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        print(f"vídeo: {shutil.copy(final, OUTPUT_DIR / f'{job.job_id}.mp4')}")
    finally:
        await container.shutdown(grace_s=5)
