"""T-017/T-018: dublês satisfazem os ports e têm a semântica dos adapters reais."""

import asyncio
from pathlib import Path

import pytest
from tests.fakes.builders import JOB_ID, make_job
from tests.fakes.fake_clock import FakeClock
from tests.fakes.memory_cache import InMemoryArtifactCache
from tests.fakes.memory_repository import InMemoryJobRepository
from tests.fakes.recording_bus import RecordingEventBus

from videogen.core.errors import AlreadyExists, NotFound, VersionConflict
from videogen.domain.events import JobStatusChanged
from videogen.domain.job import JobState
from videogen.domain.media import ArtifactKind
from videogen.domain.status import JobStatus
from videogen.ports.cache import ArtifactCache
from videogen.ports.events import EventBus
from videogen.ports.repository import JobRepository


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
async def repo(clock: FakeClock) -> InMemoryJobRepository:
    repository = InMemoryJobRepository(clock)
    await repository.create(make_job(JobStatus.AWAITING_APPROVAL))
    return repository


def test_dubles_satisfazem_os_ports(tmp_path: Path, clock: FakeClock) -> None:
    assert isinstance(InMemoryJobRepository(clock), JobRepository)
    assert isinstance(InMemoryArtifactCache(tmp_path), ArtifactCache)
    assert isinstance(RecordingEventBus(clock), EventBus)


async def test_update_incrementa_revisao_e_carimba_horario(
    repo: InMemoryJobRepository, clock: FakeClock
) -> None:
    clock.advance(60)
    updated = await repo.update(JOB_ID, lambda s: s.transition_to(JobStatus.SCRIPTING))
    assert (updated.revision, updated.status, updated.updated_at) == (
        1,
        JobStatus.SCRIPTING,
        clock.now(),
    )


async def test_revisao_otimista(repo: InMemoryJobRepository) -> None:
    await repo.update(JOB_ID, lambda s: None, expected_revision=0)
    with pytest.raises(VersionConflict):
        await repo.update(JOB_ID, lambda s: None, expected_revision=0)


async def test_estado_invalido_nunca_e_gravado(repo: InMemoryJobRepository) -> None:
    def corrupt(state: JobState) -> None:
        state.status = JobStatus.RENDERING  # sem aprovação: viola invariante

    with pytest.raises(ValueError, match="aprovado"):
        await repo.update(JOB_ID, corrupt)
    stored = await repo.get(JOB_ID)
    assert (stored.status, stored.revision) == (JobStatus.AWAITING_APPROVAL, 0)


async def test_copias_sao_independentes(repo: InMemoryJobRepository) -> None:
    copy = await repo.get(JOB_ID)
    copy.script_version = 99
    assert (await repo.get(JOB_ID)).script_version == 1


async def test_50_updates_concorrentes_sem_perda(repo: InMemoryJobRepository) -> None:
    def bump(state: JobState) -> None:
        state.ledger.add("llm", 0.001)

    await asyncio.gather(*(repo.update(JOB_ID, bump) for _ in range(50)))
    stored = await repo.get(JOB_ID)
    assert stored.revision == 50
    assert stored.ledger.llm_usd == pytest.approx(0.05)


async def test_erros_de_existencia(repo: InMemoryJobRepository) -> None:
    with pytest.raises(AlreadyExists):
        await repo.create(make_job())
    with pytest.raises(NotFound):
        await repo.get("job_ffffffffffff")
    assert [job.job_id for job in await repo.list_all()] == [JOB_ID]


def test_cache_parciais_nao_sao_hit(tmp_path: Path) -> None:
    cache = InMemoryArtifactCache(tmp_path)
    kind = ArtifactKind.VIDEO_RAW
    tmp = cache.tmp_path(kind, "h1")
    tmp.write_bytes(b"meio arquivo")
    assert cache.get(kind, "h1") is None  # ainda não commitado
    final = cache.commit(kind, "h1", tmp, {"remote_id": "p1"})
    assert cache.get(kind, "h1") == final and not tmp.exists()
    assert cache.get(ArtifactKind.AUDIO_RAW, "h1") is None


async def test_bus_numera_e_reenvia_a_partir_do_ultimo_id(clock: FakeClock) -> None:
    bus = RecordingEventBus(clock)
    for status in (JobStatus.SCRIPTING, JobStatus.AWAITING_APPROVAL, JobStatus.APPROVED):
        bus.publish(JOB_ID, JobStatusChanged(status=status))
    replay = [event.seq async for event in bus.subscribe(JOB_ID, last_event_id=1)]
    assert replay == [2, 3]
    assert bus.types(JOB_ID) == ["job.status"] * 3


def _port_protocols() -> list[type]:
    import importlib
    import inspect
    import pkgutil
    from typing import Protocol

    import videogen.ports as package

    found: list[type] = []
    for info in pkgutil.iter_modules(package.__path__):
        module = importlib.import_module(f"videogen.ports.{info.name}")
        found += [
            obj
            for obj in vars(module).values()
            if inspect.isclass(obj)
            and Protocol in obj.__bases__
            and obj.__module__ == module.__name__
        ]
    return found


def test_cada_port_tem_no_maximo_5_metodos() -> None:
    protocols = _port_protocols()
    assert len(protocols) == 10
    for protocol in protocols:
        methods = [
            name
            for name in vars(protocol)
            if callable(getattr(protocol, name)) and not name.startswith("_")
        ]
        assert 1 <= len(methods) <= 5, (protocol.__name__, methods)
