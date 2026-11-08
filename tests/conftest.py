"""Pula testes `@pytest.mark.ffmpeg` sem ffmpeg local — exceto no CI, onde são obrigatórios."""

import os
import shutil

import pytest


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if shutil.which("ffmpeg") or os.environ.get("CI"):
        return
    skip = pytest.mark.skip(reason="ffmpeg não instalado (no CI estes testes são obrigatórios)")
    for item in items:
        if "ffmpeg" in item.keywords:
            item.add_marker(skip)
