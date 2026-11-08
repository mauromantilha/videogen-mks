"""T-023: fan-out, replay por Last-Event-ID, descarte de lento e auditoria."""

import asyncio
from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from tests.fakes.builders import JOB_ID, make_job
from tests.fakes.fake_clock import FakeClock
from videogen.domain.events import Event, JobStatusChanged, ScriptUpdated
from videogen.domain.status import JobStatus
from videogen.infra.event_audit import EventAuditLog
from videogen.infra.event_bus import InMemoryEventBus
from videogen.infra.job_repository import JsonJobRepository
from videogen.infra.workspace import Workspace
from videogen.ports.events import EventBus


def _status(status: JobStatus = JobStatus.RENDERING) -> JobStatusChanged:
    return JobStatusChanged(status=status)


async def _take(stream: AsyncIterator[Event], count: int) -> list[int]:
    return [(await anext(stream)).seq for _ in range(count)]


@pytest.fixture
def bus() -> InMemoryEventBus:
    return InMemoryEventBus(FakeClock(), buffer_size=5, queue_size=3)


def test_implementa_o_port(bus: InMemoryEventBus) -> None:
    assert isinstance(bus, EventBus)


async def test_seq_monotonico_por_job(bus: InMemoryEventBus) -> None:
    seqs = [bus.publish(JOB_ID, _status()).seq for _ in range(3)]
    assert seqs == [1, 2, 3]
    assert bus.publish("job_ffffffffffff", _status()).seq == 1


async def test_varios_assinantes_recebem_tudo_em_ordem(bus: InMemoryEventBus) -> None:
    streams = [bus.subscribe(JOB_ID) for _ in range(3)]
    readers = [asyncio.create_task(_take(stream, 2)) for stream in streams]
    await asyncio.sleep(0)  # assinaturas registradas
    bus.publish(JOB_ID, _status())
    bus.publish(JOB_ID, ScriptUpdated(script_version=2))
    assert await asyncio.gather(*readers) == [[1, 2]] * 3


async def test_replay_a_partir_do_ultimo_id_sem_duplicar(bus: InMemoryEventBus) -> None:
    for _ in range(4):
        bus.publish(JOB_ID, _status())
    stream = bus.subscribe(JOB_ID, last_event_id=2)
    first = await _take(stream, 2)
    bus.publish(JOB_ID, _status())
    assert first + await _take(stream, 1) == [3, 4, 5]
    await stream.aclose()


async def test_replay_limitado_ao_buffer(bus: InMemoryEventBus) -> None:
    for _ in range(8):
        bus.publish(JOB_ID, _status())
    stream = bus.subscribe(JOB_ID, last_event_id=0)
    assert await _take(stream, 5) == [4, 5, 6, 7, 8]  # buffer de 5; o resto via snapshot
    await stream.aclose()


async def test_assinante_lento_e_encerrado_sem_bloquear_publish(bus: InMemoryEventBus) -> None:
    stream = bus.subscribe(JOB_ID)
    reader = asyncio.create_task(_drain(stream))
    await asyncio.sleep(0)
    for _ in range(10):  # fila de 3: publish nunca bloqueia
        bus.publish(JOB_ID, _status())
    assert await asyncio.wait_for(reader, 1) == []  # recebeu o fim antes de ler eventos
    assert bus.subscriber_count(JOB_ID) == 0


async def _drain(stream: AsyncIterator[Event]) -> list[int]:
    return [event.seq async for event in stream]


async def test_desconexao_libera_assinatura(bus: InMemoryEventBus) -> None:
    stream = bus.subscribe(JOB_ID)
    reader = asyncio.create_task(anext(stream))
    await asyncio.sleep(0)
    assert bus.subscriber_count(JOB_ID) == 1
    reader.cancel()
    await asyncio.gather(reader, return_exceptions=True)
    await stream.aclose()
    assert bus.subscriber_count(JOB_ID) == 0


async def test_close_job_encerra_streams(bus: InMemoryEventBus) -> None:
    reader = asyncio.create_task(_drain(bus.subscribe(JOB_ID)))
    await asyncio.sleep(0)
    bus.close_job(JOB_ID)
    assert await asyncio.wait_for(reader, 1) == []


async def test_auditoria_em_jsonl_e_falha_de_sink_nao_derruba(tmp_path: Path) -> None:
    workspace = Workspace(tmp_path)
    await JsonJobRepository(workspace, FakeClock()).create(make_job())
    audit = EventAuditLog(workspace)
    bus = InMemoryEventBus(FakeClock())

    def broken_sink(_: Event) -> None:
        raise RuntimeError("disco cheio")

    bus.add_sink(broken_sink)
    bus.add_sink(audit)
    published = [bus.publish(JOB_ID, _status(s)) for s in (JobStatus.APPROVED, JobStatus.RENDERING)]
    assert audit.read(JOB_ID) == published
    bus.publish("job_ffffffffffff", _status())  # job sem diretório: ignorado
    assert audit.read("job_ffffffffffff") == []
