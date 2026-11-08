"""Port do barramento de eventos do job (SSE e auditoria)."""

from collections.abc import AsyncIterator
from typing import Protocol, runtime_checkable

from videogen.domain.events import Event, EventPayload


@runtime_checkable
class EventBus(Protocol):
    def publish(self, job_id: str, payload: EventPayload) -> Event:
        """Não bloqueia; atribui `seq` e entrega a todos os assinantes."""
        ...

    def subscribe(self, job_id: str, last_event_id: int | None = None) -> AsyncIterator[Event]:
        """Reenvia eventos com `seq > last_event_id` ainda no buffer e segue ao vivo."""
        ...
