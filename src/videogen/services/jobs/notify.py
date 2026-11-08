"""Publicação do estado do job no barramento (compartilhado pelos serviços de jobs)."""

from videogen.domain.events import JobStatusChanged
from videogen.domain.job import JobState
from videogen.ports.events import EventBus


def publish_status(bus: EventBus, state: JobState) -> None:
    event = JobStatusChanged(status=state.status, failed_stage=state.failed_stage)
    bus.publish(state.job_id, event)
