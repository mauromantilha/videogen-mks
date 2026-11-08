"""Container da aplicação: monta tudo uma vez e entrega à API um `ApiServices` pronto.

Startup: layout do workspace, limpeza de parciais, checagem do toolchain e recuperação de jobs.
Shutdown: drena o runner e fecha os clientes HTTP.
"""

import asyncio
import logging
from dataclasses import dataclass

from videogen.api.deps import ApiServices
from videogen.app.container_auth import AuthParts, build_auth
from videogen.app.container_infra import Infra, build_infra
from videogen.app.container_providers import Providers, build_providers
from videogen.app.container_services import Services, build_services
from videogen.app.readiness import ReadinessCheck
from videogen.core.clock import SystemClock
from videogen.core.config import Settings
from videogen.core.retry import RetryPolicy

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Container:
    settings: Settings
    infra: Infra
    providers: Providers
    services: Services
    auth: AuthParts
    api: ApiServices

    async def startup(self) -> None:
        self.infra.workspace.ensure_layout()
        await self.auth.startup()
        removed = await asyncio.to_thread(self.infra.cache.remove_partials)
        report = await self.infra.toolchain.run()
        if not report.ok:
            logger.warning("toolchain incompleto", extra={"problems": report.problems})
        recovered = await self.services.recovery.resume_all()
        resumed = len(recovered.drafted) + len(recovered.rendering)
        logger.info("pronto", extra={"partials_removed": removed, "jobs_resumed": resumed})

    async def shutdown(self, grace_s: float = 10.0) -> None:
        await self.services.runner.shutdown(grace_s)
        await self.providers.context.aclose()
        await self.infra.download_client.aclose()
        await self.auth.aclose()


def build_container(settings: Settings) -> Container:
    clock = SystemClock()
    policy = RetryPolicy(max_attempts=settings.render.http_max_attempts)
    infra = build_infra(settings, clock, policy)
    providers = build_providers(settings, infra.workspace, policy)
    services = build_services(settings, infra, providers, clock)
    auth = build_auth(settings, infra.workspace, clock)
    api = api_view(settings, infra, providers, services, auth)
    return Container(settings=settings, infra=infra, providers=providers, services=services,
                     auth=auth, api=api)  # fmt: skip


def api_view(
    settings: Settings, infra: Infra, providers: Providers, services: Services, auth: AuthParts
) -> ApiServices:
    return ApiServices(
        repo=infra.repo,
        bus=infra.bus,
        cache=infra.cache,
        voice_store=infra.voice_store,
        catalog=providers.catalog,
        models=providers.registry,
        creation=services.creation,
        control=services.control,
        edits=services.edits,
        approval=services.approval,
        voices=services.voices,
        health=ReadinessCheck(infra.toolchain, infra.workspace.jobs_dir, providers.registry),
        members=auth.members,
        auth=auth.login,
        secure_cookies=settings.auth.app_public_url.startswith("https://"),
        session_max_age_s=settings.auth.session_max_age_s,
    )
