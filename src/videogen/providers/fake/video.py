"""Vídeo simulado: padrão de teste com a duração de `num_frames / fps` (exige ffmpeg)."""

from videogen.domain.generation import GenerationResult, RunContext, VideoRequest
from videogen.providers.fake.behavior import FakeBehavior
from videogen.providers.fake.media import render_test_pattern
from videogen.providers.fake.origin import FakeMediaOrigin


class FakeVideo:
    def __init__(self, origin: FakeMediaOrigin, behavior: FakeBehavior) -> None:
        self._origin = origin
        self._behavior = behavior

    async def generate(self, request: VideoRequest, ctx: RunContext) -> GenerationResult:
        remote_id = await self._behavior.submit(request.prompt, "fake-t2v", ctx)
        name = f"{remote_id}.mp4"
        if not self._origin.path_for(name).exists():
            await render_test_pattern(
                self._origin.path_for(name),
                duration_s=request.num_frames / request.fps,
                size=(request.width, request.height),
                fps=request.fps,
            )
        return GenerationResult(
            remote_id=remote_id, output_url=self._origin.url_for(name), cost_usd=0.0
        )

    async def cancel(self, remote_id: str) -> None:
        self._behavior.cancels.append(remote_id)
