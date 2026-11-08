"""T-017/T-018: dublês satisfazem os ports; tamanho dos ports. Semântica: tests/contract/."""

from pathlib import Path

import pytest
from tests.fakes.builders import JOB_ID
from tests.fakes.fake_clock import FakeClock
from tests.fakes.identity import FakeIdentityProvider
from tests.fakes.memory_cache import InMemoryArtifactCache
from tests.fakes.memory_repository import InMemoryJobRepository
from tests.fakes.recording_bus import RecordingEventBus

from videogen.domain.events import JobStatusChanged
from videogen.domain.status import JobStatus
from videogen.infra.members_file import FileMemberDirectory
from videogen.ports.cache import ArtifactCache
from videogen.ports.events import EventBus
from videogen.ports.identity import IdentityProvider, MemberDirectory, SessionVerifier
from videogen.ports.repository import JobRepository


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


def test_dubles_satisfazem_os_ports(tmp_path: Path, clock: FakeClock) -> None:
    assert isinstance(InMemoryJobRepository(clock), JobRepository)
    assert isinstance(InMemoryArtifactCache(tmp_path), ArtifactCache)
    assert isinstance(RecordingEventBus(clock), EventBus)
    identity = FakeIdentityProvider()
    assert isinstance(identity, IdentityProvider) and isinstance(identity, SessionVerifier)
    assert isinstance(FileMemberDirectory(tmp_path / "m.json"), MemberDirectory)


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
    # + ProviderResolver, ScriptHistory (M5), HealthCheck (M6); IdentityProvider, SessionVerifier,
    # MemberDirectory (login por usuário)
    assert len(protocols) == 16
    for protocol in protocols:
        methods = [
            name
            for name in vars(protocol)
            if callable(getattr(protocol, name)) and not name.startswith("_")
        ]
        assert 1 <= len(methods) <= 5, (protocol.__name__, methods)
