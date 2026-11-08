"""Fragmentos do acompanhamento: progresso ao vivo e ações do job (cancelar, retomar...)."""

from fastapi import APIRouter, Depends, Request, Response

from videogen.api.deps import Services
from videogen.api.ownership import JobId
from videogen.core.errors import DomainError
from videogen.ui.auth import UiUser, require_ui_auth
from videogen.ui.responses import flash_error, page, refresh
from videogen.ui.view_model import job_context

router = APIRouter(prefix="/ui/jobs/{job_id}", include_in_schema=False,
                   dependencies=[Depends(require_ui_auth)])  # fmt: skip


@router.get("/refresh")
async def refresh_page() -> Response:
    """Disparado pelo SSE em `job.status`: o estado mudou, recarrega a página."""
    return refresh()


@router.get("/progress")
async def progress(request: Request, job_id: JobId, services: Services) -> Response:
    return page(request, "_progress.html", **job_context(await services.repo.get(job_id)))


@router.post("/cancel")
async def cancel(request: Request, job_id: JobId, services: Services) -> Response:
    try:
        await services.control.cancel(job_id)
    except DomainError as exc:
        return flash_error(request, exc)
    return refresh()


@router.post("/retry")
async def retry(request: Request, job_id: JobId, services: Services) -> Response:
    try:
        await services.control.retry(job_id)
    except DomainError as exc:
        return flash_error(request, exc)
    return refresh()


@router.post("/reopen")
async def reopen(request: Request, job_id: JobId, services: Services) -> Response:
    try:
        await services.control.reopen(job_id)
    except DomainError as exc:
        return flash_error(request, exc)
    return refresh()


@router.post("/clone")
async def clone(request: Request, job_id: JobId, services: Services, user: UiUser) -> Response:
    try:
        state = await services.creation.clone(job_id, owner_id=user.user_id)
    except DomainError as exc:
        return flash_error(request, exc)
    return Response(status_code=204, headers={"HX-Redirect": f"/jobs/{state.job_id}"})
