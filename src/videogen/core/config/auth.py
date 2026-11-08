"""Configuração de autenticação e do banco de membros.

`local`: sem login, só conexões do próprio host (desenvolvimento e testes).
`neon`: login pelo Neon Auth (senha ou código por e-mail) + membros no Postgres.
"""

from typing import Any, Literal

from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class AuthSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", frozen=True)

    auth_mode: Literal["local", "neon"] = "local"
    neon_auth_url: str | None = None  # .../neondb/auth (Neon Console → Auth → Configuration)
    app_public_url: str = "http://localhost:8000"  # vai como Origin (precisa ser confiável no Neon)
    database_url: SecretStr | None = None  # sem ele, membros num JSON do workspace (dev)
    auth_allowed_domain: str = "mksseguros.com"  # só e-mails deste domínio viram membros
    auth_bootstrap_admin: str | None = None  # vira admin no startup se ainda não houver nenhum
    session_max_age_s: int = 7 * 24 * 3600
    session_cache_s: float = 60.0

    @field_validator("neon_auth_url", "database_url", "auth_bootstrap_admin", mode="before")
    @classmethod
    def _blank_is_none(cls, value: Any) -> Any:
        """`VAR=` vazio no .env equivale a não definir."""
        return None if isinstance(value, str) and not value.strip() else value
