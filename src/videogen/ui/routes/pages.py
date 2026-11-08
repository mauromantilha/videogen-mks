"""Páginas: lista + novo vídeo e a página do job (só os do usuário logado)."""

from typing import Any, get_args

from fastapi import APIRouter, Depends, Request, Response, status
from fastapi.responses import RedirectResponse
from pydantic import ValidationError

from videogen.api.deps import Services
from videogen.api.ownership import JobId
from videogen.core.errors import DomainError
from videogen.domain.catalog import ModelKind
from videogen.domain.identity import CurrentUser
from videogen.domain.request import JobRequest
from videogen.ui.auth import UiUser, require_ui_auth
from videogen.ui.responses import page
from videogen.ui.view_model import job_context

router = APIRouter(include_in_schema=False)
Auth = [Depends(require_ui_auth)]


@router.get("/", dependencies=Auth)
async def index(request: Request, services: Services, user: UiUser) -> Response:
    return page(request, "index.html", **await _index_context(services, user))


@router.post("/jobs", dependencies=Auth)
async def create_job(request: Request, services: Services, user: UiUser) -> Response:
    form = await request.form()
    try:
        job_request = JobRequest.model_validate(_job_payload(form))
        state = await services.creation.create(job_request, owner_id=user.user_id)
    except (ValidationError, DomainError) as exc:
        message = exc.message if isinstance(exc, DomainError) else _first_error(exc)
        context = await _index_context(services, user)
        return page(request, "index.html", status.HTTP_422_UNPROCESSABLE_CONTENT,
                    error=message, form=dict(form), **context)  # fmt: skip
    return RedirectResponse(f"/jobs/{state.job_id}", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/jobs/{job_id}", dependencies=Auth)
async def job_page(request: Request, job_id: JobId, services: Services) -> Response:
    return page(request, "job.html", **job_context(await services.repo.get(job_id)))


async def _index_context(services: Services, user: CurrentUser) -> dict[str, Any]:
    kinds: tuple[ModelKind, ...] = get_args(ModelKind)
    jobs = await services.repo.list_all()
    voices = await services.voice_store.list_all()
    return {
        "jobs": [job for job in jobs if user.can_access(job.owner_id)],
        "voices": [voice for voice in voices if user.can_access(voice.owner_id)],
        "models": {kind: services.models.available(kind) for kind in kinds},
    }


def _job_payload(form: Any) -> dict[str, Any]:
    return {
        "tema": form.get("tema", ""),
        "aspect_ratio": form.get("aspect_ratio", "9:16"),
        "n_cenas": form.get("n_cenas", 5),
        "voice_id": form.get("voice_id", ""),
        "max_budget_usd": form.get("max_budget_usd", 2),
        "models": {"llm": form.get("llm"), "tts": form.get("tts"), "video": form.get("video")},
        "options": {"resolution": form.get("resolution", "480p"), "fps": form.get("fps", 30),
                    "duracao_cena_s": form.get("duracao_cena_s", 4),
                    "legendas": form.get("legendas") == "on"},
    }  # fmt: skip


def _first_error(exc: ValidationError) -> str:
    error = exc.errors()[0]
    field = ".".join(str(part) for part in error["loc"])
    return f"{field}: {error['msg']}"
