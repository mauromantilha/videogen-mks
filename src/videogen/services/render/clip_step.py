"""Etapa de clipe (RF-04, RF-05): sync + legenda + encode local, cache `clip`. Não é paga."""

from videogen.domain.hashing import clip_hash
from videogen.domain.job import JobState
from videogen.domain.media import ArtifactKind
from videogen.domain.progress import ErrorInfo
from videogen.domain.render_plan import output_size
from videogen.domain.render_specs import ClipParams, ClipSpec
from videogen.domain.script import SceneSpec
from videogen.services.render.context import RenderContext, StepOutput
from videogen.services.render.step_tracker import StepRef


class ClipStep:
    def __init__(self, ctx: RenderContext) -> None:
        self._ctx = ctx

    async def ensure(
        self, job: JobState, scene: SceneSpec, audio: StepOutput, video: StepOutput
    ) -> StepOutput:
        ctx = self._ctx
        ref = StepRef(job.job_id, scene.scene_index, "clip")
        params = clip_params(job, scene, ctx)
        key = clip_hash(audio.key, video.key, params)
        if (hit := ctx.cache.get(ArtifactKind.CLIP, key)) is not None:
            await ctx.tracker.cached(ref, key)
            return StepOutput(hit, key)
        await ctx.tracker.started(ref, paid=False)
        tmp = ctx.cache.tmp_path(ArtifactKind.CLIP, key)
        try:
            spec = ClipSpec(params=params, video_path=video.path, audio_path=audio.path,
                            out_path=tmp)  # fmt: skip
            await ctx.composer.compose_clip(spec)
            path = ctx.cache.commit(ArtifactKind.CLIP, key, tmp, {"scene": scene.scene_index})
        except Exception as exc:
            tmp.unlink(missing_ok=True)
            await ctx.tracker.failed(ref, ErrorInfo.from_exception(exc))
            raise
        await ctx.tracker.done(ref, key, cost_usd=0.0, kind=None)
        return StepOutput(path, key)


def clip_params(job: JobState, scene: SceneSpec, ctx: RenderContext) -> ClipParams:
    options = job.request.options
    width, height = output_size(job.request.aspect_ratio, options.resolution)
    return ClipParams(texto=scene.texto_narrado, aspect_ratio=job.request.aspect_ratio,
                      width=width, height=height, fps=options.fps, subtitles=options.legendas,
                      sync=ctx.sync)  # fmt: skip
