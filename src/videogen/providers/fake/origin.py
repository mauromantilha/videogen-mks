"""Origem de mídia simulada: os fakes "publicam" arquivos e devolvem URLs https fictícias.

Também implementa o port `Downloader`, para o modo fake percorrer exatamente o mesmo
caminho do real (provedor → URL → download → cache) sem rede.
"""

import asyncio
import shutil
from collections.abc import Sequence
from pathlib import Path
from urllib.parse import urlsplit

from videogen.core.errors import ProviderError

FAKE_HOST = "fake.videogen.local"


class FakeMediaOrigin:
    def __init__(self, root: Path) -> None:
        self._root = root
        self._root.mkdir(parents=True, exist_ok=True)

    def publish(self, name: str, data: bytes) -> str:
        (self._root / name).write_bytes(data)
        return self.url_for(name)

    def path_for(self, name: str) -> Path:
        return self._root / name

    def url_for(self, name: str) -> str:
        return f"https://{FAKE_HOST}/{name}"

    async def fetch(
        self, url: str, dest: Path, *, allowed_hosts: Sequence[str], max_bytes: int
    ) -> None:
        parts = urlsplit(url)
        source = self._root / Path(parts.path).name
        if parts.hostname != FAKE_HOST or not source.is_file():
            raise ProviderError(f"mídia simulada inexistente: {url}")
        if source.stat().st_size > max_bytes:
            raise ProviderError("mídia simulada excede o limite de bytes")
        await asyncio.to_thread(shutil.copyfile, source, dest)
