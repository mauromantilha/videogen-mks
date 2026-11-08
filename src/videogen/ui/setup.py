"""Registra a UI na aplicação: rotas, estáticos e cabeçalhos de segurança."""

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from videogen.ui.routes import pages, progress_partials, script_partials, voices
from videogen.ui.security import security_headers
from videogen.ui.templating import UI_DIR


def register_ui(app: FastAPI) -> None:
    app.mount("/static", StaticFiles(directory=UI_DIR / "static"), name="static")
    app.middleware("http")(security_headers)
    for module in (pages, script_partials, progress_partials, voices):
        app.include_router(module.router)
