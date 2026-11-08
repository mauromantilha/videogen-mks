"""Ponto de entrada ASGI: `uvicorn videogen.main:app --workers 1`."""

from videogen.app.factory import create_app

app = create_app()
