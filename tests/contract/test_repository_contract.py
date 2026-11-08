"""Contrato do JobRepository: o dublê em memória e o adapter JSON se comportam igual (T-021)."""

import asyncio
from pathlib import Path

import pytest

from tests.fakes.builders import JOB_ID, make_job
from tests.fakes.fake_clock import FakeClock
from tests.fakes.memory_repository import InMemoryJobRepository
from videogen.core.errors import AlreadyExists, NotFound, VersionConflict
from videogen.domain.job import JobState
from videogen.domain.status import JobStatus
from videogen.infra.job_repository import JsonJobRepository
from videogen.infra.workspace import Workspace
from videogen.ports.repository import JobRepository


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture(params=["memory", "json"])
async def repo(request: pytest.FixtureRequest, clock: FakeClock, tmp_path: Path) -> JobRepository:
    repository: JobRepository = (
        InMemoryJobRepository(clock)
        if request.param == "memory"
        else JsonJobRepository(Workspace(tmp_path), clock)
    )
    await repository.create(make_job(JobStatus.AWAITING_APPROVAL))
    return repository


def test_implementa_o_port(repo: JobRepository) -> None:
    assert isinstance(repo, JobRepository)


async def test_update_incrementa_revisao_e_carimba_horario(
    repo: JobRepository, clock: FakeClock
) -> None:
    clock.advance(60)
    updated = await repo.update(JOB_ID, lambda s: s.transition_to(JobStatus.SCRIPTING))
    assert (updated.revision, updated.status, updated.updated_at) == (
        1,
        JobStatus.SCRIPTING,
        clock.now(),
    )
    assert await repo.get(JOB_ID) == updated


async def test_revisao_otimista(repo: JobRepository) -> None:
    await repo.update(JOB_ID, lambda s: None, expected_revision=0)
    with pytest.raises(VersionConflict):
        await repo.update(JOB_ID, lambda s: None, expected_revision=0)


async def test_estado_invalido_nunca_e_gravado(repo: JobRepository) -> None:
    def corrupt(state: JobState) -> None:
        state.status = JobStatus.RENDERING  # sem aprovação: viola invariante

    with pytest.raises(ValueError, match="aprovado"):
        await repo.update(JOB_ID, corrupt)
    stored = await repo.get(JOB_ID)
    assert (stored.status, stored.revision) == (JobStatus.AWAITING_APPROVAL, 0)


async def test_erro_no_mutator_nao_grava_nada(repo: JobRepository) -> None:
    def explode(state: JobState) -> None:
        state.script_version = 7
        raise RuntimeError("falhou no meio")

    with pytest.raises(RuntimeError):
        await repo.update(JOB_ID, explode)
    assert (await repo.get(JOB_ID)).script_version == 1


async def test_copias_sao_independentes(repo: JobRepository) -> None:
    copy = await repo.get(JOB_ID)
    copy.script_version = 99
    assert (await repo.get(JOB_ID)).script_version == 1


async def test_50_updates_concorrentes_sem_perda(repo: JobRepository) -> None:
    def bump(state: JobState) -> None:
        state.ledger.add("llm", 0.001)

    await asyncio.gather(*(repo.update(JOB_ID, bump) for _ in range(50)))
    stored = await repo.get(JOB_ID)
    assert stored.revision == 50
    assert stored.ledger.llm_usd == pytest.approx(0.05)


async def test_erros_de_existencia(repo: JobRepository) -> None:
    with pytest.raises(AlreadyExists):
        await repo.create(make_job())
    with pytest.raises(NotFound):
        await repo.get("job_ffffffffffff")
    with pytest.raises(NotFound):
        await repo.update("job_ffffffffffff", lambda s: None)
    assert [job.job_id for job in await repo.list_all()] == [JOB_ID]
