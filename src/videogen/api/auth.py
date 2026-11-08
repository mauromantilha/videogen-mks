"""Sessão por usuário (RNF-07): cookie HttpOnly `vg_session` com o token do provedor.

Modo `local` (sem provedor): sem login, só conexões do próprio host, como um admin local.
Modo `neon`: o token do cookie é validado no Neon Auth (com cache curto) e o e-mail precisa ser
de um membro ativo. A UI e a API usam a mesma sessão.
"""

from typing import Annotated

from fastapi import Depends, HTTPException, Request, status

from videogen.api.deps import get_services
from videogen.domain.identity import LOCAL_USER, CurrentUser

SESSION_COOKIE = "vg_session"
LOOPBACK = frozenset({"127.0.0.1", "::1", "localhost"})
_STATE_KEY = "current_user"
MAX_TOKEN_CHARS = 4096


async def current_user(request: Request) -> CurrentUser | None:
    """Resolve uma vez por requisição (fica em `request.state`)."""
    if hasattr(request.state, _STATE_KEY):
        cached: CurrentUser | None = getattr(request.state, _STATE_KEY)
        return cached
    user = await _resolve(request)
    setattr(request.state, _STATE_KEY, user)
    return user


async def _resolve(request: Request) -> CurrentUser | None:
    auth = get_services(request).auth
    if auth is None:
        host = request.client.host if request.client else ""
        return LOCAL_USER if host in LOOPBACK else None
    token = request.cookies.get(SESSION_COOKIE, "")
    if not token or len(token) > MAX_TOKEN_CHARS:
        return None
    return await auth.resolve(token)


async def require_auth(request: Request) -> CurrentUser:
    """API: 401 em problem+json. (A UI redireciona para o login — ver ui/auth.py.)"""
    user = await current_user(request)
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "sessão ausente ou expirada")
    return user


User = Annotated[CurrentUser, Depends(require_auth)]
