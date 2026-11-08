"""Credenciais dos provedores e modo de execução (`fake` = custo zero)."""

from typing import Literal

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class ProviderSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", frozen=True)

    provider_mode: Literal["real", "fake"] = "real"
    deepseek_api_key: SecretStr | None = None
    replicate_api_token: SecretStr | None = None
    fal_key: SecretStr | None = None
    deepinfra_api_token: SecretStr | None = None

    def configured(self) -> frozenset[str]:
        """Provedores com credencial não vazia."""
        keys = {
            "deepseek": self.deepseek_api_key,
            "replicate": self.replicate_api_token,
            "fal": self.fal_key,
            "deepinfra": self.deepinfra_api_token,
        }
        return frozenset(name for name, key in keys.items() if key and key.get_secret_value())
