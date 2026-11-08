"""Ambiente Jinja2 da UI (autoescape ligado: texto do LLM nunca vira HTML)."""

from pathlib import Path

from fastapi.templating import Jinja2Templates

from videogen.ui.filters import FILTERS

UI_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=UI_DIR / "templates")
templates.env.filters.update(FILTERS)
