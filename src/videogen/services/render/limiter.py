"""Limite de predições pagas simultâneas por modelo (evita estourar rate limit do provedor).

A vaga é ocupada só durante submit + polling; download e FFmpeg têm limites próprios.
"""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager


class ProviderLimiter:
    def __init__(self, ceilings: dict[str, int] | None = None) -> None:
        self._ceilings = ceilings or {}  # teto global por tipo: {"tts": 6, "t2v": 4}
        self._slots: dict[str, asyncio.Semaphore] = {}

    @asynccontextmanager
    async def slot(self, model_key: str, kind: str, concurrency: int) -> AsyncIterator[None]:
        if model_key not in self._slots:
            size = min(concurrency, self._ceilings.get(kind, concurrency))
            self._slots[model_key] = asyncio.Semaphore(max(1, size))
        async with self._slots[model_key]:
            yield
