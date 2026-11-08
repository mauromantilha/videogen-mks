"""Configuração fatiada por responsabilidade (design/02 §1). Use `load_settings()`."""

from videogen.core.config.app import AppSettings
from videogen.core.config.loader import ConfigError, Settings, load_settings
from videogen.core.config.providers import ProviderSettings
from videogen.core.config.render import RenderSettings

__all__ = [
    "AppSettings",
    "ConfigError",
    "ProviderSettings",
    "RenderSettings",
    "Settings",
    "load_settings",
]
