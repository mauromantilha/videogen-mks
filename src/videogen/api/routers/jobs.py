"""Rotas de jobs (RF-01, RF-11): criar, listar, consultar, cancelar, retomar, reabrir, clonar."""

from fastapi import APIRouter, Depends, Response, status

from videogen.api.auth import require_auth
from videogen.api.deps import JobId, Services
from videogen.api.dto.jobs import API, JobSummary, JobView
from videogen.domain.request import JobRequest

router = APIRouter(prefix=API, tags=["jobs"], dependencies=[Depends(require_auth)])


@router.post("/jobs", status_code=status.HTTP_202_ACCEPTED)
async def create_job(body: JobRequest, services: Services, response: Response) -> JobView:
    """Cria o job e gera o roteiro em segundo plano (acompanhe por `links.events`)."""
    state = await services.creation.create(body)
    response.headers["Location"] = f"{API}/jobs/{state.job_id}"
    return JobView.of(state)


@router.get("/jobs")
async def list_jobs(services: Services) -> list[JobSummary]:
    return [JobSummary.of(job) for job in await services.repo.list_all()]


@router.get("/jobs/{job_id}")
async def get_job(job_id: JobId, services: Services) -> JobView:
    return JobView.of(await services.repo.get(job_id))


@router.post("/jobs/{job_id}/cancel", status_code=status.HTTP_202_ACCEPTED)
async def cancel_job(job_id: JobId, services: Services) -> JobView:
    return JobView.of(await services.control.cancel(job_id))


@router.post("/jobs/{job_id}/retry", status_code=status.HTTP_202_ACCEPTED)
async def retry_job(job_id: JobId, services: Services) -> JobView:
    return JobView.of(await services.control.retry(job_id))


@router.post("/jobs/{job_id}/reopen")
async def reopen_job(job_id: JobId, services: Services) -> JobView:
    """Volta um job concluído/falho para revisão; reaprovar re-renderiza só o que mudou."""
    return JobView.of(await services.control.reopen(job_id))


@router.post("/jobs/{job_id}/clone", status_code=status.HTTP_201_CREATED)
async def clone_job(job_id: JobId, services: Services, response: Response) -> JobView:
    state = await services.creation.clone(job_id)
    response.headers["Location"] = f"{API}/jobs/{state.job_id}"
    return JobView.of(state)
