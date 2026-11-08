"""Port de síntese de voz (Etapa 2, RF-02)."""

from typing import Protocol, runtime_checkable

from videogen.domain.generation import GenerationResult, RunContext, TTSRequest


@runtime_checkable
class TTSProvider(Protocol):
    async def synthesize(self, request: TTSRequest, ctx: RunContext) -> GenerationResult:
        """Cria (ou retoma, via `ctx.resume_remote_id`) a predição e espera o resultado."""
        ...

    async def cancel(self, remote_id: str) -> None:
        """Cancelamento best-effort; idempotente."""
        ...
