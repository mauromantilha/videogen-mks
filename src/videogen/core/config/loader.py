"""Carrega e valida as combinações entre os grupos de configuração."""

from dataclasses import dataclass
from pathlib import Path

from pydantic import ValidationError

from videogen.core.config.app import AppSettings
from videogen.core.config.providers import ProviderSettings
from videogen.core.config.render import RenderSettings


class ConfigError(ValueError):
    """Configuração inválida: o processo não deve subir."""


@dataclass(frozen=True)
class Settings:
    app: AppSettings
    providers: ProviderSettings
    render: RenderSettings


def load_settings(env_file: Path | None = Path(".env")) -> Settings:
    try:
        settings = Settings(
            app=AppSettings(_env_file=env_file),
            providers=ProviderSettings(_env_file=env_file),
            render=RenderSettings(_env_file=env_file),
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
    api_key = settings.app.app_api_key
    if settings.app.app_env == "prod" and not (api_key and api_key.get_secret_value()):
        raise ConfigError("APP_ENV=prod exige APP_API_KEY")
