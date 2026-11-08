"""Utilitários de rede para testes: sleep instantâneo e relógio monotônico controlável."""

from videogen.core.retry import RetryPolicy
from videogen.providers.http.polling import PollSchedule

FAST_POLICY = RetryPolicy(max_attempts=3, base_delay_s=0)


class Sleeper:
    """Substitui asyncio.sleep: registra as esperas e avança o relógio."""

    def __init__(self) -> None:
        self.now = 0.0
        self.calls: list[float] = []

    async def __call__(self, seconds: float) -> None:
        self.calls.append(seconds)
        self.now += seconds

    def clock(self) -> float:
        return self.now

    def schedule(self) -> PollSchedule:
        return PollSchedule(sleep=self, clock=self.clock)
