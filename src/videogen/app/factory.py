"""Criação da aplicação FastAPI. Só faz wiring: nenhuma regra de negócio aqui."""

from fastapi import FastAPI

from videogen import __version__
from videogen.api.error_handlers import register_error_handlers
from videogen.api.routers import (
    approval,
    artifacts,
    catalog,
    events,
    health,
    jobs,
    script,
    voices,
)
from videogen.app.container import Container
from videogen.app.lifespan import build_lifespan
from videogen.core.config import Settings
from videogen.ui.setup import register_ui

ROUTERS = (health, jobs, script, approval, events, artifacts, voices, catalog)


def create_app(container: Container | None = None, *, settings: Settings | None = None) -> FastAPI:
    """Sem argumentos, o container é montado no startup a partir do `.env`.

    Com `container`, ele já fica disponível sem o lifespan (útil em testes).
    """
    app = FastAPI(
        title="VideoGen MKS",
        version=__version__,
        description="Vídeos curtos a partir de linguagem natural: roteiro aprovado → render.",
        lifespan=build_lifespan(container, settings),
    )
    if container is not None:
        app.state.services = container.api
    register_error_handlers(app)
    for module in ROUTERS:
        app.include_router(module.router)
    register_ui(app)
    return app
