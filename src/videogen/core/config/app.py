"""Configuração da aplicação: ambiente, autenticação, caminhos e log."""

from pathlib import Path
from typing import Literal

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class AppSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", frozen=True)

    app_env: Literal["dev", "test", "prod"] = "dev"
    app_api_key: SecretStr | None = None
    workspace_dir: Path = Path("./workspace")
    models_config: Path = Path("./config/models.yaml")
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
