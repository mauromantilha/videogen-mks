"""Uma cena: áudio ∥ vídeo → clipe (RNF-01). Compõe assim que o SEU par termina.

Se um lado falha, o outro ainda termina e fica em cache (já foi pago) antes da cena falhar.
"""

import asyncio

from videogen.domain.job import JobState
from videogen.domain.script import SceneSpec
from videogen.services.render.audio_step import AudioStep
from videogen.services.render.clip_step import ClipStep
from videogen.services.render.context import RenderContext, StepOutput
from videogen.services.render.video_step import VideoStep


class ScenePipeline:
    def __init__(self, ctx: RenderContext) -> None:
        self._audio = AudioStep(ctx)
        self._video = VideoStep(ctx)
        self._clip = ClipStep(ctx)

    async def run(self, job: JobState, scene: SceneSpec) -> StepOutput:
        audio, video = await asyncio.gather(
            self._audio.ensure(job, scene), self._video.ensure(job, scene), return_exceptions=True
        )
        if isinstance(audio, BaseException):
            raise audio
        if isinstance(video, BaseException):
            raise video
        return await self._clip.ensure(job, scene, audio, video)
