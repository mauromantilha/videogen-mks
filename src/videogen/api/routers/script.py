"""Rotas do roteiro (RF-07): ler, substituir, editar cena, adicionar, remover, mover, regenerar."""

from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from videogen.api.auth import require_auth
from videogen.api.deps import SceneIndex, Services
from videogen.api.dto.jobs import API, JobView
from videogen.api.dto.script import (
    AddSceneBody,
    EditResponse,
    MoveSceneBody,
    PatchSceneBody,
    RegenerateBody,
    ReplaceScriptBody,
    ScriptView,
    VersionedBody,
    ViolationView,
)
from videogen.api.ownership import JobId
from videogen.domain.script_rules import validate_rules
from videogen.services.script.edit_service import EditResult

router = APIRouter(prefix=f"{API}/jobs/{{job_id}}", tags=["roteiro"],
                   dependencies=[Depends(require_auth)])  # fmt: skip


def _edited(result: EditResult) -> EditResponse:
    violations = ViolationView.many(result.violations)
    return EditResponse(script_version=result.state.script_version, violations=violations)


@router.get("/script")
async def get_script(job_id: JobId, services: Services) -> ScriptView:
    job = await services.repo.get(job_id)
    script = job.require_script()
    violations = validate_rules(script, job.request.script_limits())
    return ScriptView(script_version=job.script_version, script=script,
                      violations=ViolationView.many(violations))  # fmt: skip


@router.put("/script")
async def replace_script(
    job_id: JobId, body: ReplaceScriptBody, services: Services
) -> EditResponse:
    return _edited(await services.edits.replace_script(job_id, body.script, body.expected_version))


@router.patch("/script/scenes/{index}")
async def patch_scene(
    job_id: JobId, index: SceneIndex, body: PatchSceneBody, services: Services
) -> EditResponse:
    result = await services.edits.patch_scene(job_id, index, body.fields(), body.expected_version)
    return _edited(result)


@router.post("/script/scenes", status_code=status.HTTP_201_CREATED)
async def add_scene(job_id: JobId, body: AddSceneBody, services: Services) -> EditResponse:
    scene = {"texto_narrado": body.texto_narrado, "prompt_video": body.prompt_video}
    return _edited(await services.edits.add_scene(job_id, body.after_index, scene,
                                                   body.expected_version))  # fmt: skip


@router.delete("/script/scenes/{index}")
async def remove_scene(
    job_id: JobId, index: SceneIndex, services: Services,
    expected_version: Annotated[int, Query(ge=0)],
) -> EditResponse:  # fmt: skip
    return _edited(await services.edits.remove_scene(job_id, index, expected_version))


@router.post("/script/scenes/{index}/move")
async def move_scene(
    job_id: JobId, index: SceneIndex, body: MoveSceneBody, services: Services
) -> EditResponse:
    result = await services.edits.move_scene(job_id, index, body.target, body.expected_version)
    return _edited(result)


@router.post("/script/scenes/{index}/reseed")
async def reseed_scene(
    job_id: JobId, index: SceneIndex, body: VersionedBody, services: Services
) -> EditResponse:
    """ "Gerar outra versão": nova seed só para esta cena."""
    return _edited(await services.edits.bump_seed(job_id, index, body.expected_version))


@router.post("/script/regenerate", status_code=status.HTTP_202_ACCEPTED)
async def regenerate(job_id: JobId, body: RegenerateBody, services: Services) -> JobView:
    state = await services.control.request_regeneration(
        job_id, feedback=body.feedback, scene_index=body.scene_index
    )
    return JobView.of(state)
