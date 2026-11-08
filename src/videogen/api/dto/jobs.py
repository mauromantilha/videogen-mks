"""Visões do job para a API."""

from datetime import datetime

from pydantic import BaseModel

from videogen.domain.job import JobState
from videogen.domain.progress import ErrorInfo, StepState
from videogen.domain.request import JobRequest
from videogen.domain.script import VideoScriptSchema
from videogen.domain.status import FailedStage, JobStatus

API = "/api/v1"


class StepView(BaseModel):
    status: str
    cached: bool
    attempts: int
    cost_usd: float
    error: ErrorInfo | None

    @classmethod
    def of(cls, step: StepState) -> "StepView":
        return cls(
            status=step.status,
            cached=step.cached,
            attempts=step.attempts,
            cost_usd=step.cost_usd,
            error=step.error,
        )  # sem remote_id/hash


class SceneView(BaseModel):
    scene_index: int
    audio: StepView
    video: StepView
    clip: StepView


class CostView(BaseModel):
    llm_usd: float
    tts_usd: float
    video_usd: float
    total_usd: float
    budget_usd: float | None


class JobView(BaseModel):
    job_id: str
    status: JobStatus
    failed_stage: FailedStage | None
    request: JobRequest
    script_version: int
    script: VideoScriptSchema | None
    approved_version: int | None
    scenes: list[SceneView]
    cost: CostView
    error: ErrorInfo | None
    has_final: bool
    created_at: datetime
    updated_at: datetime
    links: dict[str, str]

    @classmethod
    def of(cls, job: JobState) -> "JobView":
        base = f"{API}/jobs/{job.job_id}"
        links = {"self": base, "events": f"{base}/events", "script": f"{base}/script",
                 "estimate": f"{base}/estimate"}  # fmt: skip
        if job.final_hash:
            links["final"] = f"{base}/artifacts/final"
        ledger = job.ledger
        return cls(
            job_id=job.job_id, status=job.status, failed_stage=job.failed_stage,
            request=job.request, script_version=job.script_version, script=job.script,
            approved_version=job.approval.script_version if job.approval else None,
            scenes=[SceneView(scene_index=s.scene_index, audio=StepView.of(s.audio),
                              video=StepView.of(s.video), clip=StepView.of(s.clip))
                    for s in job.scenes],
            cost=CostView(llm_usd=ledger.llm_usd, tts_usd=ledger.tts_usd,
                          video_usd=ledger.video_usd, total_usd=ledger.total,
                          budget_usd=job.approval.max_budget_usd if job.approval else None),
            error=job.error, has_final=job.final_hash is not None,
            created_at=job.created_at, updated_at=job.updated_at, links=links,
        )  # fmt: skip


class JobSummary(BaseModel):
    job_id: str
    status: JobStatus
    tema: str
    spent_usd: float
    created_at: datetime
    updated_at: datetime

    @classmethod
    def of(cls, job: JobState) -> "JobSummary":
        return cls(job_id=job.job_id, status=job.status, tema=job.request.tema,
                   spent_usd=job.ledger.total, created_at=job.created_at,
                   updated_at=job.updated_at)  # fmt: skip
