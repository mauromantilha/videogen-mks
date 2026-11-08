"""Eventos do job: contrato único do SSE (RF-10) e do `events.jsonl` (auditoria)."""

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from videogen.domain.progress import ErrorInfo, StepName, StepStatus
from videogen.domain.status import FailedStage, JobStatus

_FROZEN = ConfigDict(extra="forbid", frozen=True)


class JobStatusChanged(BaseModel):
    model_config = _FROZEN
    type: Literal["job.status"] = "job.status"
    status: JobStatus
    failed_stage: FailedStage | None = None


class ScriptUpdated(BaseModel):
    model_config = _FROZEN
    type: Literal["script.updated"] = "script.updated"
    script_version: int = Field(ge=1)


class SceneStepChanged(BaseModel):
    model_config = _FROZEN
    type: Literal["scene.step"] = "scene.step"
    scene_index: int = Field(ge=0)
    step: StepName
    status: StepStatus
    cached: bool = False
    cost_usd: float = Field(default=0.0, ge=0)


class JobCostChanged(BaseModel):
    model_config = _FROZEN
    type: Literal["job.cost"] = "job.cost"
    spent_usd: float = Field(ge=0)
    budget_usd: float | None = None


class JobCompleted(BaseModel):
    model_config = _FROZEN
    type: Literal["job.completed"] = "job.completed"
    final_hash: str


class JobFailed(BaseModel):
    model_config = _FROZEN
    type: Literal["job.failed"] = "job.failed"
    error: ErrorInfo


EventPayload = Annotated[
    JobStatusChanged | ScriptUpdated | SceneStepChanged | JobCostChanged | JobCompleted | JobFailed,
    Field(discriminator="type"),
]
TERMINAL_EVENT_TYPES = frozenset({"job.completed", "job.failed"})


class Event(BaseModel):
    """Envelope com `seq` monotônico por job (usado como `id:` do SSE)."""

    model_config = _FROZEN

    seq: int = Field(ge=1)
    job_id: str
    ts: datetime
    data: EventPayload

    @property
    def type(self) -> str:
        return self.data.type

    def to_sse(self) -> str:
        return f"id: {self.seq}\nevent: {self.type}\ndata: {self.data.model_dump_json()}\n\n"
