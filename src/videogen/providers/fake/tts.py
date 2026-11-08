"""TTS simulado: WAV senoidal com duração proporcional ao texto (exercita o plan_sync)."""

from videogen.domain.generation import GenerationResult, RunContext, TTSRequest
from videogen.providers.fake.behavior import FakeBehavior
from videogen.providers.fake.media import sine_wav
from videogen.providers.fake.origin import FakeMediaOrigin

WORDS_PER_SECOND = 2.5
MIN_DURATION_S = 1.0


class FakeTTS:
    def __init__(self, origin: FakeMediaOrigin, behavior: FakeBehavior) -> None:
        self._origin = origin
        self._behavior = behavior

    async def synthesize(self, request: TTSRequest, ctx: RunContext) -> GenerationResult:
        remote_id = await self._behavior.submit(request.text, "fake-tts", ctx)
        name = f"{remote_id}.wav"
        if not self._origin.path_for(name).exists():
            duration = max(MIN_DURATION_S, len(request.text.split()) / WORDS_PER_SECOND)
            self._origin.publish(name, sine_wav(duration))
        return GenerationResult(
            remote_id=remote_id, output_url=self._origin.url_for(name), cost_usd=0.0
        )

    async def cancel(self, remote_id: str) -> None:
        self._behavior.cancels.append(remote_id)
