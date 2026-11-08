"""Sobe a aplicação real (container completo, modo fake) num workspace temporário."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
from pydantic import SecretStr

from videogen.app.container import Container, build_container
from videogen.app.factory import create_app
from videogen.core.config import AppSettings, ProviderSettings, RenderSettings, Settings
from videogen.providers.fake.media import sine_wav

ROOT = Path(__file__).resolve().parents[2]
API_KEY = "segredo-de-teste"


@dataclass
class ApiHarness:
    client: httpx.AsyncClient
    container: Container
    voice_id: str

    def job_body(self, **overrides: Any) -> dict[str, Any]:
        body: dict[str, Any] = {
            "tema": "Seguro de vida para jovens profissionais", "n_cenas": 3,
            "models": {"llm": "deepseek-flash", "tts": "f5-tts", "video": "wan-2.1-t2v-480p"},
            "voice_id": self.voice_id, "max_budget_usd": 1.0,
        }  # fmt: skip
        return body | overrides

    async def settle(self, job_id: str) -> dict[str, Any]:
        """Espera o trabalho em segundo plano do job e devolve o JobView atual."""
        await self.container.services.runner.join(job_id)
        response = await self.client.get(f"/api/v1/jobs/{job_id}")
        data: dict[str, Any] = response.json()
        return data


def fake_settings(workspace: Path, api_key: str | None = API_KEY) -> Settings:
    return Settings(
        app=AppSettings(_env_file=None, workspace_dir=workspace,
                        models_config=ROOT / "config/models.yaml",
                        app_api_key=SecretStr(api_key) if api_key else None),
        providers=ProviderSettings(_env_file=None, provider_mode="fake"),
        render=RenderSettings(_env_file=None),
    )  # fmt: skip


@asynccontextmanager
async def running_api(
    workspace: Path, *, api_key: str | None = API_KEY, raise_errors: bool = True
) -> AsyncIterator[ApiHarness]:
    container = build_container(fake_settings(workspace, api_key))
    await container.startup()
    voice = await container.infra.voice_store.save(
        sine_wav(6.0), name="Padrão", ref_text="Olá, esta é a minha voz.", duration_s=6.0
    )
    transport = httpx.ASGITransport(create_app(container), raise_app_exceptions=raise_errors)
    headers = {"X-API-Key": api_key} if api_key else {}
    async with httpx.AsyncClient(transport=transport, base_url="http://test",
                                 headers=headers) as client:  # fmt: skip
        try:
            yield ApiHarness(client=client, container=container, voice_id=voice.voice_id)
        finally:
            await container.shutdown(grace_s=1)
