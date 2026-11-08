"""EventBus que só grava os eventos (assinatura devolve o histórico, sem esperar novos)."""

from collections import defaultdict
from collections.abc import AsyncIterator
from typing import TYPE_CHECKING

from videogen.core.clock import Clock
from videogen.domain.events import Event, EventPayload


class RecordingEventBus:
    def __init__(self, clock: Clock) -> None:
        self._clock = clock
        self.events: defaultdict[str, list[Event]] = defaultdict(list)

    def publish(self, job_id: str, payload: EventPayload) -> Event:
        history = self.events[job_id]
        event = Event(seq=len(history) + 1, job_id=job_id, ts=self._clock.now(), data=payload)
        history.append(event)
        return event

    async def subscribe(
        self, job_id: str, last_event_id: int | None = None
    ) -> AsyncIterator[Event]:
        for event in list(self.events[job_id]):
            if last_event_id is None or event.seq > last_event_id:
                yield event

    def types(self, job_id: str) -> list[str]:
        return [event.type for event in self.events[job_id]]


if TYPE_CHECKING:
    from tests.fakes.fake_clock import FakeClock
    from videogen.ports.events import EventBus

    _conforms: EventBus = RecordingEventBus(FakeClock())
