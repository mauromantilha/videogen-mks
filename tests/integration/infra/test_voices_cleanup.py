"""T-025 (vozes) e T-026 (limpeza por TTL)."""

import hashlib
import os
from pathlib import Path

import pytest

from tests.fakes.builders import JOB_ID, make_job
from tests.fakes.fake_clock import FakeClock
from videogen.core.errors import NotFound
from videogen.domain.job import JobState
from videogen.domain.media import ArtifactKind
from videogen.domain.status import JobStatus
from videogen.infra.artifact_cache import FileArtifactCache
from videogen.infra.cleanup import RetentionPolicy, WorkspaceJanitor
from videogen.infra.job_repository import JsonJobRepository
from videogen.infra.voice_store import FileVoiceStore
from videogen.infra.workspace import Workspace
from videogen.ports.voices import VoiceStore

DAY = 86_400.0


@pytest.fixture
def workspace(tmp_path: Path) -> Workspace:
    ws = Workspace(tmp_path)
    ws.ensure_layout()
    return ws


async def test_ciclo_de_vida_da_voz(workspace: Workspace) -> None:
    store = FileVoiceStore(workspace, FakeClock())
    assert isinstance(store, VoiceStore)
    first = await store.save(b"RIFF-a", name="Mauro", ref_text="Olá.", duration_s=6.0)
    second = await store.save(b"RIFF-a", name="Cópia", ref_text="Olá.", duration_s=6.0)

    assert first.sha256 == second.sha256 == hashlib.sha256(b"RIFF-a").hexdigest()
    assert first.voice_id != second.voice_id
    assert first.path.read_bytes() == b"RIFF-a"
    assert await store.get(first.voice_id) == first
    assert {v.voice_id for v in await store.list_all()} == {first.voice_id, second.voice_id}

    await store.delete(first.voice_id)
    with pytest.raises(NotFound):
        await store.get(first.voice_id)
    with pytest.raises(NotFound):
        await store.delete(first.voice_id)
    with pytest.raises(NotFound):
        await store.get("../../etc")


def _artifact(cache: FileArtifactCache, key: str, age_days: float, clock: FakeClock) -> Path:
    tmp = cache.tmp_path(ArtifactKind.CLIP, key)
    tmp.write_bytes(b"mp4")
    path = cache.commit(ArtifactKind.CLIP, key, tmp, {})
    stamp = clock.now().timestamp() - age_days * DAY
    os.utime(path, (stamp, stamp))
    return path


async def _job(repo: JsonJobRepository, job_id: str, status: JobStatus, clip: str) -> JobState:
    job = make_job(status).model_copy(update={"job_id": job_id})
    if job.scenes:
        job.scenes[0].clip.artifact_hash = clip
    return await repo.create(JobState.model_validate(job.model_dump()))


async def test_limpeza_respeita_ttl_estado_e_referencias(workspace: Workspace) -> None:
    clock = FakeClock()
    repo = JsonJobRepository(workspace, clock)
    cache = FileArtifactCache(workspace.cache_dir)
    keys = {"antigo": "a" * 64, "bloqueado": "b" * 64, "fresco": "c" * 64, "liberado": "d" * 64}
    for name, age in (("antigo", 40), ("bloqueado", 40), ("fresco", 1), ("liberado", 40)):
        _artifact(cache, keys[name], age, clock)

    await _job(repo, JOB_ID, JobStatus.RENDERING, keys["bloqueado"])  # ativo: intocável
    await _job(repo, "job_aaaaaaaaaaaa", JobStatus.COMPLETED, keys["liberado"])
    cache.tmp_path(ArtifactKind.CLIP, keys["fresco"]).write_bytes(b"parcial")
    (workspace.job_tmp_dir(JOB_ID)).mkdir(parents=True)

    clock.advance(20 * DAY)  # concluído há 20 dias > 14
    report = await WorkspaceJanitor(workspace, repo, cache, clock).run(RetentionPolicy())

    assert (report.jobs, report.partials) == (1, 2)
    assert [job.job_id for job in await repo.list_all()] == [JOB_ID]
    remaining = {key for _, key, _ in cache.entries()}
    assert remaining == {keys["bloqueado"], keys["fresco"]}
    assert report.artifacts == 2  # "antigo" e "liberado" (job removido liberou o hash)
