"""Criação da aplicação FastAPI. Só faz wiring: nenhuma regra de negócio aqui."""

from fastapi import FastAPI

from videogen import __version__
from videogen.api.routers import health


def create_app() -> FastAPI:
    """Monta a aplicação com os routers registrados."""
    app = FastAPI(title="VideoGen MKS", version=__version__)
    app.include_router(health.router)
    return app
