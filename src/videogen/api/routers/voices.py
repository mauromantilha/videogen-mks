"""Vozes de referência (RF-12): upload multipart, listagem e remoção."""

from typing import Annotated

from fastapi import APIRouter, Depends, Form, UploadFile, status

from videogen.api.auth import require_auth
from videogen.api.deps import Services, VoiceId
from videogen.api.dto.jobs import API
from videogen.api.dto.voices import VoiceView
from videogen.services.voices import InvalidVoice, VoiceLimits

router = APIRouter(prefix=API, tags=["vozes"], dependencies=[Depends(require_auth)])
CHUNK = 1 << 20


@router.post("/voices", status_code=status.HTTP_201_CREATED)
async def create_voice(
    audio: UploadFile,
    name: Annotated[str, Form(min_length=1, max_length=80)],
    ref_text: Annotated[str, Form(min_length=1, max_length=1000)],
    services: Services,
) -> VoiceView:
    data = await _read_limited(audio, VoiceLimits().max_upload_bytes)
    voice = await services.voices.register(data, filename=audio.filename or "",
                                           name=name, ref_text=ref_text)  # fmt: skip
    return VoiceView.of(voice)


@router.get("/voices")
async def list_voices(services: Services) -> list[VoiceView]:
    return [VoiceView.of(voice) for voice in await services.voice_store.list_all()]


@router.delete("/voices/{voice_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_voice(voice_id: VoiceId, services: Services) -> None:
    await services.voice_store.delete(voice_id)


async def _read_limited(upload: UploadFile, limit: int) -> bytes:
    chunks: list[bytes] = []
    size = 0
    while chunk := await upload.read(CHUNK):
        size += len(chunk)
        if size > limit:
            raise InvalidVoice(f"arquivo maior que {limit} bytes")
        chunks.append(chunk)
    return b"".join(chunks)
