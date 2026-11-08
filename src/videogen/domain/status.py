"""Máquina de estados do job: tabela canônica de transições (design.md §4)."""

from enum import StrEnum
from typing import Literal

from videogen.core.errors import InvalidTransition

FailedStage = Literal["scripting", "rendering", "finalizing"]


class JobStatus(StrEnum):
    SCRIPTING = "scripting"
    AWAITING_APPROVAL = "awaiting_approval"
    APPROVED = "approved"
    RENDERING = "rendering"
    FINALIZING = "finalizing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELED = "canceled"


S = JobStatus
TRANSITIONS: dict[JobStatus, frozenset[JobStatus]] = {
    S.SCRIPTING: frozenset({S.AWAITING_APPROVAL, S.FAILED, S.CANCELED}),
    S.AWAITING_APPROVAL: frozenset({S.SCRIPTING, S.APPROVED, S.CANCELED}),
    S.APPROVED: frozenset({S.RENDERING, S.CANCELED}),
    S.RENDERING: frozenset({S.FINALIZING, S.FAILED, S.CANCELED}),
    S.FINALIZING: frozenset({S.COMPLETED, S.FAILED, S.CANCELED}),
    S.FAILED: frozenset({S.SCRIPTING, S.RENDERING, S.AWAITING_APPROVAL, S.CANCELED}),
    S.COMPLETED: frozenset({S.AWAITING_APPROVAL}),  # reopen
    S.CANCELED: frozenset(),
}
# Saídas de FAILED dependem de onde a falha ocorreu (retry volta à mesma etapa).
_RETRY_TARGET_BY_STAGE: dict[JobStatus, frozenset[str]] = {
    S.SCRIPTING: frozenset({"scripting"}),
    S.RENDERING: frozenset({"rendering", "finalizing"}),
}
ACTIVE_STATES = frozenset({S.SCRIPTING, S.APPROVED, S.RENDERING, S.FINALIZING})


def can_transition(
    source: JobStatus, target: JobStatus, failed_stage: FailedStage | None = None
) -> bool:
    if target not in TRANSITIONS[source]:
        return False
    stages = _RETRY_TARGET_BY_STAGE.get(target)
    return source is not S.FAILED or stages is None or failed_stage in stages


def ensure_transition(
    source: JobStatus, target: JobStatus, failed_stage: FailedStage | None = None
) -> None:
    if not can_transition(source, target, failed_stage):
        detail = f" (falha em {failed_stage})" if failed_stage else ""
        raise InvalidTransition(
            f"transição inválida: {source} → {target}{detail}",
            source=str(source),
            target=str(target),
        )
