"""Relógio controlável para testes."""

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

DEFAULT_START = datetime(2026, 11, 8, 12, 0, tzinfo=UTC)


class FakeClock:
    def __init__(self, start: datetime = DEFAULT_START) -> None:
        self._now = start

    def now(self) -> datetime:
        return self._now

    def advance(self, seconds: float) -> None:
        self._now += timedelta(seconds=seconds)


if TYPE_CHECKING:
    from videogen.core.clock import Clock

    _conforms: Clock = FakeClock()
