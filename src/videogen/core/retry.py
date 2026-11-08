"""Retry com backoff exponencial e jitter (RNF-04), compartilhado por providers e downloader.

Só repete erros marcados como `retryable`. Respeita `retry_after_s` no contexto do erro
(vindo do cabeçalho `Retry-After`). Relógio e RNG são injetáveis para testes determinísticos.
"""

import asyncio
import logging
import random
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from videogen.core.errors import DomainError

logger = logging.getLogger(__name__)

Sleep = Callable[[float], Awaitable[None]]
Random = Callable[[], float]


@dataclass(frozen=True)
class RetryPolicy:
    max_attempts: int = 3
    base_delay_s: float = 1.0
    max_delay_s: float = 30.0

    def __post_init__(self) -> None:
        if self.max_attempts < 1 or self.base_delay_s < 0 or self.max_delay_s < 0:
            raise ValueError("política de retry inválida")

    def backoff(self, attempt: int, rng: Random) -> float:
        """Full jitter: aleatório em [0, min(teto, base * 2^(tentativa-1))]."""
        ceiling = min(self.max_delay_s, self.base_delay_s * 2.0 ** (attempt - 1))
        return rng() * ceiling


def is_retryable(exc: BaseException) -> bool:
    return isinstance(exc, DomainError) and exc.retryable


def retry_after(exc: BaseException) -> float | None:
    value = exc.context.get("retry_after_s") if isinstance(exc, DomainError) else None
    return float(value) if isinstance(value, int | float) and value >= 0 else None


async def retry_async[T](
    operation: Callable[[], Awaitable[T]],
    policy: RetryPolicy,
    *,
    sleep: Sleep = asyncio.sleep,
    rng: Random = random.random,
    label: str = "operação",
) -> T:
    """Executa `operation` até `policy.max_attempts` vezes; propaga o último erro."""
    attempt = 1
    while True:
        try:
            return await operation()
        except Exception as exc:
            if attempt >= policy.max_attempts or not is_retryable(exc):
                raise
            hinted = retry_after(exc)
            delay = policy.backoff(attempt, rng)
            if hinted is not None:
                delay = min(hinted, policy.max_delay_s)
            logger.warning(
                "%s falhou; nova tentativa em %.2fs",
                label,
                delay,
                extra={"attempt": attempt, "error_code": getattr(exc, "code", type(exc).__name__)},
            )
            await sleep(delay)
            attempt += 1
