"""Lê e valida `config/models.yaml`. YAML inválido impede o processo de subir."""

from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from videogen.core.config import ConfigError
from videogen.domain.catalog import ModelCatalog

SUPPORTED_VERSION = 1


def load_catalog(path: Path) -> ModelCatalog:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise ConfigError(f"não foi possível ler {path}: {exc}") from exc
    return parse_catalog(raw, source=str(path))


def parse_catalog(raw: Any, *, source: str = "models.yaml") -> ModelCatalog:
    if not isinstance(raw, dict) or raw.get("version") != SUPPORTED_VERSION:
        raise ConfigError(f"{source}: esperado `version: {SUPPORTED_VERSION}` na raiz")
    models = raw.get("models")
    if not isinstance(models, dict) or not models:
        raise ConfigError(f"{source}: `models` deve ser um mapa não vazio")
    try:
        entries = {key: {"key": key, **(spec or {})} for key, spec in models.items()}
        return ModelCatalog.model_validate({"models": entries})
    except ValidationError as exc:
        raise ConfigError(f"{source}: catálogo inválido\n{exc}") from exc
