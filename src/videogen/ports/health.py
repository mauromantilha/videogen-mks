"""Port de prontidão: a API pergunta "posso atender?" sem conhecer FFmpeg nem disco."""

from typing import Protocol, runtime_checkable


@runtime_checkable
class HealthCheck(Protocol):
    async def problems(self) -> list[str]:
        """Lista vazia = pronto para trabalhar."""
        ...
