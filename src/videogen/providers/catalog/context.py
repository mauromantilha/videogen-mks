"""Recursos compartilhados pelos adapters: credenciais, clientes HTTP e estado dos fakes."""

from pathlib import Path

import httpx

from videogen.core.config import ConfigError, ProviderSettings
from videogen.core.retry import RetryPolicy
from videogen.providers.fake.behavior import FakeBehavior
from videogen.providers.fake.origin import FakeMediaOrigin
from videogen.providers.http.client import ResilientHttpClient

# provedor -> (atributo em ProviderSettings, esquema do cabeçalho Authorization)
_CREDENTIALS = {
    "deepseek": ("deepseek_api_key", "Bearer"),
    "deepinfra": ("deepinfra_api_token", "Bearer"),
    "replicate": ("replicate_api_token", "Bearer"),
    "fal": ("fal_key", "Key"),
}
DEFAULT_TIMEOUT = httpx.Timeout(60.0, connect=10.0)


class ProviderContext:
    def __init__(self, settings: ProviderSettings, policy: RetryPolicy, fake_root: Path) -> None:
        self.settings = settings
        self.policy = policy
        self.fake_origin = FakeMediaOrigin(fake_root)
        self.fake_behavior = FakeBehavior()
        self._clients: dict[str, httpx.AsyncClient] = {}

    def has_credential(self, provider: str) -> bool:
        return provider in self.settings.configured()

    def http(self, provider: str) -> ResilientHttpClient:
        if provider not in self._clients:
            self._clients[provider] = httpx.AsyncClient(
                headers={"Authorization": self._authorization(provider)}, timeout=DEFAULT_TIMEOUT
            )
        return ResilientHttpClient(self._clients[provider], self.policy, provider=provider)

    async def aclose(self) -> None:
        for client in self._clients.values():
            await client.aclose()
        self._clients.clear()

    def _authorization(self, provider: str) -> str:
        if provider not in _CREDENTIALS:
            raise ConfigError(f"provedor sem esquema de credencial conhecido: {provider}")
        attribute, scheme = _CREDENTIALS[provider]
        secret = getattr(self.settings, attribute)
        if not self.has_credential(provider) or secret is None:
            raise ConfigError(f"credencial ausente para {provider} ({attribute.upper()})")
        return f"{scheme} {secret.get_secret_value()}"
