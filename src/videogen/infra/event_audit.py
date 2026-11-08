"""Auditoria append-only dos eventos em `jobs/{job_id}/events.jsonl` (RNF-08).

Escrita síncrona de uma linha (~200 bytes) por evento: custo desprezível frente ao I/O de rede,
e mantém a ordem exata do `seq` sem precisar de uma task extra.
"""

import logging

from videogen.domain.events import Event
from videogen.infra.workspace import Workspace

logger = logging.getLogger(__name__)


class EventAuditLog:
    def __init__(self, workspace: Workspace) -> None:
        self._workspace = workspace

    def __call__(self, event: Event) -> None:
        path = self._workspace.events_path(event.job_id)
        if not path.parent.is_dir():
            return  # job ainda não persistido (ou removido): nada a auditar
        with path.open("a", encoding="utf-8") as handle:
            handle.write(event.model_dump_json() + "\n")

    def read(self, job_id: str) -> list[Event]:
        path = self._workspace.events_path(job_id)
        if not path.is_file():
            return []
        lines = path.read_text(encoding="utf-8").splitlines()
        return [Event.model_validate_json(line) for line in lines if line.strip()]
