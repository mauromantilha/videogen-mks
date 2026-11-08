"""Relógio injetável: o código nunca chama `datetime.now()` direto (testes determinísticos)."""

from datetime import UTC, datetime
from typing import Protocol


class Clock(Protocol):
    def now(self) -> datetime: ...


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(UTC)
