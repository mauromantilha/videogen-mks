"""Página de vozes: upload (multipart, sem JS), lista e remoção."""

from typing import Annotated

from fastapi import APIRouter, Depends, Form, Request, Response, UploadFile, status
from fastapi.responses import RedirectResponse

from videogen.api.deps import Services
from videogen.api.ownership import VoiceId
from videogen.core.errors import DomainError
from videogen.domain.identity import CurrentUser
from videogen.domain.media import VoiceRef
from videogen.services.voices import VoiceLimits
from videogen.ui.auth import UiUser, require_ui_auth
from videogen.ui.responses import page

router = APIRouter(include_in_schema=False, dependencies=[Depends(require_ui_auth)])


@router.get("/voices")
async def voices_page(request: Request, services: Services, user: UiUser) -> Response:
    return page(request, "voices.html", voices=await _voices(services, user),
                limits=VoiceLimits())  # fmt: skip


@router.post("/voices")
async def upload_voice(
    request: Request, services: Services, user: UiUser, audio: UploadFile,
    name: Annotated[str, Form()], ref_text: Annotated[str, Form()],
) -> Response:  # fmt: skip
    try:
        data = await audio.read(VoiceLimits().max_upload_bytes + 1)
        await services.voices.register(data, filename=audio.filename or "", name=name,
                                       ref_text=ref_text, owner_id=user.user_id)  # fmt: skip
    except DomainError as exc:
        return page(request, "voices.html", status.HTTP_422_UNPROCESSABLE_CONTENT,
                    voices=await _voices(services, user), limits=VoiceLimits(),
                    error=exc.message, form={"name": name, "ref_text": ref_text})  # fmt: skip
    return RedirectResponse("/voices", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/voices/{voice_id}/delete")
async def delete_voice(voice_id: VoiceId, services: Services) -> Response:
    await services.voice_store.delete(voice_id)
    return RedirectResponse("/voices", status_code=status.HTTP_303_SEE_OTHER)


async def _voices(services: Services, user: CurrentUser) -> list[VoiceRef]:
    return [v for v in await services.voice_store.list_all() if user.can_access(v.owner_id)]
