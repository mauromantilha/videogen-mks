"""Página de vozes: upload (multipart, sem JS), lista e remoção."""

from typing import Annotated

from fastapi import APIRouter, Depends, Form, Request, Response, UploadFile, status
from fastapi.responses import RedirectResponse

from videogen.api.deps import Services, VoiceId
from videogen.core.errors import DomainError
from videogen.services.voices import VoiceLimits
from videogen.ui.auth import require_ui_auth
from videogen.ui.responses import page

router = APIRouter(include_in_schema=False, dependencies=[Depends(require_ui_auth)])


@router.get("/voices")
async def voices_page(request: Request, services: Services) -> Response:
    return page(request, "voices.html", voices=await services.voice_store.list_all(),
                limits=VoiceLimits())  # fmt: skip


@router.post("/voices")
async def upload_voice(
    request: Request, services: Services, audio: UploadFile,
    name: Annotated[str, Form()], ref_text: Annotated[str, Form()],
) -> Response:  # fmt: skip
    try:
        data = await audio.read(VoiceLimits().max_upload_bytes + 1)
        await services.voices.register(data, filename=audio.filename or "", name=name,
                                       ref_text=ref_text)  # fmt: skip
    except DomainError as exc:
        return page(request, "voices.html", status.HTTP_422_UNPROCESSABLE_CONTENT,
                    voices=await services.voice_store.list_all(), limits=VoiceLimits(),
                    error=exc.message, form={"name": name, "ref_text": ref_text})  # fmt: skip
    return RedirectResponse("/voices", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/voices/{voice_id}/delete")
async def delete_voice(voice_id: VoiceId, services: Services) -> Response:
    await services.voice_store.delete(voice_id)
    return RedirectResponse("/voices", status_code=status.HTTP_303_SEE_OTHER)
