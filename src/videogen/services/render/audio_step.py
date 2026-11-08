"""Etapa de áudio (RF-02): TTS pago (cache `audio_raw`) → loudnorm local (cache `audio_norm`).

O hash gravado no step é o do áudio normalizado (é o que a API serve e o clipe usa). Mudar só
o alvo de loudness refaz a normalização, nunca o TTS pago.
"""

from pathlib import Path

from videogen.domain.generation import GenerationResult, RunContext
from videogen.domain.hashing import audio_hash, audio_norm_hash
from videogen.domain.job import JobState
from videogen.domain.media import ArtifactKind
from videogen.domain.progress import ErrorInfo
from videogen.domain.render_plan import tts_request
from videogen.domain.script import SceneSpec
from videogen.services.render.cached_step import PaidCall
from videogen.services.render.context import RenderContext, StepOutput
from videogen.services.render.step_tracker import StepRef


class AudioStep:
    def __init__(self, ctx: RenderContext) -> None:
        self._ctx = ctx

    async def ensure(self, job: JobState, scene: SceneSpec) -> StepOutput:
        ref = StepRef(job.job_id, scene.scene_index, "audio")
        try:
            return await self._ensure(job, scene, ref)
        except Exception as exc:
            await self._ctx.tracker.failed(ref, ErrorInfo.from_exception(exc))
            raise

    async def _ensure(self, job: JobState, scene: SceneSpec, ref: StepRef) -> StepOutput:
        ctx = self._ctx
        spec = ctx.catalog.get(job.request.models.tts, "tts")
        request = tts_request(scene, spec, await ctx.voices.get(job.request.voice_id))
        raw_key = audio_hash(request)
        norm_key = audio_norm_hash(raw_key, ctx.loudness)
        if (hit := ctx.cache.get(ArtifactKind.AUDIO_NORM, norm_key)) is not None:
            await ctx.tracker.cached(ref, norm_key)
            return StepOutput(hit, norm_key)
        provider = ctx.providers.tts(spec.key)

        async def produce(run_ctx: RunContext) -> GenerationResult:
            async with ctx.limiter.slot(spec.key, "tts", spec.concurrency):
                return await provider.synthesize(request, run_ctx)

        call = PaidCall(ArtifactKind.AUDIO_RAW, raw_key, spec, produce, provider.cancel)
        raw = await ctx.cached_step.fetch(call, ref)
        path = await ctx.flight.run(norm_key, lambda: self._normalize(raw.path, norm_key))
        if raw.fresh:
            await ctx.tracker.done(ref, norm_key, cost_usd=raw.cost_usd, kind="tts")
        else:
            await ctx.tracker.cached(ref, norm_key)
        return StepOutput(path, norm_key)

    async def _normalize(self, raw: Path, norm_key: str) -> Path:
        ctx = self._ctx
        if (hit := ctx.cache.get(ArtifactKind.AUDIO_NORM, norm_key)) is not None:
            return hit
        tmp = ctx.cache.tmp_path(ArtifactKind.AUDIO_NORM, norm_key)
        await ctx.composer.normalize_audio(raw, tmp, ctx.loudness)
        meta = {"source": raw.name, "lufs": ctx.loudness.integrated_lufs}
        return ctx.cache.commit(ArtifactKind.AUDIO_NORM, norm_key, tmp, meta)
