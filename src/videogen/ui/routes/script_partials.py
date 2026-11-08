"""Fragmentos HTMX do editor de roteiro: salvar campo, operações de cena, estimativa, aprovar."""

from typing import Annotated

from fastapi import APIRouter, Depends, Form, Request, Response

from videogen.api.deps import JobId, SceneIndex, Services
from videogen.core.errors import DomainError
from videogen.ui.auth import require_ui_auth
from videogen.ui.responses import flash_error, page, refresh
from videogen.ui.view_model import scene_status_context

router = APIRouter(prefix="/ui/jobs/{job_id}", include_in_schema=False,
                   dependencies=[Depends(require_ui_auth)])  # fmt: skip
Version = Annotated[int, Form(alias="expected_version")]
NEW_SCENE = {
    "texto_narrado": "Nova cena.",
    "prompt_video": "Describe the new shot: subject, action, setting, light, camera.",
}


@router.patch("/scenes/{index}")
async def save_field(request: Request, job_id: JobId, index: SceneIndex, services: Services,
                     expected_version: Version) -> Response:  # fmt: skip
    form = await request.form()
    fields = {k: form[k] for k in ("texto_narrado", "prompt_video") if k in form}
    try:
        result = await services.edits.patch_scene(job_id, index, fields, expected_version)
    except DomainError as exc:
        return flash_error(request, exc)
    response = page(request, "_scene_status.html", **scene_status_context(result.state, index))
    response.headers["HX-Trigger"] = "script-changed"
    return response


@router.post("/scenes/{index}/reseed")
async def reseed(request: Request, job_id: JobId, index: SceneIndex, services: Services,
                 expected_version: Version) -> Response:  # fmt: skip
    try:
        await services.edits.bump_seed(job_id, index, expected_version)
    except DomainError as exc:
        return flash_error(request, exc)
    return refresh()


@router.post("/scenes/{index}/move")
async def move(request: Request, job_id: JobId, index: SceneIndex, services: Services,
               expected_version: Version, target: Annotated[int, Form()]) -> Response:  # fmt: skip
    try:
        await services.edits.move_scene(job_id, index, target, expected_version)
    except DomainError as exc:
        return flash_error(request, exc)
    return refresh()


@router.post("/scenes/{index}/delete")
async def delete(request: Request, job_id: JobId, index: SceneIndex, services: Services,
                 expected_version: Version) -> Response:  # fmt: skip
    try:
        await services.edits.remove_scene(job_id, index, expected_version)
    except DomainError as exc:
        return flash_error(request, exc)
    return refresh()


@router.post("/scenes/{index}/add-after")
async def add_after(request: Request, job_id: JobId, index: SceneIndex, services: Services,
                    expected_version: Version) -> Response:  # fmt: skip
    try:
        await services.edits.add_scene(job_id, index, NEW_SCENE, expected_version)
    except DomainError as exc:
        return flash_error(request, exc)
    return refresh()


@router.post("/regenerate")
async def regenerate(request: Request, job_id: JobId, services: Services,
                     feedback: Annotated[str, Form(max_length=500)] = "",
                     scene_index: Annotated[str, Form()] = "") -> Response:  # fmt: skip
    try:
        await services.control.request_regeneration(
            job_id, feedback=feedback or None,
            scene_index=int(scene_index) if scene_index.isdigit() else None)  # fmt: skip
    except DomainError as exc:
        return flash_error(request, exc)
    return refresh()


@router.get("/estimate")
async def estimate(request: Request, job_id: JobId, services: Services) -> Response:
    job = await services.repo.get(job_id)
    return page(request, "_estimate.html", estimate=await services.approval.estimate(job_id),
                budget=job.request.max_budget_usd)  # fmt: skip


@router.post("/approve")
async def approve(request: Request, job_id: JobId, services: Services, expected_version: Version,
                  max_budget_usd: Annotated[float, Form(gt=0, le=100)]) -> Response:  # fmt: skip
    try:
        await services.approval.approve(job_id, script_version=expected_version,
                                        max_budget_usd=max_budget_usd)  # fmt: skip
    except DomainError as exc:
        return flash_error(request, exc)
    return refresh()
