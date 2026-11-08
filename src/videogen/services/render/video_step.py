"""Etapa de vídeo (RF-03): T2V pago com seed fixa, cache `video_raw`."""

from videogen.domain.generation import GenerationResult, RunContext
from videogen.domain.hashing import video_hash
from videogen.domain.job import JobState
from videogen.domain.media import ArtifactKind
from videogen.domain.progress import ErrorInfo
from videogen.domain.render_plan import video_request
from videogen.domain.script import SceneSpec
from videogen.services.render.cached_step import PaidCall
from videogen.services.render.context import RenderContext, StepOutput
from videogen.services.render.step_tracker import StepRef


class VideoStep:
    def __init__(self, ctx: RenderContext) -> None:
        self._ctx = ctx

    async def ensure(self, job: JobState, scene: SceneSpec) -> StepOutput:
        ref = StepRef(job.job_id, scene.scene_index, "video")
        try:
            return await self._ensure(job, scene, ref)
        except Exception as exc:
            await self._ctx.tracker.failed(ref, ErrorInfo.from_exception(exc))
            raise

    async def _ensure(self, job: JobState, scene: SceneSpec, ref: StepRef) -> StepOutput:
        ctx = self._ctx
        spec = ctx.catalog.get(job.request.models.video, "t2v")
        request = video_request(job.job_id, scene, job.require_script(), spec,
                                job.request.aspect_ratio)  # fmt: skip
        key = video_hash(request)
        provider = ctx.providers.video(spec.key)

        async def produce(run_ctx: RunContext) -> GenerationResult:
            async with ctx.limiter.slot(spec.key, "t2v", spec.concurrency):
                return await provider.generate(request, run_ctx)

        produced = await ctx.cached_step.fetch(
            PaidCall(ArtifactKind.VIDEO_RAW, key, spec, produce, provider.cancel), ref
        )
        if produced.fresh:
            await ctx.tracker.done(ref, key, cost_usd=produced.cost_usd, kind="video")
        else:
            await ctx.tracker.cached(ref, key)
        return StepOutput(produced.path, key)
