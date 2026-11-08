"""Wiring dos provedores: catálogo YAML + registry (real ou fake)."""

from dataclasses import dataclass

from videogen.core.config import Settings
from videogen.core.retry import RetryPolicy
from videogen.domain.catalog import ModelCatalog
from videogen.infra.workspace import Workspace
from videogen.providers.catalog.context import ProviderContext
from videogen.providers.catalog.loader import load_catalog
from videogen.providers.catalog.registry import ProviderRegistry


@dataclass(frozen=True)
class Providers:
    catalog: ModelCatalog
    context: ProviderContext
    registry: ProviderRegistry


def build_providers(settings: Settings, workspace: Workspace, policy: RetryPolicy) -> Providers:
    catalog = load_catalog(settings.app.models_config)
    context = ProviderContext(settings.providers, policy, workspace.root / "_fake_origin")
    registry = ProviderRegistry(catalog, context, mode=settings.providers.provider_mode)
    return Providers(catalog=catalog, context=context, registry=registry)
