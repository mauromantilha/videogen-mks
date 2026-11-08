"""Estimativa de custo e aprovação (RF-08, RF-09)."""

from fastapi import APIRouter, Depends, status

from videogen.api.auth import require_auth
from videogen.api.deps import Services
from videogen.api.dto.jobs import API, JobView
from videogen.api.dto.script import ApproveBody
from videogen.api.ownership import JobId
from videogen.domain.cost import CostEstimate

router = APIRouter(prefix=f"{API}/jobs/{{job_id}}", tags=["aprovação"],
                   dependencies=[Depends(require_auth)])  # fmt: skip


@router.get("/estimate")
async def estimate(job_id: JobId, services: Services) -> CostEstimate:
    return await services.approval.estimate(job_id)


@router.post("/approve", status_code=status.HTTP_202_ACCEPTED)
async def approve(job_id: JobId, body: ApproveBody, services: Services) -> JobView:
    """Congela a versão exibida e libera a Etapa 2. 409 se a versão mudou; 422 se estourar."""
    state = await services.approval.approve(
        job_id, script_version=body.script_version, max_budget_usd=body.max_budget_usd
    )
    return JobView.of(state)
