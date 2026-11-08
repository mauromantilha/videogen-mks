"""Estimativa de custo antes da aprovação (RF-08), descontando o que já está em cache.

Usa `domain.render_plan` — os mesmos pedidos que o render enviará —, então uma cena cujo
áudio e vídeo já existem custa zero aqui e zero no render.
"""

from videogen.domain.catalog import ModelCatalog
from videogen.domain.cost import CostEstimate, SceneEstimate
from videogen.domain.hashing import audio_hash, video_hash
from videogen.domain.job import JobState
from videogen.domain.media import ArtifactKind
from videogen.domain.render_plan import tts_request, video_request
from videogen.ports.cache import ArtifactCache
from videogen.ports.voices import VoiceStore


class CostEstimator:
    def __init__(self, catalog: ModelCatalog, cache: ArtifactCache, voices: VoiceStore) -> None:
        self._catalog = catalog
        self._cache = cache
        self._voices = voices

    async def estimate(self, job: JobState) -> CostEstimate:
        script = job.require_script()
        models = job.request.models
        tts_spec = self._catalog.get(models.tts, "tts")
        video_spec = self._catalog.get(models.video, "t2v")
        voice = await self._voices.get(job.request.voice_id)
        scenes = []
        for scene in script.cenas:
            audio_key = audio_hash(tts_request(scene, tts_spec, voice))
            video_key = video_hash(
                video_request(job.job_id, scene, script, video_spec, job.request.aspect_ratio)
            )
            audio_cached = self._cache.get(ArtifactKind.AUDIO_RAW, audio_key) is not None
            video_cached = self._cache.get(ArtifactKind.VIDEO_RAW, video_key) is not None
            scenes.append(
                SceneEstimate(
                    scene_index=scene.scene_index,
                    tts_usd=0.0 if audio_cached else tts_spec.price.estimate(),
                    video_usd=0.0 if video_cached else video_spec.price.estimate(),
                    cached=audio_cached and video_cached,
                )
            )
        return CostEstimate.from_scenes(scenes, spent_usd=job.ledger.total)
