"""Download e pré-visualização (RF-13), com HTTP Range (FileResponse do Starlette).

Caminhos nunca vêm do cliente: o arquivo é achado pelo hash registrado no job.
"""

from typing import Literal

from fastapi import APIRouter, Depends
from fastapi.responses import FileResponse

from videogen.api.auth import require_auth
from videogen.api.deps import SceneIndex, Services
from videogen.api.dto.jobs import API
from videogen.api.ownership import JobId
from videogen.core.errors import NotFound
from videogen.domain.media import ArtifactKind
from videogen.ports.cache import ArtifactCache

router = APIRouter(prefix=f"{API}/jobs/{{job_id}}", tags=["artefatos"],
                   dependencies=[Depends(require_auth)])  # fmt: skip
SceneArtifact = Literal["audio", "video", "clip"]
SCENE_KINDS: dict[str, tuple[ArtifactKind, str]] = {
    "audio": (ArtifactKind.AUDIO_NORM, "audio/wav"),
    "video": (ArtifactKind.VIDEO_RAW, "video/mp4"),
    "clip": (ArtifactKind.CLIP, "video/mp4"),
}


@router.get("/artifacts/final")
async def final_video(job_id: JobId, services: Services) -> FileResponse:
    job = await services.repo.get(job_id)
    path = _cached(services.cache, ArtifactKind.FINAL, job.final_hash)
    return FileResponse(path, media_type="video/mp4", filename=f"{job_id}.mp4")


@router.get("/scenes/{index}/{artifact}")
async def scene_artifact(
    job_id: JobId, index: SceneIndex, artifact: SceneArtifact, services: Services
) -> FileResponse:
    job = await services.repo.get(job_id)
    if index >= len(job.scenes):
        raise NotFound(f"cena {index} não existe neste render")
    kind, media_type = SCENE_KINDS[artifact]
    step = job.scenes[index].step(artifact)
    return FileResponse(_cached(services.cache, kind, step.artifact_hash), media_type=media_type)


def _cached(cache: ArtifactCache, kind: ArtifactKind, key: str | None) -> str:
    path = cache.get(kind, key) if key else None
    if path is None:
        raise NotFound("artefato ainda não disponível")
    return str(path)
