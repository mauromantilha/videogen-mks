"""Startup/shutdown do processo: monta o container (se não injetado), recupera jobs e drena."""

from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager

from fastapi import FastAPI

from videogen.app.container import Container, build_container
from videogen.core.config import Settings, load_settings
from videogen.core.logging import configure_logging

Lifespan = Callable[[FastAPI], AbstractAsyncContextManager[None]]


def build_lifespan(container: Container | None, settings: Settings | None) -> Lifespan:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        active = container
        if active is None:
            resolved = settings or load_settings()
            configure_logging(resolved.app.log_level)
            active = build_container(resolved)
        app.state.services = active.api
        await active.startup()
        try:
            yield
        finally:
            await active.shutdown()

    return lifespan
