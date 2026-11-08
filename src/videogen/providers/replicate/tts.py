"""TTS via Replicate (F5-TTS etc.). O nome dos campos vem do YAML (`fields`)."""

import asyncio

from videogen.domain.catalog import ModelSpec
from videogen.domain.generation import GenerationResult, RunContext, TTSRequest
from videogen.providers.replicate.mapping import build_input, tts_values
from videogen.providers.replicate.runner import PredictionRunner


class ReplicateTTS:
    def __init__(self, runner: PredictionRunner, spec: ModelSpec) -> None:
        self._runner = runner
        self._spec = spec

    async def synthesize(self, request: TTSRequest, ctx: RunContext) -> GenerationResult:
        ref_audio = await asyncio.to_thread(request.ref_audio_path.read_bytes)
        payload = build_input(self._spec, tts_values(request, ref_audio))
        return await self._runner.run(self._spec, payload, ctx)

    async def cancel(self, remote_id: str) -> None:
        await self._runner.cancel(remote_id)
