"""EventBus em memória (design/02 §6): fan-out por job, replay curto e descarte de lentos.

O manifesto é a verdade; o bus só acelera a UI. Um assinante que não acompanha recebe o fim
do stream (sentinela None) e deve reconectar pedindo snapshot.
"""

import asyncio
import logging
from collections import deque
from collections.abc import AsyncIterator, Callable

from videogen.core.clock import Clock
from videogen.domain.events import Event, EventPayload

logger = logging.getLogger(__name__)
EventSink = Callable[[Event], None]
_Queue = asyncio.Queue[Event | None]


class _Channel:
    def __init__(self, buffer_size: int) -> None:
        self.seq = 0
        self.buffer: deque[Event] = deque(maxlen=buffer_size)
        self.subscribers: set[_Queue] = set()


class InMemoryEventBus:
    def __init__(self, clock: Clock, *, buffer_size: int = 200, queue_size: int = 256) -> None:
        self._clock = clock
        self._buffer_size = buffer_size
        self._queue_size = queue_size
        self._channels: dict[str, _Channel] = {}
        self._sinks: list[EventSink] = []

    def add_sink(self, sink: EventSink) -> None:
        """Assinante síncrono interno (ex.: auditoria em `events.jsonl`)."""
        self._sinks.append(sink)

    def publish(self, job_id: str, payload: EventPayload) -> Event:
        channel = self._channel(job_id)
        channel.seq += 1
        event = Event(seq=channel.seq, job_id=job_id, ts=self._clock.now(), data=payload)
        channel.buffer.append(event)
        for queue in list(channel.subscribers):
            self._deliver(channel, queue, event)
        for sink in self._sinks:
            try:
                sink(event)
            except Exception:
                logger.exception("falha em assinante interno de eventos", extra={"job_id": job_id})
        return event

    async def subscribe(
        self, job_id: str, last_event_id: int | None = None
    ) -> AsyncIterator[Event]:
        channel = self._channel(job_id)
        backlog = [e for e in channel.buffer if last_event_id is not None and e.seq > last_event_id]
        queue: _Queue = asyncio.Queue(maxsize=self._queue_size)
        channel.subscribers.add(queue)
        try:
            for event in backlog:
                yield event
            while (event_or_end := await queue.get()) is not None:
                yield event_or_end
        finally:
            channel.subscribers.discard(queue)

    def close_job(self, job_id: str) -> None:
        """Encerra todos os streams do job (ex.: job removido)."""
        channel = self._channels.pop(job_id, None)
        for queue in list(channel.subscribers) if channel else []:
            _end(queue)

    def subscriber_count(self, job_id: str) -> int:
        channel = self._channels.get(job_id)
        return len(channel.subscribers) if channel else 0

    def _channel(self, job_id: str) -> _Channel:
        return self._channels.setdefault(job_id, _Channel(self._buffer_size))

    @staticmethod
    def _deliver(channel: _Channel, queue: _Queue, event: Event) -> None:
        try:
            queue.put_nowait(event)
        except asyncio.QueueFull:
            channel.subscribers.discard(queue)
            _end(queue)
            logger.warning("assinante lento descartado", extra={"job_id": event.job_id})


def _end(queue: _Queue) -> None:
    """Esvazia a fila e entrega a sentinela de fim (sempre cabe após esvaziar)."""
    while not queue.empty():
        queue.get_nowait()
    queue.put_nowait(None)
