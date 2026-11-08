"""Text-to-video via Replicate (Wan 2.1, CogVideoX). Campos vêm do YAML (`fields`)."""

from videogen.domain.catalog import ModelSpec
from videogen.domain.generation import GenerationResult, RunContext, VideoRequest
from videogen.providers.replicate.mapping import build_input, video_values
from videogen.providers.replicate.runner import PredictionRunner


class ReplicateVideo:
    def __init__(self, runner: PredictionRunner, spec: ModelSpec) -> None:
        self._runner = runner
        self._spec = spec

    async def generate(self, request: VideoRequest, ctx: RunContext) -> GenerationResult:
        payload = build_input(self._spec, dict(video_values(request)))
        return await self._runner.run(self._spec, payload, ctx)

    async def cancel(self, remote_id: str) -> None:
        await self._runner.cancel(remote_id)
