"""Páginas: login, lista + novo vídeo e a página do job."""

from typing import Annotated, Any, get_args

from fastapi import APIRouter, Depends, Form, Request, Response, status
from fastapi.responses import RedirectResponse
from pydantic import ValidationError

from videogen.api.auth import COOKIE_NAME, key_matches
from videogen.api.deps import JobId, Services
from videogen.core.errors import DomainError
from videogen.domain.catalog import ModelKind
from videogen.domain.request import JobRequest
from videogen.ui.auth import require_ui_auth, safe_next
from videogen.ui.responses import page
from videogen.ui.view_model import job_context

router = APIRouter(include_in_schema=False)
Auth = [Depends(require_ui_auth)]
COOKIE_MAX_AGE = 7 * 24 * 3600


@router.get("/login")
async def login_form(request: Request, next: str | None = None) -> Response:
    return page(request, "login.html", next=safe_next(next))


@router.post("/login")
async def login(
    request: Request, services: Services,
    api_key: Annotated[str, Form()], next: Annotated[str, Form()] = "/",
) -> Response:  # fmt: skip
    expected = services.api_key
    if expected is not None and not key_matches(api_key, expected):
        return page(request, "login.html", status.HTTP_401_UNAUTHORIZED, next=safe_next(next),
                    error="Chave inválida.")  # fmt: skip
    response = RedirectResponse(safe_next(next), status_code=status.HTTP_303_SEE_OTHER)
    response.set_cookie(COOKIE_NAME, api_key, max_age=COOKIE_MAX_AGE, httponly=True,
                        samesite="lax", secure=request.url.scheme == "https")  # fmt: skip
    return response


@router.post("/logout")
async def logout() -> Response:
    response = RedirectResponse("/login", status_code=status.HTTP_303_SEE_OTHER)
    response.delete_cookie(COOKIE_NAME)
    return response


@router.get("/", dependencies=Auth)
async def index(request: Request, services: Services) -> Response:
    return page(request, "index.html", **await _index_context(services))


@router.post("/jobs", dependencies=Auth)
async def create_job(request: Request, services: Services) -> Response:
    form = await request.form()
    try:
        state = await services.creation.create(JobRequest.model_validate(_job_payload(form)))
    except (ValidationError, DomainError) as exc:
        message = exc.message if isinstance(exc, DomainError) else _first_error(exc)
        return page(request, "index.html", status.HTTP_422_UNPROCESSABLE_CONTENT,
                    error=message, form=dict(form), **await _index_context(services))  # fmt: skip
    return RedirectResponse(f"/jobs/{state.job_id}", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/jobs/{job_id}", dependencies=Auth)
async def job_page(request: Request, job_id: JobId, services: Services) -> Response:
    return page(request, "job.html", **job_context(await services.repo.get(job_id)))


async def _index_context(services: Services) -> dict[str, Any]:
    kinds: tuple[ModelKind, ...] = get_args(ModelKind)
    return {
        "jobs": await services.repo.list_all(),
        "voices": await services.voice_store.list_all(),
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
