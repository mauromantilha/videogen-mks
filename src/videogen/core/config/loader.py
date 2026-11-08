"""Carrega e valida as combinações entre os grupos de configuração."""

from dataclasses import dataclass, field
from pathlib import Path

from pydantic import ValidationError

from videogen.core.config.app import AppSettings
from videogen.core.config.auth import AuthSettings
from videogen.core.config.providers import ProviderSettings
from videogen.core.config.render import RenderSettings


class ConfigError(ValueError):
    """Configuração inválida: o processo não deve subir."""


@dataclass(frozen=True)
class Settings:
    app: AppSettings
    providers: ProviderSettings
    render: RenderSettings
    auth: AuthSettings = field(default_factory=lambda: AuthSettings(_env_file=None))


def load_settings(env_file: Path | None = Path(".env")) -> Settings:
    try:
        settings = Settings(
            app=AppSettings(_env_file=env_file),
            providers=ProviderSettings(_env_file=env_file),
            render=RenderSettings(_env_file=env_file),
            auth=AuthSettings(_env_file=env_file),
        )
    except ValidationError as exc:
        raise ConfigError(f"configuração inválida:\n{exc}") from exc
    _check_combinations(settings)
    return settings


def _check_combinations(settings: Settings) -> None:
    if settings.providers.provider_mode == "real" and not settings.providers.configured():
        raise ConfigError(
            "PROVIDER_MODE=real exige ao menos uma chave de provedor "
            "(DEEPSEEK_API_KEY, REPLICATE_API_TOKEN, FAL_KEY ou DEEPINFRA_API_TOKEN); "
            "use PROVIDER_MODE=fake para rodar sem custo"
        )
    _check_auth(settings)


def _check_auth(settings: Settings) -> None:
    auth = settings.auth
    if settings.app.app_env == "prod" and auth.auth_mode != "neon":
        raise ConfigError("APP_ENV=prod exige AUTH_MODE=neon (login por usuário)")
    if auth.auth_mode != "neon":
        return
    if not auth.neon_auth_url or not auth.neon_auth_url.startswith("https://"):
        raise ConfigError("AUTH_MODE=neon exige NEON_AUTH_URL (https://…/auth)")
    if settings.app.app_env == "prod" and not auth.app_public_url.startswith("https://"):
        raise ConfigError("APP_ENV=prod exige APP_PUBLIC_URL em https")
    if settings.app.app_env == "prod" and auth.database_url is None:
        raise ConfigError("APP_ENV=prod exige DATABASE_URL (membros no Postgres)")
