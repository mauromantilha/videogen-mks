"""Polling com intervalo crescente e prazo total (cold start incluso)."""

import asyncio
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from videogen.core.errors import ProviderTimeout
from videogen.core.retry import Sleep

Monotonic = Callable[[], float]


@dataclass(frozen=True)
class PollSchedule:
    initial_s: float = 2.0
    max_s: float = 5.0
    factor: float = 1.5
    sleep: Sleep = field(default=asyncio.sleep, compare=False)
    clock: Monotonic = field(default=time.monotonic, compare=False)


async def poll_until[T](
    fetch: Callable[[], Awaitable[T]],
    is_done: Callable[[T], bool],
    *,
    timeout_s: float,
    schedule: PollSchedule,
    label: str = "predição",
) -> T:
    """Chama `fetch` até `is_done`; `ProviderTimeout` (retryable) ao estourar o prazo.

    Erros de rede dentro de `fetch` são tratados pelo retry do próprio cliente e não
    consomem as tentativas de submissão.
    """
    deadline = schedule.clock() + timeout_s
    interval = schedule.initial_s
    while True:
        state = await fetch()
        if is_done(state):
            return state
        remaining = deadline - schedule.clock()
        if remaining <= 0:
            raise ProviderTimeout(f"{label} não terminou em {timeout_s:.0f}s")
        await schedule.sleep(min(interval, remaining))
        interval = min(interval * schedule.factor, schedule.max_s)
