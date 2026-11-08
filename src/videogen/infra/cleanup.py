"""Limpeza por TTL (T-026). Nunca toca em job ativo nem em artefato referenciado por um job.

Ordem: temporários órfãos → jobs terminais vencidos → cache vencido e não referenciado.
Remover um job primeiro libera os hashes que só ele usava.
"""

import asyncio
import shutil
from dataclasses import dataclass
from datetime import timedelta

from videogen.core.clock import Clock
from videogen.domain.job import JobState
from videogen.domain.status import JobStatus
from videogen.infra.artifact_cache import FileArtifactCache
from videogen.infra.workspace import Workspace
from videogen.ports.repository import JobRepository

TERMINAL = frozenset({JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELED})


@dataclass(frozen=True)
class RetentionPolicy:
    jobs_days: int = 14
    cache_days: int = 30


@dataclass(frozen=True)
class CleanupReport:
    partials: int
    jobs: int
    artifacts: int


class WorkspaceJanitor:
    def __init__(
        self, workspace: Workspace, repo: JobRepository, cache: FileArtifactCache, clock: Clock
    ) -> None:
        self._workspace = workspace
        self._repo = repo
        self._cache = cache
        self._clock = clock

    async def run(self, policy: RetentionPolicy) -> CleanupReport:
        partials = await asyncio.to_thread(self._remove_partials)
        jobs = await self._repo.list_all()
        expired = [job for job in jobs if self._job_expired(job, policy)]
        for job in expired:
            await asyncio.to_thread(shutil.rmtree, self._workspace.job_dir(job.job_id))
        kept = [job for job in jobs if job not in expired]
        artifacts = await asyncio.to_thread(self._remove_artifacts, kept, policy)
        return CleanupReport(partials=partials, jobs=len(expired), artifacts=artifacts)

    def _remove_partials(self) -> int:
        removed = self._cache.remove_partials()
        for tmp_dir in self._workspace.jobs_dir.glob("job_*/tmp"):
            shutil.rmtree(tmp_dir, ignore_errors=True)
            removed += 1
        return removed

    def _job_expired(self, job: JobState, policy: RetentionPolicy) -> bool:
        limit = self._clock.now() - timedelta(days=policy.jobs_days)
        return job.status in TERMINAL and job.updated_at < limit

    def _remove_artifacts(self, jobs: list[JobState], policy: RetentionPolicy) -> int:
        referenced = {ref for job in jobs for ref in _referenced_hashes(job)}
        limit = (self._clock.now() - timedelta(days=policy.cache_days)).timestamp()
        removed = 0
        for _kind, key, path in self._cache.entries():
            if key in referenced or path.stat().st_mtime >= limit:
                continue
            path.unlink(missing_ok=True)
            path.with_name(f"{path.stem}.meta.json").unlink(missing_ok=True)
            removed += 1
        return removed


def _referenced_hashes(job: JobState) -> set[str]:
    steps = [step for scene in job.scenes for step in (scene.audio, scene.video, scene.clip)]
    hashes = {step.artifact_hash for step in steps if step.artifact_hash}
    return hashes | ({job.final_hash} if job.final_hash else set())
