"""Port de download seguro das saídas dos provedores (anti-SSRF, tamanho máximo)."""

from collections.abc import Sequence
from pathlib import Path
from typing import Protocol, runtime_checkable


@runtime_checkable
class Downloader(Protocol):
    async def fetch(
        self, url: str, dest: Path, *, allowed_hosts: Sequence[str], max_bytes: int
    ) -> None: ...
