"""Progresso por cena e por etapa (RF-10). Artefatos são referenciados por hash."""

from enum import StrEnum
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field

from videogen.core.errors import DomainError

StepName = Literal["audio", "video", "clip"]
_MAX_MESSAGE = 500


class StepStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"


class ErrorInfo(BaseModel):
    """Erro serializável no estado do job (sem stack trace nem detalhes internos)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    code: str
    message: str
    retryable: bool = False

    @classmethod
    def from_exception(cls, exc: BaseException) -> Self:
        if isinstance(exc, DomainError):
            return cls(code=exc.code, message=exc.message[:_MAX_MESSAGE], retryable=exc.retryable)
        return cls(code="INTERNAL_ERROR", message=type(exc).__name__)


class StepState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: StepStatus = StepStatus.PENDING
    artifact_hash: str | None = None
    remote_id: str | None = None  # id da predição no provedor (retomada após crash)
    cached: bool = False
    attempts: int = Field(default=0, ge=0)
    cost_usd: float = Field(default=0.0, ge=0)
    error: ErrorInfo | None = None

    def start(self) -> None:
        self.status, self.error = StepStatus.RUNNING, None
        self.attempts += 1

    def mark_cached(self, artifact_hash: str) -> None:
        self.status, self.artifact_hash, self.cached, self.error = (
            StepStatus.DONE,
            artifact_hash,
            True,
            None,
        )

    def finish(self, artifact_hash: str, cost_usd: float = 0.0) -> None:
        self.status, self.artifact_hash, self.cached, self.error = (
            StepStatus.DONE,
            artifact_hash,
            False,
            None,
        )
        self.cost_usd += cost_usd

    def fail(self, error: ErrorInfo) -> None:
        self.status, self.error = StepStatus.FAILED, error

    def reset_failed(self) -> None:
        """Retry: etapa falha volta a pendente; `remote_id` é mantido para retomar."""
        if self.status is StepStatus.FAILED:
            self.status, self.error = StepStatus.PENDING, None


class SceneProgress(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scene_index: int = Field(ge=0)
    audio: StepState = Field(default_factory=StepState)  # TTS + loudnorm
    video: StepState = Field(default_factory=StepState)  # T2V
    clip: StepState = Field(default_factory=StepState)  # sync + legenda + encode

    def step(self, name: StepName) -> StepState:
        return {"audio": self.audio, "video": self.video, "clip": self.clip}[name]

    @property
    def done(self) -> bool:
        return all(s.status is StepStatus.DONE for s in (self.audio, self.video, self.clip))

    @property
    def failed(self) -> bool:
        return any(s.status is StepStatus.FAILED for s in (self.audio, self.video, self.clip))
