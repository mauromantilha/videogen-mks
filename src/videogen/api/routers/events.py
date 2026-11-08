"""Progresso em tempo real por SSE (RF-10).

Primeiro um `snapshot` com o job inteiro (o manifesto é a verdade); depois os eventos, com
replay por `Last-Event-ID`. Heartbeat mantém proxies acordados. Termina quando o job chega a
um estado final ou o cliente desconecta.
"""

import asyncio
from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import APIRouter, Depends, Header
from fastapi.responses import StreamingResponse

from videogen.api.auth import require_auth
from videogen.api.deps import Services
from videogen.api.dto.jobs import API, JobView
from videogen.api.ownership import JobId
from videogen.domain.events import Event, JobStatusChanged
from videogen.domain.status import JobStatus
from videogen.ports.events import EventBus

router = APIRouter(prefix=API, tags=["eventos"], dependencies=[Depends(require_auth)])
HEARTBEAT_S = 15.0
FINAL = frozenset({JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELED})
SSE_HEADERS = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}


@router.get("/jobs/{job_id}/events")
async def job_events(
    job_id: JobId,
    services: Services,
    last_event_id: Annotated[int | None, Header(alias="Last-Event-ID")] = None,
) -> StreamingResponse:
    snapshot = JobView.of(await services.repo.get(job_id))
    stream = event_stream(services.bus, snapshot, last_event_id, HEARTBEAT_S)
    return StreamingResponse(stream, media_type="text/event-stream", headers=SSE_HEADERS)


async def event_stream(
    bus: EventBus, snapshot: JobView, last_event_id: int | None, heartbeat_s: float
) -> AsyncIterator[str]:
    yield f"event: snapshot\ndata: {snapshot.model_dump_json()}\n\n"
    if snapshot.status in FINAL:
        return
    events = bus.subscribe(snapshot.job_id, last_event_id)
    pending: asyncio.Future[Event] | None = None
    try:
        while True:
            pending = pending or asyncio.ensure_future(anext(events))
            done, _ = await asyncio.wait({pending}, timeout=heartbeat_s)
            if not done:
                yield ": ping\n\n"
                continue
            try:
                event = pending.result()
            except StopAsyncIteration:
                return
            pending = None
            yield event.to_sse()
            if isinstance(event.data, JobStatusChanged) and event.data.status in FINAL:
                return
    finally:
        if pending is not None:
            pending.cancel()
        await events.aclose()  # type: ignore[attr-defined]
