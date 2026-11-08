"""Pula `ffmpeg` sem ffmpeg local (exceto no CI) e `live` sem RUN_LIVE=1 (gera custo real)."""

import os
import shutil

import pytest


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    skip_live = pytest.mark.skip(reason="gera custo real: rode com RUN_LIVE=1")
    skip_ffmpeg = pytest.mark.skip(
        reason="ffmpeg não instalado (no CI estes testes são obrigatórios)"
    )
    no_ffmpeg = not (shutil.which("ffmpeg") or os.environ.get("CI"))
    for item in items:
        if "live" in item.keywords and os.environ.get("RUN_LIVE") != "1":
            item.add_marker(skip_live)
        elif "ffmpeg" in item.keywords and no_ffmpeg:
            item.add_marker(skip_ffmpeg)
