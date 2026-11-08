"""Sobe a aplicação real (container completo, modo fake) num workspace temporário."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from tests.fakes.identity import FakeIdentityProvider
from videogen.app.container import Container, build_container
from videogen.app.factory import create_app
from videogen.core.config import AppSettings, ProviderSettings, RenderSettings, Settings
from videogen.domain.identity import LOCAL_USER, Member, Role
from videogen.providers.fake.media import sine_wav
from videogen.services.auth.login import AuthService

ROOT = Path(__file__).resolve().parents[2]
ADMIN_EMAIL = "admin@mksseguros.com"


@dataclass
class ApiHarness:
    client: httpx.AsyncClient
    container: Container
    voice_id: str
    identity: FakeIdentityProvider = field(default_factory=FakeIdentityProvider)

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


def fake_settings(workspace: Path) -> Settings:
    return Settings(
        app=AppSettings(_env_file=None, workspace_dir=workspace,
                        models_config=ROOT / "config/models.yaml"),
        providers=ProviderSettings(_env_file=None, provider_mode="fake"),
        render=RenderSettings(_env_file=None),
    )  # fmt: skip


@asynccontextmanager
async def running_api(
    workspace: Path, *, auth: bool = False, raise_errors: bool = True,
    client_host: str = "127.0.0.1",
) -> AsyncIterator[ApiHarness]:  # fmt: skip
    """`auth=False`: modo local (sem login, loopback). `auth=True`: login real com provedor fake;
    a voz padrão pertence ao admin `ADMIN_EMAIL` (senha `senha-do-admin`)."""
    identity = FakeIdentityProvider()
    container = _with_auth(build_container(fake_settings(workspace)), identity) if auth else (
        build_container(fake_settings(workspace)))  # fmt: skip
    await container.startup()
    owner = LOCAL_USER.user_id
    if auth:
        owner = identity.add_user(ADMIN_EMAIL, "senha-do-admin").user_id
        await container.auth.directory.add(Member(email=ADMIN_EMAIL, name="Admin",
                                                  role=Role.ADMIN, created_at=_now()))  # fmt: skip
    voice = await container.infra.voice_store.save(
        sine_wav(6.0), name="Padrão", ref_text="Olá, esta é a minha voz.", duration_s=6.0,
        owner_id=owner,
    )  # fmt: skip
    transport = httpx.ASGITransport(create_app(container), raise_app_exceptions=raise_errors,
                                    client=(client_host, 50000))  # fmt: skip
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        try:
            yield ApiHarness(client=client, container=container, voice_id=voice.voice_id,
                             identity=identity)  # fmt: skip
        finally:
            await container.shutdown(grace_s=1)


def _with_auth(container: Container, identity: FakeIdentityProvider) -> Container:
    login = AuthService(identity, identity, container.auth.directory)
    return replace(container, api=replace(container.api, auth=login, secure_cookies=False))


def _now() -> datetime:
    return datetime.now(UTC)
