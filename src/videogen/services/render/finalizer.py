"""Concatenação final (RF-06): rendering → finalizing → completed, cache `final` por hash.

Reexecutar sem mudanças não roda FFmpeg: o hash final (lista ordenada de clipes) já existe.
"""

from videogen.core.errors import MediaError
from videogen.domain.hashing import final_hash
from videogen.domain.job import JobState
from videogen.domain.media import ArtifactKind
from videogen.domain.progress import ErrorInfo
from videogen.domain.render_specs import ConcatParams
from videogen.ports.cache import ArtifactCache
from videogen.ports.composer import MediaComposer
from videogen.services.render.job_tracker import JobTracker

CONCAT = ConcatParams()


class Finalizer:
    def __init__(self, cache: ArtifactCache, composer: MediaComposer, jobs: JobTracker) -> None:
        self._cache = cache
        self._composer = composer
        self._jobs = jobs

    async def run(self, job_id: str) -> JobState:
        state = await self._jobs.begin_finalizing(job_id)
        try:
            key = await self._concat(state)
        except Exception as exc:
            return await self._jobs.fail(job_id, "finalizing", [ErrorInfo.from_exception(exc)])
        return await self._jobs.complete(job_id, key)

    async def _concat(self, state: JobState) -> str:
        clip_keys = [scene.clip.artifact_hash for scene in state.scenes]
        if not all(clip_keys):
            raise MediaError("há cenas sem clipe composto")
        keys = [key for key in clip_keys if key]
        final_key = final_hash(keys, CONCAT)
        if self._cache.get(ArtifactKind.FINAL, final_key) is not None:
            return final_key
        clips = []
        for key in keys:
            path = self._cache.get(ArtifactKind.CLIP, key)
            if path is None:
                raise MediaError(f"clipe {key[:12]}… não está mais no cache")
            clips.append(path)
        tmp = self._cache.tmp_path(ArtifactKind.FINAL, final_key)
        try:
            await self._composer.concat(clips, tmp, CONCAT)
            self._cache.commit(ArtifactKind.FINAL, final_key, tmp, {"clips": len(keys)})
        finally:
            tmp.unlink(missing_ok=True)
        return final_key
