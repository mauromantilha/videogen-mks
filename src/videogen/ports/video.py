"""Port de geração de vídeo text-to-video (Etapa 2, RF-03)."""

from typing import Protocol, runtime_checkable

from videogen.domain.generation import GenerationResult, RunContext, VideoRequest


@runtime_checkable
class VideoProvider(Protocol):
    async def generate(self, request: VideoRequest, ctx: RunContext) -> GenerationResult:
        """Cria (ou retoma, via `ctx.resume_remote_id`) a predição e espera o resultado."""
        ...

    async def cancel(self, remote_id: str) -> None:
        """Cancelamento best-effort; idempotente."""
        ...
