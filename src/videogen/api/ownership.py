"""Ids de rota que só resolvem para o dono: job/voz de outro usuário responde 404, como se
não existisse (não revela ids alheios). Vale para a API e para a UI.
"""

from typing import Annotated

from fastapi import Depends, HTTPException, Path, Request, status

from videogen.api.auth import current_user
from videogen.api.deps import get_services
from videogen.core.errors import NotFound
from videogen.core.ids import JOB_ID_RE, VOICE_ID_RE
from videogen.domain.identity import CurrentUser


async def _user(request: Request) -> CurrentUser:
    user = await current_user(request)
    if user is None:  # a dependência de login do router já barra; isto é defesa em profundidade
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "sessão ausente ou expirada")
    return user


async def owned_job_id(
    request: Request,
    job_id: Annotated[str, Path(pattern=JOB_ID_RE.pattern, description="job_<12 hex>")],
) -> str:
    user = await _user(request)
    state = await get_services(request).repo.get(job_id)
    if not user.can_access(state.owner_id):
        raise NotFound("job não encontrado", job_id=job_id)
    return job_id


async def owned_voice_id(
    request: Request, voice_id: Annotated[str, Path(pattern=VOICE_ID_RE.pattern)]
) -> str:
    user = await _user(request)
    voice = await get_services(request).voice_store.get(voice_id)
    if not user.can_access(voice.owner_id):
        raise NotFound("voz não encontrada", voice_id=voice_id)
    return voice_id


JobId = Annotated[str, Depends(owned_job_id)]
VoiceId = Annotated[str, Depends(owned_voice_id)]
