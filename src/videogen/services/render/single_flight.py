"""Single-flight por chave: pedidos concorrentes iguais viram uma só execução (RNF-02).

Duas cenas com o mesmo texto (ou prompt+seed) no mesmo render pagam uma vez; a segunda
recebe o mesmo resultado — ou a mesma exceção.
"""

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any


class SingleFlight:
    def __init__(self) -> None:
        self._inflight: dict[str, asyncio.Future[Any]] = {}

    def is_inflight(self, key: str) -> bool:
        return key in self._inflight

    async def run[T](self, key: str, factory: Callable[[], Awaitable[T]]) -> T:
        if (future := self._inflight.get(key)) is not None:
            result: T = await asyncio.shield(future)
            return result
        future = asyncio.get_running_loop().create_future()
        self._inflight[key] = future
        try:
            value = await factory()
        except BaseException as exc:
            future.set_exception(exc)
            future.exception()  # marca como observada: sem aviso se ninguém mais esperava
            raise
        else:
            future.set_result(value)
            return value
        finally:
            del self._inflight[key]
