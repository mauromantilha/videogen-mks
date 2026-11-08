"""Estado persistido de um job (manifesto `job_state.json`)."""

from datetime import datetime
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from videogen.core.errors import InvalidTransition
from videogen.core.ids import JOB_ID_RE
from videogen.domain.cost import CostLedger
from videogen.domain.progress import ErrorInfo, SceneProgress
from videogen.domain.request import MAX_BUDGET_CEILING_USD, JobRequest
from videogen.domain.script import VideoScriptSchema
from videogen.domain.status import FailedStage, JobStatus, ensure_transition

FROZEN_STATES = frozenset(
    {JobStatus.APPROVED, JobStatus.RENDERING, JobStatus.FINALIZING, JobStatus.COMPLETED}
)


class Approval(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    script_version: int = Field(ge=1)
    approved_at: datetime
    max_budget_usd: float = Field(gt=0, le=MAX_BUDGET_CEILING_USD)


class JobState(BaseModel):
    """Fonte da verdade do job. Mutado só dentro de `JobRepository.update`."""

    model_config = ConfigDict(extra="forbid")

    job_id: str = Field(pattern=JOB_ID_RE.pattern)
    revision: int = Field(default=0, ge=0)  # concorrência otimista do manifesto
    owner_id: str | None = None  # usuário dono (None: criado antes do login por usuário)
    status: JobStatus = JobStatus.SCRIPTING
    failed_stage: FailedStage | None = None
    request: JobRequest
    script_version: int = Field(default=0, ge=0)
    script: VideoScriptSchema | None = None
    approval: Approval | None = None  # preenchido ⇒ roteiro congelado
    scenes: list[SceneProgress] = Field(default_factory=list)
    final_hash: str | None = None
    ledger: CostLedger = Field(default_factory=CostLedger)
    error: ErrorInfo | None = None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def new(
        cls, job_id: str, request: JobRequest, now: datetime, owner_id: str | None = None
    ) -> Self:
        return cls(job_id=job_id, request=request, owner_id=owner_id, created_at=now,
                   updated_at=now)  # fmt: skip

    @model_validator(mode="after")
    def _invariants(self) -> Self:
        if (self.status is JobStatus.FAILED) != (self.failed_stage is not None):
            raise ValueError("failed_stage existe se, e somente se, o status for failed")
        awaiting = self.status is JobStatus.AWAITING_APPROVAL
        if awaiting and (self.script is None or self.approval is not None):
            raise ValueError("awaiting_approval exige roteiro e nenhuma aprovação vigente")
        if self.status in FROZEN_STATES:
            self._check_frozen()
        return self

    def _check_frozen(self) -> None:
        if self.script is None or self.approval is None:
            raise ValueError(f"{self.status} exige roteiro aprovado")
        if self.approval.script_version != self.script_version:
            raise ValueError("versão aprovada difere da versão do roteiro")
        if [scene.scene_index for scene in self.scenes] != list(range(len(self.script.cenas))):
            raise ValueError("progresso deve ter uma entrada por cena, em ordem")

    @property
    def is_frozen(self) -> bool:
        return self.approval is not None

    def ensure_status(self, *allowed: JobStatus) -> None:
        if self.status not in allowed:
            expected = ", ".join(allowed)
            raise InvalidTransition(f"job está em {self.status}; exige {expected}")

    def require_script(self) -> VideoScriptSchema:
        if self.script is None:
            raise InvalidTransition("o job ainda não tem roteiro")
        return self.script

    def transition_to(self, target: JobStatus) -> None:
        ensure_transition(self.status, target, self.failed_stage)
        if self.status is JobStatus.FAILED:
            self.failed_stage, self.error = None, None
        self.status = target

    def fail(self, stage: FailedStage, error: ErrorInfo) -> None:
        ensure_transition(self.status, JobStatus.FAILED)
        self.status, self.failed_stage, self.error = JobStatus.FAILED, stage, error
