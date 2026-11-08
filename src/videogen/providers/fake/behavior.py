"""Comportamento configurável dos fakes: latência, falhas injetáveis e contadores."""

import asyncio
from dataclasses import dataclass, field

from videogen.core.errors import ContentRejected, ProviderError
from videogen.domain.generation import RunContext


@dataclass
class FailureRule:
    marker: str  # falha quando o texto/prompt contém este trecho
    times: int  # quantas vezes falhar antes de passar
    retryable: bool = True
    content_rejected: bool = False


@dataclass
class FakeBehavior:
    latency_s: float = 0.0
    rules: list[FailureRule] = field(default_factory=list)
    max_attempts: int = 3
    submits: list[str] = field(default_factory=list)  # remote_ids criados, em ordem
    cancels: list[str] = field(default_factory=list)

    def fail_when(self, marker: str, times: int = 1, *, retryable: bool = True) -> None:
        self.rules.append(FailureRule(marker, times, retryable))

    def reject_when(self, marker: str) -> None:
        self.rules.append(FailureRule(marker, 1_000_000, retryable=False, content_rejected=True))

    async def before_run(self, content: str) -> None:
        if self.latency_s:
            await asyncio.sleep(self.latency_s)
        for rule in self.rules:
            if rule.marker in content and rule.times > 0:
                rule.times -= 1
                if rule.content_rejected:
                    raise ContentRejected(f"fake: conteúdo recusado ({rule.marker})")
                raise ProviderError(
                    f"fake: falha injetada ({rule.marker})", retryable=rule.retryable
                )

    async def submit(self, content: str, prefix: str, ctx: RunContext) -> str:
        """Mesma semântica do adapter real: cria a predição, avisa o id e, em falha
        transitória, cria outra (até `max_attempts`). Retomada não cria nada."""
        if ctx.resume_remote_id is not None:
            return ctx.resume_remote_id
        attempt = 1
        while True:
            remote_id = f"{prefix}-{len(self.submits) + 1}"
            self.submits.append(remote_id)
            await ctx.on_submitted(remote_id)
            try:
                await self.before_run(content)
            except ProviderError as exc:
                if not exc.retryable or attempt >= self.max_attempts:
                    raise
                attempt += 1
                continue
            return remote_id

    def submit_count(self, prefix: str = "") -> int:
        return sum(1 for remote_id in self.submits if remote_id.startswith(prefix))
